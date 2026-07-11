#!/usr/bin/env python3
"""Audit every UI-format ComfyUI workflow for missing node classes and missing
model files.

Usage:
    ~/my-local-ai-stack/.venv/bin/python tools/check_workflows.py [--json out.json]

What it does:
  1. Recursively loads every *.json workflow under the ComfyUI UI workflows
     dir (~/my-local-ai-stack/ComfyUI/user/default/workflows/, including the
     aether-pipeline/ subfolder).
  2. For each workflow, walks every node and collects:
       - every node "type" (the ComfyUI class name)
       - every widget value (from "widgets_values") that is a string ending
         in one of MODEL_EXTS
  3. Queries the live ComfyUI instance once at COMFY_URL + /object_info to
     get the set of currently-registered node classes.
  4. Builds an index of every model file that exists locally (under
     ComfyUI/models/**) and on the SSD path(s) declared in
     extra_model_paths.yaml (plus the pipeline.toml [paths].loras dir), keyed
     by basename (case-insensitive) so a reference resolves regardless of
     which subfolder/model-type dir it actually lives in.
  5. Reports, per workflow: missing node classes and missing model filenames.

Output: a human-readable table on stdout, plus a machine-readable JSON
report (default: tools/check_workflows_report.json, override with --json).
Exit code is 0 if everything passes, 1 if anything is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MODEL_EXTS = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".onnx")

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PIPELINE_ROOT.parents[2]  # .../my-local-ai-stack
COMFY_ROOT = REPO_ROOT / "ComfyUI"
UI_WORKFLOWS_DIR = COMFY_ROOT / "user" / "default" / "workflows"
EXTRA_MODEL_PATHS_YAML = COMFY_ROOT / "extra_model_paths.yaml"
PIPELINE_TOML = PIPELINE_ROOT / "pipeline.toml"
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")


def find_workflow_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.json"))


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_object_info(url: str) -> dict:
    try:
        with urllib.request.urlopen(url + "/object_info", timeout=60) as r:
            return json.load(r)
    except (urllib.error.URLError, OSError) as e:
        print(f"ERROR: could not reach ComfyUI at {url}/object_info: {e}", file=sys.stderr)
        sys.exit(2)


def parse_extra_model_paths_yaml(path: Path) -> list[Path]:
    """Minimal parser for the simple extra_model_paths.yaml shape used here:
    a top-level key, then 'base_path: <path>' and a handful of
    '<model_type>: <relative>' lines. Returns a list of base_path Path roots
    (there can be more than one top-level section)."""
    bases: list[Path] = []
    if not path.exists():
        return bases
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("base_path:"):
            val = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            bases.append(Path(val))
    return bases


def parse_pipeline_toml_lora_path(path: Path) -> Path | None:
    if not path.exists():
        return None
    in_paths = False
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_paths = s == "[paths]"
            continue
        if in_paths and s.startswith("loras"):
            # loras = "/some/path"  # comment
            rhs = s.split("=", 1)[1].strip()
            rhs = rhs.split("#", 1)[0].strip()
            rhs = rhs.strip('"').strip("'")
            return Path(rhs)
    return None


def build_model_index(roots: list[Path]) -> dict[str, list[Path]]:
    """basename.lower() -> list of full paths that exist under any root."""
    index: dict[str, list[Path]] = {}
    for root in roots:
        if not root.exists():
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                for fn in filenames:
                    key = fn.lower()
                    index.setdefault(key, []).append(Path(dirpath) / fn)
        except OSError as e:
            print(f"WARNING: could not walk {root}: {e}", file=sys.stderr)
    return index


def iter_widget_strings(widgets_values):
    """widgets_values is usually a list, occasionally a dict (rare). Yield
    every string leaf value."""
    if isinstance(widgets_values, dict):
        vals = widgets_values.values()
    elif isinstance(widgets_values, list):
        vals = widgets_values
    else:
        return
    for v in vals:
        if isinstance(v, str):
            yield v
        elif isinstance(v, (list, dict)):
            yield from iter_widget_strings(v)


def collect_all_nodes(doc):
    """Return (nodes, subgraph_ids). Modern ComfyUI 'subgraph' saves nest a
    real sub-canvas of nodes under definitions.subgraphs[].nodes; the
    top-level node that *uses* a subgraph has a UUID for its "type" (matching
    one of these subgraph ids) instead of a real registered class name. We
    need to recurse into every subgraph's nodes so widget/model refs and
    class names inside them are still audited, and to know which top-level
    "type" values are subgraph-UUIDs (not missing node classes)."""
    all_nodes = list(doc.get("nodes", []) or [])
    subgraph_ids: set[str] = set()

    def walk_defs(container):
        defs = container.get("definitions") if isinstance(container, dict) else None
        subgraphs = defs.get("subgraphs") if isinstance(defs, dict) else None
        if not isinstance(subgraphs, list):
            return
        for sg in subgraphs:
            sgid = sg.get("id")
            if sgid:
                subgraph_ids.add(sgid)
            sg_nodes = sg.get("nodes", []) or []
            all_nodes.extend(sg_nodes)
            walk_defs(sg)  # nested subgraphs, if any

    walk_defs(doc)
    return all_nodes, subgraph_ids


def analyze_workflow(path: Path, object_info: dict, model_index: dict[str, list[Path]]):
    try:
        doc = load_json(path)
    except (json.JSONDecodeError, OSError) as e:
        return {"path": str(path), "load_error": str(e)}

    if not isinstance(doc.get("nodes"), list):
        return {"path": str(path), "load_error": "no top-level 'nodes' list (not a UI-format workflow)"}

    nodes, subgraph_ids = collect_all_nodes(doc)

    missing_nodes: set[str] = set()
    seen_types: set[str] = set()
    model_refs: dict[str, str] = {}  # filename -> node title/type it came from
    SKIP_TYPES = {"Note", "Reroute", "PrimitiveNode", "MarkdownNote"}

    for node in nodes:
        ntype = node.get("type")
        if not ntype:
            continue
        seen_types.add(ntype)
        is_subgraph_ref = ntype in subgraph_ids
        if ntype not in object_info and ntype not in SKIP_TYPES and not is_subgraph_ref:
            missing_nodes.add(ntype)
        title = node.get("title", ntype)
        for s in iter_widget_strings(node.get("widgets_values")):
            low = s.lower()
            if low.endswith(MODEL_EXTS):
                model_refs.setdefault(s, title)

    missing_models = []
    found_models = []
    for fname, title in model_refs.items():
        key = Path(fname).name.lower()  # in case a relative subpath was stored
        hits = model_index.get(key)
        if hits:
            found_models.append({"file": fname, "node": title, "resolved": str(hits[0])})
        else:
            missing_models.append({"file": fname, "node": title})

    return {
        "path": str(path),
        "node_types": sorted(seen_types),
        "missing_nodes": sorted(missing_nodes),
        "model_refs": sorted(model_refs.keys()),
        "missing_models": sorted(missing_models, key=lambda d: d["file"]),
        "found_models": sorted(found_models, key=lambda d: d["file"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(PIPELINE_ROOT / "tools" / "check_workflows_report.json"))
    ap.add_argument("--workflows-dir", default=str(UI_WORKFLOWS_DIR))
    args = ap.parse_args()

    object_info = fetch_object_info(COMFY_URL)

    local_models_root = COMFY_ROOT / "models"
    ssd_roots = parse_extra_model_paths_yaml(EXTRA_MODEL_PATHS_YAML)
    lora_root = parse_pipeline_toml_lora_path(PIPELINE_TOML)
    roots = [local_models_root] + ssd_roots
    if lora_root:
        roots.append(lora_root)
    model_index = build_model_index(roots)

    wf_dir = Path(args.workflows_dir)
    files = find_workflow_files(wf_dir)

    results = []
    for f in files:
        results.append(analyze_workflow(f, object_info, model_index))

    # --- human table ---
    total_missing_nodes = 0
    total_missing_models = 0
    print(f"Scanned {len(files)} workflow file(s) under {wf_dir}")
    print(f"Model search roots: {[str(r) for r in roots]}")
    print(f"object_info: {len(object_info)} node classes registered at {COMFY_URL}")
    print()
    header = f"{'WORKFLOW':60} {'MISSING NODES':30} {'MISSING MODELS':40}"
    print(header)
    print("-" * len(header))
    for r in results:
        name = str(Path(r["path"]).relative_to(wf_dir))
        if "load_error" in r:
            print(f"{name:60} LOAD ERROR: {r['load_error']}")
            continue
        mn = r["missing_nodes"]
        mm = [m["file"] for m in r["missing_models"]]
        total_missing_nodes += len(mn)
        total_missing_models += len(mm)
        mn_s = ", ".join(mn) if mn else "-"
        mm_s = ", ".join(mm) if mm else "-"
        status = "OK" if not mn and not mm else "FAIL"
        print(f"{name:60} {mn_s:30} {mm_s:40} [{status}]")
    print()
    print(f"TOTAL missing node refs: {total_missing_nodes}   TOTAL missing model refs: {total_missing_models}")

    report = {
        "comfy_url": COMFY_URL,
        "workflows_dir": str(wf_dir),
        "model_search_roots": [str(r) for r in roots],
        "num_object_info_classes": len(object_info),
        "results": results,
        "totals": {
            "missing_node_refs": total_missing_nodes,
            "missing_model_refs": total_missing_models,
        },
    }
    Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nJSON report written to {args.json}")

    sys.exit(0 if total_missing_nodes == 0 and total_missing_models == 0 else 1)


if __name__ == "__main__":
    main()
