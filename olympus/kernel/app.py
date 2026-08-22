"""Olympus Kernel — central hub for the Local AI Stack.

FastAPI service on :4600. Connects Ollama, Voice Studio, ComfyUI, and the
Anime Pipeline engine. Serves the Olympus dashboard UI.

Run:
    .venv/bin/uvicorn kernel.app:app --host 0.0.0.0 --port 4600
"""

from __future__ import annotations

import asyncio
import hmac
import io
import json
import logging
import secrets
import subprocess
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

KERNEL_DIR = Path(__file__).resolve().parent
STACK_ROOT = KERNEL_DIR.parent.parent
WEB_DIR = STACK_ROOT / "olympus" / "web"

import sys
import time

_CONFIG_PATH = STACK_ROOT / "stack.toml"
if str(STACK_ROOT) not in sys.path:
    sys.path.insert(0, str(STACK_ROOT))
from stack.config import StackConfig, load_config, cfg

logger = logging.getLogger("olympus.kernel")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    _h = logging.StreamHandler()
    _h.setFormatter(_fmt)
    logger.addHandler(_h)
    try:
        _log_dir = STACK_ROOT / "logs"
        _log_dir.mkdir(exist_ok=True)
        _fh = RotatingFileHandler(
            _log_dir / "olympus.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        _fh.setFormatter(_fmt)
        logger.addHandler(_fh)
    except Exception:
        pass

_CSRF_SECRET = secrets.token_urlsafe(32)

app = FastAPI(title="Olympus", version="3.0.0")

_MAX_BODY_BYTES = 1_000_000  # 1MB hard limit for all request bodies

@app.middleware("http")
async def csrf_protect(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        cookie_token = request.cookies.get("olympus_csrf", "")
        header_token = request.headers.get("x-csrf-token", "")
        if cookie_token and not hmac.compare_digest(cookie_token, header_token):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing or invalid", "type": "CSRF"},
            )
    response = await call_next(request)
    response.set_cookie(
        "olympus_csrf",
        _CSRF_SECRET,
        httponly=False,
        samesite="lax",
        secure=False,
        path="/",
    )
    return response

@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    try:
        size = int(cl, 10) if cl is not None else 0
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid Content-Length", "type": "BadRequest"}
        )
    if size > _MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body too large", "type": "PayloadTooLarge"}
        )
    return await call_next(request)

@app.middleware("http")
async def request_timeout(request: Request, call_next):
    if request.url.path == "/api/voice/tts":
        return await call_next(request)  # TTS has its own 300s upstream timeout
    try:
        return await asyncio.wait_for(call_next(request), timeout=30.0)
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"detail": "Request timed out", "type": "Timeout"},
        )


# ── exception handlers ─────────────────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "type": "HTTPException"}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__}
    )


# ── request models ─────────────────────────────────────────────────────────

class TaskIn(BaseModel):
    text: str = Field(min_length=1)
    agent: str | None = None


class AgentIn(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: str = "general"
    model: str = "worker"
    keywords: str = ""
    description: str = ""
    system_prompt: str = Field(min_length=1)


class GoalIn(BaseModel):
    goal: str = Field(min_length=1)


class TTSIn(BaseModel):
    text: str = Field(min_length=1)
    voice: str = "af_heart"
    speed: float = 1.0


# ── GPU ────────────────────────────────────────────────────────────────────

def gpu_status() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        used, total = (int(x) for x in out.stdout.strip().split(","))
        return {"available": True, "vram_used_mb": used, "vram_total_mb": total}
    except Exception:
        return {"available": False}


# ── tasks / agents ─────────────────────────────────────────────────────────

import threading

_tasks: dict[int, dict] = {}
_task_counter: int = 0
_task_lock = threading.Lock()
_active_tasks: set[int] = set()  # Track currently running tasks
_MAX_CONCURRENT_TASKS = 3  # Limit concurrent tasks to prevent resource exhaustion


def _evict_old_tasks():
    """Remove tasks older than 24 hours to prevent unbounded memory growth."""
    while True:
        try:
            time.sleep(300)  # Check every 5 minutes
            cutoff = time.time() - (24 * 3600)  # 24 hours ago
            with _task_lock:
                to_remove = [
                    tid for tid, task in _tasks.items()
                    if task.get("created", 0) < cutoff
                    and task.get("status") in ("done", "failed", "queued")
                ]
                for tid in to_remove:
                    del _tasks[tid]
                    _active_tasks.discard(tid)
        except Exception:
            pass  # Don't crash the eviction thread

_eviction_thread = threading.Thread(target=_evict_old_tasks, daemon=True, name="task-evictor")
_eviction_thread.start()


def _resolve_model(role: str) -> str:
    """Map an agent model role name to the actual Ollama model."""
    try:
        return getattr(cfg.ollama.agents, role)
    except AttributeError:
        return cfg.ollama.models.default


_AGENTS = [
    {"id": "jarvis", "name": "JARVIS", "domain": "general", "model": "triage",
     "description": "Primary assistant — answers questions, routes work.",
     "resolved_model": _resolve_model("triage")},
    {"id": "archivist", "name": "ARCHIVIST", "domain": "knowledge", "model": "triage",
     "description": "Reads the vault, indexes notes, searches knowledge.",
     "resolved_model": _resolve_model("triage")},
    {"id": "plutus", "name": "PLUTUS", "domain": "commerce", "model": "triage",
     "description": "Commerce tasks — listings, invoices, pricing, budgets.",
     "resolved_model": _resolve_model("triage")},
    {"id": "conductor", "name": "CONDUCTOR", "domain": "orchestration", "model": "planner",
     "description": "Orchestrates multi-step work, plans goals, routes sub-tasks.",
     "resolved_model": _resolve_model("planner")},
]


def _model_for_agent(agent_name: str | None) -> str:
    agent = next((a for a in _AGENTS if a["name"].lower() == (agent_name or "jarvis").lower()), _AGENTS[0])
    return _resolve_model(agent["model"])


def _call_ollama(model: str, prompt: str) -> tuple[str, str | None]:
    """Calls Ollama. Returns (result_text, error_message). One is always None."""
    payload = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": 0.7, "num_predict": 300},
    }).encode()
    req = urllib.request.Request(
        cfg.ollama.url + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.ollama.timeout_seconds) as resp:
            return json.loads(resp.read()).get("response", ""), None
    except Exception as e:
        return "", str(e)


def _run_task(task_id: int, text: str, agent_name: str | None):
    model_name = _model_for_agent(agent_name)
    logger.info("Task %d starting: agent=%s model=%s", task_id, agent_name or "jarvis", model_name)

    # Mark task as active
    with _task_lock:
        _tasks[task_id]["status"] = "running"
        _active_tasks.add(task_id)

    try:
        result, error = _call_ollama(model_name, text)

        with _task_lock:
            _tasks[task_id]["status"] = "failed" if error and not result else "done"
            _tasks[task_id]["result"] = result or (f"[Error: {error}]" if error else "")
            if error:
                _tasks[task_id]["error"] = error
                logger.error("Task %d failed: %s", task_id, error)
            else:
                logger.info("Task %d completed successfully", task_id)
    finally:
        # Always remove from active tasks when done
        with _task_lock:
            _active_tasks.discard(task_id)


# ── health ─────────────────────────────────────────────────────────────────

def _check(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except Exception:
        return False


# Caching for health checks to reduce external API calls
_health_cache = {"data": None, "timestamp": 0}
_HEALTH_CACHE_TTL = 10  # seconds
_services_cache = {"data": None, "timestamp": 0}
_SERVICES_CACHE_TTL = 15  # seconds


@app.get("/api/health")
def health():
    # Check if cache is still valid
    now = time.time()
    if _health_cache["data"] and (now - _health_cache["timestamp"]) < _HEALTH_CACHE_TTL:
        logger.debug("Health cache hit")
        return _health_cache["data"]
    
    logger.debug("Health check: checking services")
    result = {
        "status": "ok",
        "agents": len(_AGENTS),
        "ollama": _check(cfg.ollama.url + "/api/version"),
        "comfyui": _check(cfg.comfyui.url + "/system_stats"),
        "voice": _check(cfg.voice.url + "/api/health"),
        "gpu": gpu_status(),
    }
    
    # Update cache
    _health_cache["data"] = result
    _health_cache["timestamp"] = now
    return result


# ── services ───────────────────────────────────────────────────────────────

SERVICES = {
    "ollama": {"port": cfg.ollama.port, "url": cfg.ollama.url + "/api/version"},
    "comfyui": {"port": cfg.comfyui.port, "url": cfg.comfyui.url + "/system_stats"},
    "voice": {"port": cfg.voice.port, "url": cfg.voice.url + "/api/health"},
    "open-webui": {"port": cfg.webui.port, "url": cfg.webui.url},
}


@app.get("/api/services")
def list_services():
    # Check if cache is still valid
    now = time.time()
    if _services_cache["data"] and (now - _services_cache["timestamp"]) < _SERVICES_CACHE_TTL:
        return _services_cache["data"]
    
    result = []
    for name, svc in SERVICES.items():
        running = False
        try:
            urllib.request.urlopen(svc["url"], timeout=3)
            running = True
        except Exception:
            pass
        result.append({"name": name, "port": svc["port"], "running": running})
    
    # Update cache
    _services_cache["data"] = result
    _services_cache["timestamp"] = now
    return result


@app.post("/api/services/{name}/start")
def start_service(name: str):
    if name not in SERVICES:
        raise HTTPException(404, f"unknown service: {name}")
    unit_map = {
        "comfyui": "comfyui-server.service",
        "voice": "voice-studio.service",
        "open-webui": "open-webui.service",
    }
    if name in unit_map:
        try:
            logger.info("Starting service: %s (%s)", name, unit_map[name])
            subprocess.run(
                ["systemctl", "--user", "start", unit_map[name]],
                capture_output=True, timeout=30,
            )
            logger.info("Service started: %s", name)
            return {"name": name, "started": True}
        except Exception as e:
            logger.error("Failed to start service %s: %s", name, e)
            raise HTTPException(503, str(e))
    logger.warning("No systemd unit for service: %s", name)
    raise HTTPException(400, f"{name} has no systemd unit — started externally")


# ── agent API ──────────────────────────────────────────────────────────────

@app.get("/api/agents")
def list_agents():
    return _AGENTS


@app.post("/api/agents/reload")
def reload_agents():
    return {"reloaded": len(_AGENTS)}


# ── task API ───────────────────────────────────────────────────────────────

@app.post("/api/tasks", status_code=201)
def submit_task(body: TaskIn):
    global _task_counter
    with _task_lock:
        # Check if we've reached max concurrent tasks
        if len(_active_tasks) >= _MAX_CONCURRENT_TASKS:
            logger.warning("Task rejected: max concurrent tasks reached (%d)", _MAX_CONCURRENT_TASKS)
            raise HTTPException(429, "Too many concurrent tasks. Please try again later.")
        
        _task_counter += 1
        tid = _task_counter
        _tasks[tid] = {
            "id": tid, "text": body.text, "agent": body.agent or "jarvis",
            "status": "queued", "result": None, "error": None, "created": time.time(),
        }
    logger.info("Task submitted: id=%d agent=%s text=%s", tid, body.agent or "jarvis", body.text[:50])
    threading.Thread(target=_run_task, args=(tid, body.text, body.agent), daemon=True).start()
    return _tasks[tid]


@app.get("/api/tasks")
def list_tasks():
    return sorted(_tasks.values(), key=lambda t: t["id"], reverse=True)


@app.get("/api/tasks/{tid}")
def get_task(tid: int):
    task = _tasks.get(tid)
    if task is None:
        raise HTTPException(404, f"no task {tid}")
    return task


@app.post("/api/tasks/{tid}/rerun", status_code=201)
def rerun_task(tid: int):
    task = _tasks.get(tid)
    if task is None:
        raise HTTPException(404, f"no task {tid}")
    return submit_task(TaskIn(text=task["text"], agent=task["agent"]))


@app.post("/api/tasks/{tid}/retry")
def retry_task(tid: int):
    task = _tasks.get(tid)
    if task is None:
        raise HTTPException(404, f"no task {tid}")
    if task["status"] != "failed":
        raise HTTPException(409, "only failed tasks can be retried")
    with _task_lock:
        task["status"] = "queued"
        task["result"] = None
        task["error"] = None
    threading.Thread(target=_run_task, args=(tid, task["text"], task["agent"]), daemon=True).start()
    return task


@app.post("/api/orchestrate", status_code=201)
def orchestrate(body: GoalIn):
    plans, _ = _call_ollama(cfg.ollama.agents.planner, f"Plan this goal as numbered steps:\n{body.goal}")
    # Parse plan into individual tasks and submit them
    steps = [s.strip() for s in plans.split("\n") if s.strip() and s.strip()[0].isdigit()]
    created = []
    for step in steps:
        text = step.lstrip("0123456789. )-")
        if len(text) > 10:
            created.append(submit_task(TaskIn(text=text, agent="conductor")))
    return {"goal": body.goal, "plan": plans, "tasks_created": len(created), "tasks": created}


# ── TTS proxy ──────────────────────────────────────────────────────────────

@app.get("/api/voice/voices")
def voice_voices():
    try:
        with urllib.request.urlopen(cfg.voice.url + "/api/voices", timeout=5) as r:
            return json.load(r)
    except Exception:
        raise HTTPException(503, "Voice Studio offline")


@app.post("/api/voice/tts")
def voice_tts(body: TTSIn) -> Response:
    payload = json.dumps(body.model_dump()).encode()
    req = urllib.request.Request(
        cfg.voice.url + "/api/tts",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return Response(content=r.read(), media_type="audio/wav")
    except Exception:
        raise HTTPException(503, "Voice Studio offline")


# ── pipeline bridge ────────────────────────────────────────────────────────

PIPELINE_ENGINE = STACK_ROOT / "olympus" / "engines" / "pipeline"
if str(PIPELINE_ENGINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ENGINE))

from pipeline.blueprint import Blueprint, STAGE_ORDER
from pipeline.scores import Scores

_locks: dict[tuple, threading.Thread] = {}
_lock_map = threading.Lock()


@app.get("/api/pipeline/projects")
def pipeline_projects():
    projects_dir = PIPELINE_ENGINE / "projects"
    if not projects_dir.exists():
        return []
    results = []
    for d in sorted(projects_dir.iterdir()):
        bp_path = d / "blueprint.json"
        if not bp_path.exists():
            continue
        try:
            bp = Blueprint.load(d)
            results.append({"slug": bp.slug, "story_id": bp.story_id, "fps": bp.fps, "created": bp.created})
        except Exception:
            continue
    results.sort(key=lambda p: p.get("created", ""), reverse=True)
    return results


class ProjectIn(BaseModel):
    slug: str
    brief_text: str | None = None
    script_text: str | None = None
    fps: int = 24
    mode: str = "0b"  # stage0 intake mode: 0b | 0a | 0i


@app.post("/api/pipeline/projects", status_code=201)
def pipeline_create(body: ProjectIn):
    import run as prun
    import tempfile

    project_dir = PIPELINE_ENGINE / "projects" / body.slug
    if project_dir.exists():
        raise HTTPException(409, f"project {body.slug!r} exists")

    seed = body.brief_text or body.script_text or ""
    with tempfile.TemporaryDirectory() as tmp:
        seed_path = Path(tmp) / "seed.txt"
        seed_path.write_text(seed)
        try:
            prun.new_project(
                body.slug, seed_path, fps=body.fps, projects_dir=project_dir.parent,
                mode=body.mode,
            )
        except Exception as e:
            raise HTTPException(400, str(e))

    # Persist intake inputs so stage0 runs (and RUN-ALL) work without re-passing.
    (project_dir / "input").mkdir(parents=True, exist_ok=True)
    if body.mode == "0b" and body.brief_text:
        brief_md = body.brief_text
        if "word_target:" not in brief_md:
            brief_md = "---\nword_target: 800\n---\n\n" + brief_md
        (project_dir / "input" / "brief.md").write_text(brief_md, encoding="utf-8")
    elif body.mode == "0a" and body.script_text:
        (project_dir / "input" / "source.txt").write_text(body.script_text, encoding="utf-8")

    bp = Blueprint.load(project_dir)
    return {"slug": bp.slug, "story_id": bp.story_id, "fps": bp.fps, "created": bp.created, "mode": bp.mode}


@app.get("/api/pipeline/{slug}/status")
def pipeline_status(slug: str):
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if not (project_dir / "blueprint.json").exists():
        raise HTTPException(404, f"no project: {slug!r}")

    bp = Blueprint.load(project_dir)
    stages = {}
    for stage in STAGE_ORDER:
        st = bp.stages.get(stage)
        status = st.status if st else "pending"
        info = {"status": status}
        if status == "done":
            try:
                with Scores(project_dir / "scores.sqlite") as s:
                    info["metrics"] = s.metrics_for(stage)
            except Exception:
                pass
        stages[stage] = info

    return {"slug": bp.slug, "story_id": bp.story_id, "fps": bp.fps, "mode": bp.mode, "stages": stages}


class StageRunIn(BaseModel):
    source: str | None = None      # stage0 mode 0a: path to source text (server-side)
    source_text: str | None = None  # stage0 mode 0a: inline source text (persisted to input/source.txt)
    panels: str | None = None      # stage0 mode 0i: zip/folder of panels (server-side)
    word_target: int | None = None  # stage0 mode 0a: word budget
    brief: str | None = None       # stage0 mode 0b: inline brief text (persisted to input/brief.md)
    force: bool = False            # force rerun even if stage is marked done


@app.post("/api/pipeline/{slug}/run/{stage}")
def pipeline_run_stage(slug: str, stage: str, body: StageRunIn | None = None):
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if not (project_dir / "blueprint.json").exists():
        raise HTTPException(404, f"no project: {slug!r}")
    if stage not in STAGE_ORDER:
        raise HTTPException(404, f"unknown stage: {stage!r}")

    key = (slug, stage)
    with _lock_map:
        t = _locks.get(key)
        if t and t.is_alive():
            raise HTTPException(409, f"{slug}/{stage} already running")

        import run as prun
        body = body or StageRunIn()

        def worker():
            ok = False
            err_msg = ""
            # If force, clear the scorecard entry so the gate allows rerun
            if body.force:
                try:
                    from pipeline.scores import Scores as _Scores
                    with _Scores(project_dir / "scores.sqlite") as _sc:
                        _sc.clear_stage(stage)
                except Exception:
                    pass
            # Flip the stage to "running" up-front so the dashboard reflects
            # that a job is in flight, not just after it finishes.
            try:
                bp = Blueprint.load(project_dir)
                entry = bp.stages.get(stage)
                if entry is not None:
                    entry.status = "running"
                    bp.write(project_dir)
            except Exception:
                pass
            try:
                brief_path = None
                source_path = body.source
                if body.brief:
                    (project_dir / "input").mkdir(parents=True, exist_ok=True)
                    brief_md = body.brief
                    if "word_target:" not in brief_md:
                        brief_md = "---\nword_target: 800\n---\n\n" + brief_md
                    (project_dir / "input" / "brief.md").write_text(brief_md, encoding="utf-8")
                    brief_path = project_dir / "input" / "brief.md"
                if body.source_text:
                    (project_dir / "input").mkdir(parents=True, exist_ok=True)
                    (project_dir / "input" / "source.txt").write_text(body.source_text, encoding="utf-8")
                    source_path = project_dir / "input" / "source.txt"
                prun.run_stage(
                    slug, stage, projects_dir=project_dir.parent,
                    source_path=source_path, panel_upload=body.panels,
                    word_target=body.word_target, brief_path=brief_path,
                    force=body.force,
                )
                ok = True
            except Exception as exc:  # noqa: BLE001 - surface to caller, no swallow
                err_msg = f"{type(exc).__name__}: {exc}"
            finally:
                with _lock_map:
                    _locks.pop(key, None)
                # Persist the outcome on the project's blueprint so the dashboard
                # does not sit on "running" forever after a stage crash. The
                # previous version swallowed exceptions silently, which left
                # stages permanently stuck at "running" in the UI.
                if not ok:
                    (project_dir / "logs").mkdir(parents=True, exist_ok=True)
                    (project_dir / "logs" / f"{stage}.error").write_text(
                        err_msg, encoding="utf-8"
                    )
                    try:
                        bp = Blueprint.load(project_dir)
                        entry = bp.stages.get(stage)
                        if entry is not None:
                            entry.status = "failed"
                            entry.ts = time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                            )
                            bp.write(project_dir)
                    except Exception:
                        pass

        t = threading.Thread(target=worker, daemon=True, name=f"pipe-{slug}-{stage}")
        _locks[key] = t
        t.start()

    return {"slug": slug, "stage": stage, "status": "running"}


class RunAllIn(BaseModel):
    brief: str | None = None          # stage0 mode 0b: inline brief (persisted on demand)
    source_text: str | None = None    # stage0 mode 0a: inline source (persisted to input/source.txt)
    source: str | None = None         # stage0 mode 0a: server-side path to source text
    panels: str | None = None         # stage0 mode 0i: zip/folder of panels
    word_target: int | None = None    # stage0 mode 0a: prose word budget


@app.post("/api/pipeline/{slug}/run-all")
def pipeline_run_all(slug: str, body: RunAllIn | None = None):
    """Run every remaining stage in STAGE_ORDER (resume-safe). Intended for the
    Studio 'RUN ALL' button. Stages already proven complete are skipped by the
    engine; stages 0 (intake), 1 (world bible), 3 (storyboard), 2 (screenplay),
    and 4 (audio) that use Ollama run with the local review model when needed."""
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if not (project_dir / "blueprint.json").exists():
        raise HTTPException(404, f"no project: {slug!r}")

    key = (slug, "_all")
    with _lock_map:
        t = _locks.get(key)
        if t and t.is_alive():
            raise HTTPException(409, f"{slug} full run already in progress")

        import run as prun
        body = body or RunAllIn()

        def worker():
            err_msg = ""
            try:
                source_path = body.source
                if body.brief:
                    (project_dir / "input").mkdir(parents=True, exist_ok=True)
                    brief_md = body.brief
                    if "word_target:" not in brief_md:
                        brief_md = "---\nword_target: 800\n---\n\n" + brief_md
                    (project_dir / "input" / "brief.md").write_text(brief_md, encoding="utf-8")
                if body.source_text:
                    (project_dir / "input").mkdir(parents=True, exist_ok=True)
                    (project_dir / "input" / "source.txt").write_text(body.source_text, encoding="utf-8")
                    source_path = project_dir / "input" / "source.txt"
                prun.run_all(
                    slug,
                    projects_dir=project_dir.parent,
                    brief_path=project_dir / "input" / "brief.md"
                    if (project_dir / "input" / "brief.md").exists() else None,
                    source_path=source_path,
                    panel_upload=body.panels,
                    word_target=body.word_target,
                    run_critique=False,
                )
            except Exception as exc:  # noqa: BLE001 - surface to caller
                err_msg = f"{type(exc).__name__}: {exc}"
                (project_dir / "logs").mkdir(parents=True, exist_ok=True)
                (project_dir / "logs" / "run_all.error").write_text(err_msg, encoding="utf-8")
            finally:
                with _lock_map:
                    _locks.pop(key, None)

        t = threading.Thread(target=worker, daemon=True, name=f"pipe-{slug}-all")
        _locks[key] = t
        t.start()

    return {"slug": slug, "status": "running"}


@app.get("/api/pipeline/{slug}/log/{stage}")
def pipeline_stage_log(slug: str, stage: str):
    """Per-stage run log/error text (written by the kernel worker on failure, or
    the stage's own logs). Returns {'log': str, 'exists': bool}."""
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if not (project_dir / "blueprint.json").exists():
        raise HTTPException(404, f"no project: {slug!r}")
    candidates = [
        project_dir / "logs" / f"{stage}.error",
        project_dir / "logs" / f"{stage}.log",
        project_dir / "logs" / "run_all.error",
    ]
    for p in candidates:
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            return {"log": text[-20000:], "exists": True, "path": str(p)}
    return {"log": "", "exists": False}


# ── pipeline artifacts (per-stage viewable outputs) ────────────────────────

# Map each stage to the glob patterns (relative to the project dir) that its
# artifacts live under. Ordered so the most representative output is first.
_STAGE_ARTIFACT_GLOBS: dict[str, list[str]] = {
    "stage0": ["input/script.txt", "input/brief.md", "stage0_scenes.json"],
    "stage0_dossier": ["intake/dossier.json"],
    "stage1": ["worldbible/world_bible.json", "worldbible/contradictions.json", "voices.json"],
    "stage1r": ["worldbible/refs/*/ref_*.png", "worldbible/refs/_style/*", "worldbible/refs/*/voice_audition.wav"],
    "stage2": ["screenplay/screenplay.json"],
    "stage3": ["storyboard/storyboard.json"],
    "stage3b": ["plates/*.png", "panels/*.png"],
    "stage3c": ["clips/*.mp4"],
    "stage_vlm_review": ["reviews/vlm_review.json"],
    "stage4": ["audio/**/*.wav"],
    "stage5": ["video/final.mp4", "video/*.mp4"],
}

_ARTIFACT_MIME = {
    "json": "application/json", "txt": "text/plain", "md": "text/plain",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
    "wav": "audio/wav", "mp3": "audio/mpeg", "mp4": "video/mp4",
}


def _safe_project_path(project_dir: Path, rel: str) -> Path:
    p = (project_dir / rel).resolve()
    if not p.is_relative_to(project_dir.resolve()):
        raise HTTPException(400, "path escapes project dir")
    return p


@app.get("/api/pipeline/{slug}/artifacts")
def pipeline_artifacts(slug: str):
    """Index of viewable artifacts per stage (relative paths + kind)."""
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if not project_dir.is_dir():
        raise HTTPException(404, f"no project: {slug!r}")
    out: dict[str, list[dict]] = {}
    for stage, globs in _STAGE_ARTIFACT_GLOBS.items():
        found: list[dict] = []
        seen: set[str] = set()
        for g in globs:
            for p in sorted(project_dir.glob(g)):
                if p.is_file():
                    rel = str(p.relative_to(project_dir))
                    if rel in seen:
                        continue
                    seen.add(rel)
                    ext = p.suffix.lower().lstrip(".")
                    found.append({
                        "path": rel,
                        "kind": "image" if ext in ("png", "jpg", "jpeg", "webp")
                        else "video" if ext == "mp4"
                        else "audio" if ext in ("wav", "mp3")
                        else "text" if ext in ("txt", "md")
                        else "json",
                        "name": p.name,
                    })
        out[stage] = found
    return out


@app.get("/api/pipeline/{slug}/file")
def pipeline_file(slug: str, path: str):
    """Stream a single project artifact by relative path."""
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if not project_dir.is_dir():
        raise HTTPException(404, f"no project: {slug!r}")
    p = _safe_project_path(project_dir, path)
    if not p.is_file():
        raise HTTPException(404, f"no such file: {path!r}")
    mime = _ARTIFACT_MIME.get(p.suffix.lower().lstrip("."), "application/octet-stream")
    return FileResponse(p, media_type=mime)


from fastapi import UploadFile, File as _File  # noqa: E402

_PANEL_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


@app.post("/api/pipeline/{slug}/panels")
def pipeline_upload_panels(slug: str, file: UploadFile = _File(...)):
    """Upload a panel image or zip into ``input/panels/`` for stage0 mode 0i.
    Accepts a single file (zip or image). Images are written flat; zips are
    extracted (only image members)."""
    import zipfile

    project_dir = PIPELINE_ENGINE / "projects" / slug
    if not project_dir.is_dir():
        raise HTTPException(404, f"no project: {slug!r}")
    panels_dir = project_dir / "input" / "panels"
    panels_dir.mkdir(parents=True, exist_ok=True)

    fname = Path(file.filename or "panel.png")
    ext = fname.suffix.lower()
    data = file.file.read()

    if ext == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            written = 0
            for m in zf.namelist():
                if m.endswith("/"):
                    continue
                mext = Path(m).suffix.lower()
                if mext in _PANEL_EXTS:
                    (panels_dir / Path(m).name).write_bytes(zf.read(m))
                    written += 1
        if not written:
            raise HTTPException(400, "zip contained no panel images (.png/.jpg/.jpeg/.webp)")
        return {"written": written}
    if ext not in _PANEL_EXTS:
        raise HTTPException(400, f"unsupported file type {ext!r}; want .png/.jpg/.jpeg/.webp or .zip")
    (panels_dir / fname.name).write_bytes(data)
    return {"written": 1}



# ── vault / brain ──────────────────────────────────────────────────────────

def _vault_root() -> Path:
    p = Path(cfg.paths.vault) if cfg.paths.vault else Path("/tmp/olympus-vault")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _validate_note_path(path: str) -> str:
    """Validate and sanitize note path to prevent directory traversal attacks."""
    if not path or not isinstance(path, str):
        raise HTTPException(400, "Invalid path: must be a non-empty string")
    
    # Remove any leading/trailing whitespace
    path = path.strip()
    
    # Prevent directory traversal attacks
    if ".." in path or path.startswith("/"):
        raise HTTPException(400, "Invalid path: directory traversal not allowed")
    
    # Prevent empty path after stripping
    if not path:
        raise HTTPException(400, "Invalid path: path cannot be empty")
    
    return path


@app.get("/api/brain/notes")
def brain_notes(folder: str = ""):
    # Validate folder path
    if folder:
        folder = _validate_note_path(folder)
    
    root = _vault_root()
    root_resolved = root.resolve()
    base = (root / folder).resolve()
    if not base.is_relative_to(root_resolved) or not base.is_dir():
        raise HTTPException(404, "folder not found")
    dirs = sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    notes = sorted(p.name for p in base.glob("*.md"))
    return [{"type": "dir", "name": d} for d in dirs] + [{"type": "note", "name": n} for n in notes]


@app.get("/api/brain/note")
def brain_note(path: str):
    import bleach
    import markdown as md

    # Validate path to prevent directory traversal
    path = _validate_note_path(path)
    
    root = _vault_root()
    root_resolved = root.resolve()
    p = (root / path).resolve()
    if not p.is_relative_to(root_resolved) or not p.is_file():
        raise HTTPException(404, "note not found")
    html = md.markdown(
        p.read_text(encoding="utf-8", errors="replace"),
        extensions=["tables", "fenced_code"],
    )
    safe = bleach.clean(
        html,
        tags=["p", "h1", "h2", "h3", "h4", "ul", "ol", "li", "strong", "em", "a",
              "code", "pre", "blockquote", "table", "thead", "tbody", "tr", "th",
              "td", "hr", "br", "img"],
        attributes={"a": ["href"], "img": ["src", "alt"]},
    )
    return {"path": path, "html": safe}


# ── system info ────────────────────────────────────────────────────────────

@app.get("/api/system")
def system_info():
    from collections import Counter
    counts = Counter(t["status"] for t in _tasks.values())
    return {
        "kernel": {"version": app.version, "port": cfg.kernel.port,
                   "core_agents": cfg.kernel.core_agents},
        "models": cfg.ollama.models.model_dump(),
        "nim": cfg.nim.model_dump(),
        "paths": cfg.paths.model_dump(),
        "tasks": {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
        },
        "agents": _AGENTS,
        "gpu": gpu_status(),
    }


# ── NIM model selection (permanent, no agent) ────────────────────────────

class NimModelIn(BaseModel):
    model: str = Field(min_length=1)


@app.get("/api/nim/models")
def nim_models():
    """List available NIM models and the currently active one (from stack.toml)."""
    return {
        "active": cfg.nim.model,
        "models": cfg.nim.models,
        "enabled": cfg.nim.enabled,
        "base_url": cfg.nim.base_url,
    }


@app.post("/api/nim/model")
def set_nim_model(body: NimModelIn):
    """Set the active NIM model permanently (writes to stack.toml, reloads config)."""
    if body.model not in cfg.nim.models:
        raise HTTPException(400, f"unknown NIM model {body.model!r}; available: {cfg.nim.models}")
    # Update stack.toml in place (preserve comments/formatting where possible)
    toml_path = STACK_ROOT / "stack.toml"
    try:
        text = toml_path.read_text(encoding="utf-8")
        # Replace the `model = "..."` line inside [nim] section
        import re
        # Find [nim] section and its model line
        def repl(m):
            return m.group(1) + f'"{body.model}"' + m.group(3)
        # Pattern: inside [nim] block, find model = "..."
        # Simple approach: replace the first occurrence of model = "..." after [nim]
        nim_start = text.find("[nim]")
        if nim_start == -1:
            raise HTTPException(500, "stack.toml missing [nim] section")
        # Find next section after [nim]
        next_section = text.find("\n[", nim_start + 5)
        nim_block = text[nim_start:next_section if next_section != -1 else len(text)]
        new_nim_block = re.sub(
            r'(model\s*=\s*)"[^"]*"(\s*)',
            r'\1"' + body.model + r'"\2',
            nim_block,
            count=1,
        )
        if new_nim_block == nim_block:
            raise HTTPException(500, "could not find model line in [nim] section")
        new_text = text[:nim_start] + new_nim_block + (text[next_section:] if next_section != -1 else "")
        toml_path.write_text(new_text, encoding="utf-8")
        # Reload config singletons
        from stack.config import reload_config
        reload_config()
        # Also reload pipeline config cache if it exists
        try:
            import importlib
            import pipeline.config as pc
            importlib.reload(pc)
        except Exception:
            pass
        logger.info("NIM model switched to %s (written to stack.toml)", body.model)
        return {"active": body.model, "models": cfg.nim.models}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("failed to update NIM model: %s", e)
        raise HTTPException(500, str(e))


# ── static dashboard ───────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
