#!/usr/bin/env python3
"""Smoke-validate every ComfyUI workflow template against the live server.

Stack venv, stdlib only. For each workflows/*.json (except manifest.json):
  (a) json-parse it
  (b) verify every class_type exists in /object_info
  (c) verify every _meta.title in manifest.json's patchable map exists in the
      file and the referenced input field exists on that node
  (d) POST the graph to /prompt with a client_id and read the response:
        - HTTP 200 + prompt_id  -> clean queue == validated; the item is
          IMMEDIATELY deleted from the queue and /interrupt is called so no
          real generation ever runs.
        - HTTP 400 whose node_errors are ONLY missing-FILE errors on PATCH_
          placeholders (checkpoints, loras, LoadImage files) -> PASS-with-note.
        - any other node/schema error -> FAIL.

Prints a per-template PASS / PASS-with-note / FAIL table and exits nonzero on
any FAIL.
"""
import glob
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
HERE = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.path.normpath(os.path.join(HERE, "..", "workflows"))
MANIFEST = os.path.join(WF_DIR, "manifest.json")
TIMEOUT = 30


def _get(path):
    with urllib.request.urlopen(COMFY + path, timeout=TIMEOUT) as r:
        return json.load(r)


def _post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        COMFY + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"_raw": body}


def valid_inputs(objinfo, class_type):
    """Set of accepted input field names for a class from /object_info."""
    spec = objinfo.get(class_type, {}).get("input", {})
    names = set()
    names.update(spec.get("required", {}).keys())
    names.update(spec.get("optional", {}).keys())
    return names


def is_patch_error(node_err):
    """True iff every error on this node is a missing-file on a PATCH_ value."""
    errs = node_err.get("errors", [])
    if not errs:
        return False
    for e in errs:
        received = ""
        extra = e.get("extra_info") or {}
        if isinstance(extra, dict):
            received = str(extra.get("received_value", ""))
        details = str(e.get("details", ""))
        blob = received + " " + details
        if "PATCH" not in blob:
            return False
    return True


def cancel(prompt_id):
    try:
        _post("/queue", {"delete": [prompt_id]})
    except Exception:
        pass
    try:
        _post("/interrupt", {})
    except Exception:
        pass


def check_template(path, objinfo, patchable):
    name = os.path.basename(path)
    notes = []

    # (a) json-parse
    try:
        graph = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        return "FAIL", ["json parse error: %s" % e]

    # (b) class_type exists
    for nid, node in graph.items():
        ct = node.get("class_type")
        if ct not in objinfo:
            return "FAIL", ["node %s: unknown class_type %r" % (nid, ct)]

    # (c) patchable titles + fields
    titles = {n.get("_meta", {}).get("title") for n in graph.values()}
    if patchable is None:
        notes.append("no patchable map in manifest")
    else:
        for title, ref in patchable.items():
            if "." not in ref:
                return "FAIL", ["patch %r -> %r is not 'id.field'" % (title, ref)]
            nid, field = ref.split(".", 1)
            if nid not in graph:
                return "FAIL", ["patch %r: node id %r not in graph" % (title, nid)]
            node = graph[nid]
            if field not in node.get("inputs", {}):
                return "FAIL", ["patch %r: field %r missing on node %s" % (title, field, nid)]
            if field not in valid_inputs(objinfo, node["class_type"]):
                return "FAIL", [
                    "patch %r: field %r not a real input of %s" % (title, field, node["class_type"])
                ]
            node_title = node.get("_meta", {}).get("title")
            if title != node_title:
                notes.append(
                    "alias: title %r patches node %s (titled %r).%s" % (title, nid, node_title, field)
                )
            elif title not in titles:
                notes.append("title %r not found as a node title" % title)

    # (d) POST to /prompt and read validation result
    cid = uuid.uuid4().hex
    status, resp = _post("/prompt", {"prompt": graph, "client_id": cid})
    if status == 200 and isinstance(resp, dict) and resp.get("prompt_id"):
        cancel(resp["prompt_id"])
        notes.append("clean queue (cancelled before generation)")
        return ("PASS-with-note" if notes else "PASS"), notes

    node_errors = resp.get("node_errors") if isinstance(resp, dict) else None
    if node_errors:
        benign, offending = [], []
        for nid, ne in node_errors.items():
            (benign if is_patch_error(ne) else offending).append((nid, ne))
        if offending:
            first_nid, first_ne = offending[0]
            msgs = [e.get("details") or e.get("message") for e in first_ne.get("errors", [])]
            return "FAIL", ["node %s (%s): %s" % (first_nid, first_ne.get("class_type"), "; ".join(map(str, msgs)))]
        placeholders = sorted({nid for nid, _ in benign})
        notes.append("expected PATCH-placeholder file(s) missing on node(s) %s" % ",".join(placeholders))
        return "PASS-with-note", notes

    # 400/other without node_errors we can classify
    err = resp.get("error") if isinstance(resp, dict) else resp
    return "FAIL", ["HTTP %s unclassified: %s" % (status, err)]


def main():
    try:
        objinfo = _get("/object_info")
    except Exception as e:
        print("FATAL: cannot reach ComfyUI at %s/object_info: %s" % (COMFY, e))
        return 2
    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    templates = manifest.get("templates", {})

    files = sorted(f for f in glob.glob(os.path.join(WF_DIR, "*.json"))
                   if os.path.basename(f) != "manifest.json")

    results = []
    for path in files:
        name = os.path.basename(path)
        patchable = templates.get(name, {}).get("patchable")
        status, notes = check_template(path, objinfo, patchable)
        results.append((name, status, notes))

    width = max(len(n) for n, _, _ in results)
    print("\nComfyUI workflow smoke-validation  (server %s)" % COMFY)
    print("=" * (width + 30))
    for name, status, notes in results:
        print("%-*s  %-14s  %s" % (width, name, status, "; ".join(notes) if notes else ""))
    print("=" * (width + 30))

    n_fail = sum(1 for _, s, _ in results if s == "FAIL")
    n_note = sum(1 for _, s, _ in results if s == "PASS-with-note")
    n_pass = sum(1 for _, s, _ in results if s == "PASS")
    print("PASS=%d  PASS-with-note=%d  FAIL=%d  (total %d)\n" % (n_pass, n_note, n_fail, len(results)))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
