"""
app.py  --  The unified dashboard for the whole stack.

Started via start.bat, serves http://localhost:8750 with five pages:
  /             Dashboard      overview: status strip, quick task, activity feed
  /tasks        Tasks          full task composer + history (Project 1)
  /automation   Automation     trigger digests on demand (Project 3)
  /reviews      Knowledge      browse what the AI wrote into your vault (Project 2)
  /integrations Integrations   live status + links for every connected app
                                (Ollama, LM Studio, n8n, AnythingLLM, ComfyUI, Agent Atlas)

No database, no accounts, no cloud. Everything is your local Ollama model.
"""

from __future__ import annotations
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

import bleach
import markdown as md_lib
import requests
from flask import Flask, abort, flash, redirect, render_template, request, url_for

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process import process_task, save_result  # noqa: E402
from shared.lib import llm  # noqa: E402
from shared.lib.config import load_config  # noqa: E402
from shared.lib.notes import generated_dir  # noqa: E402

CFG = load_config()
ROOT = Path(CFG["root"])
app = Flask(__name__)
app.secret_key = os.urandom(24)

JOBS = {
    "nightly": ("project2-second-brain/run_nightly.py", "Nightly Review", "Extract tasks/decisions/insights, write a Daily Review (Project 2)."),
    "research": ("project3-automation/research.py", "Research Digest", "Read feeds.txt, summarise new articles into the vault (Project 3)."),
    "repos": ("project3-automation/repo_digest.py", "Repo Digest", "Read-only git log + TODO scan for repos in config.json (Project 3)."),
}
JOB_COLORS = {"nightly": "#A78BFA", "research": "#7DD3FC", "repos": "#5EE2B5"}

ALLOWED_TAGS = [
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "em",
    "code", "pre", "blockquote", "a", "hr", "br", "table", "thead", "tbody",
    "tr", "th", "td", "span", "del",
]
ALLOWED_ATTRS = {"a": ["href", "title"], "*": ["class"]}


def render_markdown_safe(text: str) -> str:
    html = md_lib.markdown(text, extensions=["extra", "sane_lists", "nl2br"])
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)


def _human_when(dt: datetime) -> str:
    delta = datetime.now() - dt
    secs = delta.total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return dt.strftime("%Y-%m-%d %H:%M")


def _last_run(namespace: str) -> str:
    fp = generated_dir() / ".state" / f"{namespace}.json"
    if fp.exists():
        return _human_when(datetime.fromtimestamp(fp.stat().st_mtime))
    return "never"


def _last_run_status(namespace: str) -> str:
    """ok = ran in the last 24h, warn = ran before that, bad = never run."""
    fp = generated_dir() / ".state" / f"{namespace}.json"
    if not fp.exists():
        return "bad"
    age = datetime.now().timestamp() - fp.stat().st_mtime
    return "ok" if age < 86400 else "warn"


_STAMP_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}-")


def _recent_tasks(limit: int = 8) -> list[dict]:
    outbox = Path(CFG["task_outbox"])
    if not outbox.exists():
        return []
    files = sorted(outbox.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for f in files:
        # filename shape: <stamp>-<category>-<title>.md, where <stamp> is
        # notes.now_stamp() ("YYYY-MM-DD_HHMMSS") -- it has its own dashes,
        # so strip it as a fixed prefix instead of splitting on "-" blindly.
        rest = _STAMP_PREFIX_RE.sub("", f.stem)
        category, _, title = rest.partition("-")
        if not title:
            category, title = "task", category
        out.append({
            "name": f.name,
            "title": title.replace("-", " "),
            "category": category,
            "when": _human_when(datetime.fromtimestamp(f.stat().st_mtime)),
        })
    return out


def _activity_feed(limit: int = 10) -> list[dict]:
    """Real events pulled from disk: recent tasks + nightly review runs."""
    events = []
    for t in _recent_tasks(limit=limit):
        events.append({"badge": "task", "desc": t["title"], "when": t["when"],
                        "ts": (Path(CFG["task_outbox"]) / t["name"]).stat().st_mtime})
    logs_dir = generated_dir() / "logs"
    if logs_dir.exists():
        for f in sorted(logs_dir.glob("nightly-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            events.append({"badge": "review", "desc": "Nightly review completed",
                            "when": _human_when(datetime.fromtimestamp(f.stat().st_mtime)),
                            "ts": f.stat().st_mtime})
    events.sort(key=lambda e: e["ts"], reverse=True)
    return events[:limit]


# ---------------------------------------------------------------------------
# Integrations — every app this stack can talk to, with a live status check
# ---------------------------------------------------------------------------
def _get_json(url: str, timeout: float = 2.5) -> dict | None:
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code < 500:
            return r.json()
    except Exception:  # noqa: BLE001
        pass
    return None


def _n8n_api_key() -> str | None:
    """Read N8N_API_KEY out of foundation/.env, if it's been added there."""
    env_file = ROOT / "foundation" / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("N8N_API_KEY="):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


def _integrations() -> list[dict]:
    out = []

    ollama_up = llm.ollama_up()
    models = llm.installed_models() if ollama_up else []
    out.append({
        "key": "ollama", "label": "Ollama", "color": "#7DD3FC", "up": ollama_up,
        "detail": f"{len(models)} models pulled" if ollama_up else "not reachable",
        "link": "http://localhost:11434", "has_ui": False,
        "role": "Primary local model engine — everything routes through this.",
    })

    lmstudio = _get_json("http://127.0.0.1:1234/v1/models")
    lm_count = len(lmstudio.get("data", [])) if lmstudio else 0
    out.append({
        "key": "lmstudio", "label": "LM Studio", "color": "#F5B544", "up": lmstudio is not None,
        "detail": f"{lm_count} models loaded" if lmstudio else "not running",
        "link": "http://127.0.0.1:1234", "has_ui": False,
        "role": "Second local model server (used by Agent Atlas). Manage models from the LM Studio desktop app, not a browser.",
    })

    n8n_up = False
    try:
        n8n_up = requests.get("http://localhost:5678/healthz", timeout=2).status_code < 500
    except Exception:  # noqa: BLE001
        pass
    n8n_detail = "not running"
    n8n_key = _n8n_api_key()
    if n8n_up and n8n_key:
        try:
            r = requests.get(
                "http://localhost:5678/api/v1/workflows",
                headers={"X-N8N-API-KEY": n8n_key}, timeout=3,
            )
            if r.status_code == 200:
                wfs = r.json().get("data", [])
                active = sum(1 for w in wfs if w.get("active"))
                n8n_detail = f"{len(wfs)} workflows ({active} active)"
            else:
                n8n_detail = "API key rejected"
        except Exception:  # noqa: BLE001
            n8n_detail = "online, API unreachable"
    elif n8n_up:
        n8n_detail = "online (no API key set)"
    out.append({
        "key": "n8n", "label": "n8n", "color": "#F472B6", "up": n8n_up,
        "detail": n8n_detail, "has_ui": True,
        "link": "http://localhost:5678", "role": "Build/run automations (email triage, scheduled workflows).",
    })

    allm = _get_json("http://127.0.0.1:3001/api/ping")
    out.append({
        "key": "anythingllm", "label": "AnythingLLM", "color": "#A78BFA", "up": bool(allm and allm.get("online")),
        "detail": "chat with your vault" if allm else "not running", "has_ui": True,
        "link": "http://127.0.0.1:3001", "role": "RAG chat over your Obsidian notes.",
    })

    comfy = _get_json("http://127.0.0.1:8188/system_stats")
    comfy_detail = "not running"
    if comfy:
        gpu = (comfy.get("devices") or [{}])[0]
        comfy_detail = gpu.get("name", "image/video generation")
    out.append({
        "key": "comfyui", "label": "ComfyUI", "color": "#5EE2B5", "up": comfy is not None,
        "detail": comfy_detail, "link": "http://127.0.0.1:8188", "has_ui": True,
        "role": "Local image/video generation (node graph).",
    })

    atlas = _get_json("http://127.0.0.1:8000/api/health")
    atlas_detail = "not running"
    if atlas:
        atlas_detail = f"{atlas.get('agents_loaded', '?')} agents · {atlas.get('models_loaded', '?')} models"
    out.append({
        "key": "agent_atlas", "label": "Agent Atlas", "color": "#8B5CF6", "up": atlas is not None,
        "detail": atlas_detail, "link": "http://127.0.0.1:8000", "has_ui": True,
        "role": "Multi-agent system: persistent memory, background jobs, email, agent factory.",
    })

    opencode_path = shutil.which("opencode")
    out.append({
        "key": "opencode", "label": "OpenCode", "color": "#F26D6D", "up": opencode_path is not None,
        "detail": "qwen2.5-coder:7b (local)" if opencode_path else "not installed",
        "link": None, "role": "Terminal coding agent — reads repos, edits files, runs tests.",
    })

    return out


# ---------------------------------------------------------------------------
# Dashboard (home)
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def dashboard():
    integrations = _integrations()
    jobs = [
        {
            "key": k, "label": label, "description": desc,
            "last_run": _last_run(_job_namespace(k)),
            "status": _last_run_status(_job_namespace(k)),
            "color": JOB_COLORS[k],
        }
        for k, (_, label, desc) in JOBS.items()
    ]
    return render_template(
        "dashboard.html", active="dashboard",
        integrations=integrations,
        connected_count=sum(1 for i in integrations if i["up"]),
        total_count=len(integrations),
        jobs=jobs, feed=_activity_feed(limit=8),
        up=llm.ollama_up(),
    )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
# Tasks run an LLM through up to 4 passes, which can take a while on a local
# model. Running that inline in the request thread meant slow/failed runs
# looked like "nothing happened" with no feedback. Instead we run each task
# in a background thread and let the page poll for status -- same shape as
# Agent Atlas's job queue, just in-memory (no DB, matches this app's
# no-database design).
_TASK_JOBS: dict[str, dict] = {}
_TASK_JOBS_LOCK = threading.Lock()


def _run_task_job(job_id: str, task: str, passes: int) -> None:
    with _TASK_JOBS_LOCK:
        _TASK_JOBS[job_id]["status"] = "running"
    try:
        result = process_task(task, passes=passes)
    except Exception as exc:  # noqa: BLE001 - keep the worker thread alive
        traceback.print_exc()
        result = {"category": "error", "title": "error", "output": f"Unexpected error: {exc}"}

    saved = None
    save_error = None
    if result["category"] != "error" and task.strip():
        try:
            saved = str(save_result(task, result))
        except Exception as exc:  # noqa: BLE001
            save_error = str(exc)
            print(f"[tasks] failed to save result for job {job_id}: {exc}", file=sys.stderr)
            traceback.print_exc()

    with _TASK_JOBS_LOCK:
        _TASK_JOBS[job_id].update({
            "status": "done", "result": result, "saved": saved,
            "save_error": save_error, "finished_at": time.time(),
        })


@app.route("/tasks", methods=["GET"])
def tasks():
    return render_template(
        "tasks.html", active="tasks", up=llm.ollama_up(),
        result=None, task="", passes=3, saved=None, recent=_recent_tasks(),
    )


@app.route("/tasks/run", methods=["POST"])
def run_task():
    task = request.form.get("task", "")
    try:
        passes = int(request.form.get("passes", "3"))
    except ValueError:
        passes = 3

    if not task.strip():
        return {"error": "Task can't be empty."}, 400

    job_id = uuid.uuid4().hex[:12]
    with _TASK_JOBS_LOCK:
        _TASK_JOBS[job_id] = {"status": "queued", "task": task, "passes": passes, "started_at": time.time()}
    threading.Thread(target=_run_task_job, args=(job_id, task, passes), daemon=True).start()
    return {"job_id": job_id}


@app.route("/tasks/status/<job_id>")
def task_status(job_id: str):
    with _TASK_JOBS_LOCK:
        job = _TASK_JOBS.get(job_id)
    if job is None:
        abort(404)
    payload = {"status": job["status"], "elapsed": round(time.time() - job["started_at"], 1)}
    if job["status"] == "done":
        payload["result"] = job["result"]
        payload["result_html"] = render_markdown_safe(job["result"]["output"])
        payload["saved"] = job.get("saved")
        payload["save_error"] = job.get("save_error")
    return payload


@app.route("/tasks/recent.json")
def tasks_recent_json():
    return {"recent": _recent_tasks()}


@app.route("/outbox/view")
def view_outbox_file():
    name = request.args.get("name", "")
    if "/" in name or "\\" in name or ".." in name:
        abort(404)
    target = Path(CFG["task_outbox"]) / name
    if not target.is_file():
        abort(404)
    text = target.read_text(encoding="utf-8", errors="replace")
    return render_template(
        "file_view.html", active="tasks", title=name,
        subtitle="Saved task result", content_html=render_markdown_safe(text),
        back_url=url_for("tasks"),
    )


# ---------------------------------------------------------------------------
# Knowledge (vault browser)
# ---------------------------------------------------------------------------
@app.route("/reviews")
def reviews():
    root = generated_dir()
    groups: dict[str, list[dict]] = {}
    for p in sorted(root.rglob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        rel = p.relative_to(root)
        if ".state" in rel.parts:
            continue
        group = rel.parts[0] if len(rel.parts) > 1 else "General"
        groups.setdefault(group, []).append({
            "rel": str(rel).replace("\\", "/"),
            "name": p.name,
            "when": _human_when(datetime.fromtimestamp(p.stat().st_mtime)),
        })
    return render_template("reviews.html", active="reviews", groups=groups)


@app.route("/reviews/view")
def view_review_file():
    rel = request.args.get("rel", "")
    root = generated_dir().resolve()
    target = (root / rel).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        abort(404)
    text = target.read_text(encoding="utf-8", errors="replace")
    return render_template(
        "file_view.html", active="reviews", title=target.name,
        subtitle=str(target.relative_to(root)), content_html=render_markdown_safe(text),
        back_url=url_for("reviews"),
    )


# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------
def _job_namespace(key: str) -> str:
    return {"nightly": "second_brain", "research": "research", "repos": "repos"}[key]


@app.route("/automation")
def automation():
    jobs = [
        {
            "key": k, "label": label, "description": desc,
            "last_run": _last_run(_job_namespace(k)),
            "status": _last_run_status(_job_namespace(k)),
            "color": JOB_COLORS[k],
        }
        for k, (_, label, desc) in JOBS.items()
    ]
    return render_template("automation.html", active="automation", jobs=jobs)


@app.route("/automation/run/<job>", methods=["POST"])
def run_automation(job: str):
    if job not in JOBS:
        abort(404)
    script_rel, label, _ = JOBS[job]
    script_path = ROOT / script_rel
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, timeout=1800, cwd=str(script_path.parent),
        )
        if proc.returncode == 0:
            flash(f"{label} finished.", "ok")
        else:
            tail = (proc.stderr or proc.stdout or "").strip()[-500:]
            flash(f"{label} exited with an error: {tail}", "error")
    except subprocess.TimeoutExpired:
        flash(f"{label} timed out after 30 minutes.", "error")
    except Exception as exc:  # noqa: BLE001
        flash(f"{label} failed to start: {exc}", "error")
    return redirect(url_for("automation"))


# ---------------------------------------------------------------------------
# Integrations page
# ---------------------------------------------------------------------------
@app.route("/integrations")
def integrations_page():
    items = _integrations()
    return render_template(
        "integrations.html", active="integrations", items=items,
        connected_count=sum(1 for i in items if i["up"]), total_count=len(items),
        n8n_configured=_n8n_api_key() is not None,
    )


@app.route("/status")
def status_redirect():
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    port = int(CFG.get("flask_port", 8750))
    print(f"\n  Local AI Stack dashboard -> http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
