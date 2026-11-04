"""Olympus Kernel — central hub for the Local AI Stack.

FastAPI service on :4600. Connects Ollama and Voice Studio. Serves the
Olympus dashboard UI.

Run:
    .venv/bin/uvicorn kernel.app:app --host 0.0.0.0 --port 4600
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import io
import json
import logging
import os
import re
import secrets
import subprocess
import urllib.parse
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
from stack.config import cfg

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
    if request.url.path in {"/api/voice/tts", "/api/orchestrate", "/api/nim/test",
                              "/api/commerce/deep-research"} or request.url.path.startswith("/api/studio/"):
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


_installed_ollama: set[str] | None = None
_installed_ollama_ts: float = 0.0


def _ollama_installed() -> set[str]:
    """Names of models currently installed in Ollama (cached 60s).

    The kernel resolves agent roles to a model that actually exists on this
    box. Ollama returns a 404 for a generate request on a model that is not
    pulled, which silently failed every Jarvis/capture/commerce task when the
    configured role model (e.g. ``llama3.2:3b``) was absent.
    """
    global _installed_ollama, _installed_ollama_ts
    now = time.time()
    if _installed_ollama is not None and now - _installed_ollama_ts < 60:
        return _installed_ollama
    names: set[str] = set()
    try:
        req = urllib.request.Request(cfg.ollama.url + "/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            names = {m.get("name", "") for m in json.loads(resp.read()).get("models", [])}
    except Exception:
        pass
    _installed_ollama = names
    _installed_ollama_ts = now
    return names


def _resolve_model(role: str) -> str:
    """Map an agent model role name to an Ollama model that is INSTALLED.

    Falls back to ``[ollama].models.default`` when the role's configured model
    is missing from the box so agent tasks never 404 on an unpulled model.
    """
    try:
        candidate = getattr(cfg.ollama.agents, role)
    except AttributeError:
        candidate = ""
    installed = _ollama_installed()
    if candidate and candidate in installed:
        return candidate
    default = cfg.ollama.models.default
    if default in installed:
        return default
    # Last resort: any installed completion model (prefer qwen3 family).
    for name in sorted(installed):
        if any(k in name for k in ("qwen3:", "qwen3-", "llama3")) and not name.startswith("hf.co"):
            return name
    return default


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
        "voice": "voice-studio.service",
        "open-webui": "open-webui.service",
    }
    if name in unit_map:
        try:
            logger.info("Starting service: %s (%s)", name, unit_map[name])
            result = subprocess.run(
                ["systemctl", "--user", "start", unit_map[name]],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).decode(errors="replace").strip()
                raise HTTPException(503, detail or f"systemctl failed with exit code {result.returncode}")
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
        if len(_active_tasks) >= _MAX_CONCURRENT_TASKS:
            raise HTTPException(429, "Too many concurrent tasks. Please try again later.")
        task["status"] = "queued"
        task["result"] = None
        task["error"] = None
    threading.Thread(target=_run_task, args=(tid, task["text"], task["agent"]), daemon=True).start()
    return task


@app.post("/api/orchestrate", status_code=201)
def orchestrate(body: GoalIn):
    plans, _ = _call_ollama(_resolve_model("planner"), f"Plan this goal as numbered steps:\n{body.goal}")
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


@app.get("/api/voice/config")
def voice_config():
    return {
        "engine": getattr(cfg.voice, "engine", "auto"),
        "default_voice": getattr(cfg.voice, "default_voice", "af_heart"),
        "default_speed": getattr(cfg.voice, "default_speed", 1.0),
        "options": [
            {"id": "auto", "name": "Auto (Kokoro -> espeak-ng)", "local": True},
            {"id": "kokoro", "name": "Kokoro 82M", "local": True},
            {"id": "espeak-ng", "name": "espeak-ng", "local": True},
        ],
    }


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
    dirs = sorted(
        p.name for p in base.iterdir()
        if p.is_dir()
        and not p.name.startswith(".")
        # Skip symlinks that resolve outside the vault root so the dashboard's
        # folder walk never trips over them (e.g. vault shortcuts to ~/Downloads).
        and p.resolve().is_relative_to(root_resolved)
    )
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


# ── commerce (read-only product-research + n8n status) ──────────────────────

_ZIK_PATH = Path("/home/amire/n8n-stack/zik_data.json")
_N8N_ENV_PATH = Path("/home/amire/n8n-stack/.env")
_N8N_API = "http://127.0.0.1:5679"


def _n8n_key() -> str:
    try:
        for line in _N8N_ENV_PATH.read_text().splitlines():
            if line.startswith("N8N_API_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


@app.get("/api/commerce/zik")
def commerce_zik(limit: int = 50):
    """Top Zik keywords/sellers from the n8n intake file (read-only)."""
    try:
        raw = _ZIK_PATH.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(503, "zik intake unavailable")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(503, "zik intake corrupt")
    kws = sorted(data.get("keywords", []),
                 key=lambda k: k.get("revenue_30d", 0), reverse=True)
    sellers = sorted(data.get("sellers", []),
                     key=lambda s: s.get("sales_30d", 0), reverse=True)
    limit = max(1, min(limit, 200))
    return {
        "keywords": kws[:limit],
        "keyword_count": len(kws),
        "sellers": sellers[:12],
        "updated": int(_ZIK_PATH.stat().st_mtime),
    }


@app.get("/api/commerce/n8n")
def commerce_n8n():
    """n8n workflow roster + latest product-research execution (read-only)."""
    key = _n8n_key()
    if not key:
        return {"reachable": False}
    try:
        req = urllib.request.Request(
            _N8N_API + "/api/v1/workflows?limit=100",
            headers={"X-N8N-API-KEY": key},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            ws = json.load(r).get("data", [])
    except Exception:
        return {"reachable": False}
    items = [{"id": w.get("id"), "name": w.get("name"),
              "active": bool(w.get("active"))} for w in ws]
    pr = next((w for w in ws if (w.get("name") or "") ==
               "Product research pipeline (Zik -> LLM -> Obsidian)"), None)
    last = None
    try:
        req = urllib.request.Request(
            _N8N_API + "/api/v1/executions?limit=20",
            headers={"X-N8N-API-KEY": key},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            exs = json.load(r).get("data", [])
        if pr:
            mine = [e for e in exs if str(e.get("workflowId")) == str(pr.get("id"))]
            if mine:
                e = mine[0]
                last = {"status": e.get("status"),
                        "startedAt": e.get("startedAt"),
                        "stoppedAt": e.get("stoppedAt")}
    except Exception:
        last = None
    return {
        "reachable": True,
        "workflows": len(ws),
        "active": sum(1 for w in ws if w.get("active")),
        "product_research": ({
            "id": pr.get("id"), "name": pr.get("name"),
            "active": bool(pr.get("active")), "last": last,
        } if pr else None),
        "items": items,
    }


# ── commerce workbench (intake + eBay comps proxy + reports) ───────────────
# Keys for the eBay comps proxy are per-request only (pasted per session in
# the dashboard) and are never stored or logged. Intake/report writes are
# confined to vault/Product Research/_intakes/.

_INTAKES_DIRNAME = "Product Research/_intakes"


def _commerce_slug(category: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (category or "").lower()).strip("-")[:60]
    if not slug or not re.fullmatch(r"[a-z0-9-]+", slug):
        raise HTTPException(400, "category must contain letters/numbers")
    return slug


def _intakes_dir() -> Path:
    root = _vault_root().resolve()
    d = (root / _INTAKES_DIRNAME).resolve()
    if not d.is_relative_to(root):
        raise HTTPException(400, "intakes dir escapes vault")
    d.mkdir(parents=True, exist_ok=True)
    return d


class IntakeKw(BaseModel):
    keyword: str = Field(max_length=200)
    revenue_30d: int = Field(ge=0, le=10_000_000_000)


class IntakeSeller(BaseModel):
    seller: str = Field(max_length=200)
    country: str = Field(default="", max_length=8)
    feedback: int = Field(default=0, ge=0)
    sales_30d: int = Field(default=0, ge=0)


class IntakeIn(BaseModel):
    category: str = Field(max_length=120)
    keywords: list[IntakeKw] = Field(max_length=300)
    sellers: list[IntakeSeller] = Field(default=[], max_length=100)


@app.post("/api/commerce/intakes", status_code=201)
def commerce_save_intake(body: IntakeIn):
    slug = _commerce_slug(body.category)
    p = (_intakes_dir() / f"{slug}.json").resolve()
    if not p.is_relative_to(_vault_root().resolve()):
        raise HTTPException(400, "path escapes vault")
    seen: dict[str, int] = {}
    kws = []
    for k in body.keywords:
        name = re.sub(r"\s*[,.;:]+\s*$", "", k.keyword.strip())
        name = re.sub(r"\s+", " ", name)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            seen[key] = max(seen[key], k.revenue_30d)
            continue
        seen[key] = k.revenue_30d
        kws.append({"keyword": name, "revenue_30d": k.revenue_30d})
    kws.sort(key=lambda k: k["revenue_30d"], reverse=True)
    p.write_text(json.dumps({
        "category": body.category.strip(), "slug": slug,
        "keywords": kws, "sellers": [s.model_dump() for s in body.sellers],
    }, indent=1), encoding="utf-8")
    return {"slug": slug, "keywords": len(kws), "sellers": len(body.sellers)}


class EbayCompsIn(BaseModel):
    keyword: str = Field(max_length=200)
    app_id: str = Field(max_length=200)
    cert_id: str = Field(max_length=200)
    env: str = Field(default="sandbox", max_length=16)
    limit: int = Field(default=10, ge=1, le=25)


@app.post("/api/commerce/ebay-comps")
def commerce_ebay_comps(body: EbayCompsIn):
    """Live eBay comps for one keyword. Keys stay in memory, never stored."""
    host = {"sandbox": "api.sandbox.ebay.com",
            "production": "api.ebay.com"}.get(body.env)
    if not host:
        raise HTTPException(400, "env must be sandbox or production")
    basic = base64.b64encode(
        f"{body.app_id.strip()}:{body.cert_id.strip()}".encode()).decode()
    try:
        tok_req = urllib.request.Request(
            f"https://{host}/identity/v1/oauth2/token",
            data=b"grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            headers={"Authorization": "Basic " + basic,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(tok_req, timeout=10) as r:
            token = json.load(r).get("access_token", "")
        if not token:
            raise ValueError("no token")
    except Exception:
        raise HTTPException(502, "eBay auth failed — check keys/env")
    try:
        q = urllib.parse.quote(body.keyword.strip())
        search = urllib.request.Request(
            f"https://{host}/buy/browse/v1/item_summary/search"
            f"?q={q}&limit={body.limit}",
            headers={"Authorization": "Bearer " + token,
                     "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
        )
        with urllib.request.urlopen(search, timeout=10) as r:
            data = json.load(r)
    except Exception:
        raise HTTPException(502, "eBay search failed")
    prices: list[float] = []
    items = []
    for it in data.get("itemSummaries", []) or []:
        pr = (it.get("price") or {})
        try:
            v = float(pr.get("value", "nan"))
        except (TypeError, ValueError):
            continue
        prices.append(v)
        sl = it.get("seller") or {}
        im = it.get("image") or {}
        thumb = im.get("imageUrl", "")
        if isinstance(thumb, list):
            thumb = thumb[0] if thumb else ""
        items.append({"title": it.get("title", "")[:140],
                      "price": v, "currency": pr.get("currency", ""),
                      "url": it.get("itemWebUrl", ""),
                      "thumb": thumb,
                      "seller": sl.get("username", ""),
                      "seller_feedback": sl.get("feedbackScore"),
                      "seller_pct": sl.get("feedbackPercentage")})
    prices.sort()
    stats = None
    if prices:
        mid = prices[len(prices) // 2]
        stats = {"min": prices[0], "med": mid, "max": prices[-1],
                 "avg": round(sum(prices) / len(prices), 2),
                 "currency": (items[0].get("currency") if items else "")}
    return {"keyword": body.keyword.strip(), "env": body.env,
            "total": data.get("total", 0), "returned": len(items),
            "stats": stats, "items": items[:body.limit]}


@app.get("/api/commerce/trends")
def commerce_trends(keyword: str):
    """Google-interest trend for one keyword via the local trends proxy."""
    kw = (keyword or "").strip()[:200]
    if not kw:
        raise HTTPException(400, "keyword required")
    try:
        url = ("http://127.0.0.1:8791/trends?keyword="
               + urllib.parse.quote(kw))
        with urllib.request.urlopen(url, timeout=45) as r:
            return json.load(r)
    except Exception:
        raise HTTPException(502, "trends unavailable")


class ReportIn(BaseModel):
    slug: str = Field(max_length=70)
    markdown: str = Field(max_length=100_000)


@app.post("/api/commerce/reports", status_code=201)
def commerce_save_report(body: ReportIn):
    slug = _commerce_slug(body.slug)
    p = (_intakes_dir() / f"{slug}-report.md").resolve()
    if not p.is_relative_to(_vault_root().resolve()):
        raise HTTPException(400, "path escapes vault")
    p.write_text(body.markdown, encoding="utf-8")
    return {"path": f"{_INTAKES_DIRNAME}/{slug}-report.md"}


@app.get("/api/commerce/insights")
def commerce_insights(limit: int = 200):
    """Rank research notes by opportunity score (parsed from frontmatter)."""
    root = _vault_root().resolve()
    base = (root / "Product Research").resolve()
    items: list[dict] = []
    if base.is_relative_to(root) and base.is_dir():
        for p in sorted(base.glob("*.md"))[:max(1, min(limit, 500))]:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not text.startswith("---"):
                continue
            end = text.find("\n---", 3)
            if end < 0:
                continue
            fm: dict[str, str] = {}
            for line in text[3:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip().lower()] = v.strip()

            def num(key: str):
                m = re.search(r"[\d,]+", fm.get(key, ""))
                return int(m.group(0).replace(",", "")) if m else None

            items.append({"file": p.name,
                          "keyword": fm.get("keyword", p.stem),
                          "category": fm.get("category", ""),
                          "revenue_30d": num("revenue_30d"),
                          "opportunity": num("opportunity")})
    items.sort(key=lambda i: (i["opportunity"] is None, -(i["opportunity"] or 0)))
    return {"items": items, "count": len(items)}


# ── commerce deep pipeline (proxy to the n8n zik-deep-research workflow) ──
# Per-run eBay keys pass through kernel memory only: forwarded to the n8n
# webhook in the POST body, never written anywhere. The webhook guard key
# and n8n API key stay server-side (read from ~/n8n-stack/.env).

_N8N_DEEP_WEBHOOK = "http://127.0.0.1:5679/webhook/zik-research"


def _hook_key() -> str:
    try:
        for line in _N8N_ENV_PATH.read_text().splitlines():
            if line.startswith("HOOK_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


class DeepIn(BaseModel):
    category: str = Field(max_length=120)
    keywords: list[IntakeKw] = Field(max_length=30)
    sellers: list[IntakeSeller] = Field(default=[], max_length=12)
    app_id: str = Field(max_length=200)
    cert_id: str = Field(max_length=200)


@app.post("/api/commerce/deep-research")
def commerce_deep_start(body: DeepIn):
    guard = _hook_key()
    if not guard:
        raise HTTPException(503, "pipeline guard unavailable")
    if not body.keywords:
        raise HTTPException(400, "no keywords")
    if not body.app_id.strip() or not body.cert_id.strip():
        raise HTTPException(400, "eBay keys required for the deep pipeline")
    payload = json.dumps({
        "category": body.category.strip() or "general",
        "app_id": body.app_id.strip(), "cert_id": body.cert_id.strip(),
        "keywords": [{"keyword": k.keyword, "revenue_30d": k.revenue_30d}
                     for k in body.keywords],
        "sellers": [s.model_dump() for s in body.sellers],
    }).encode()
    req = urllib.request.Request(
        _N8N_DEEP_WEBHOOK, data=payload,
        headers={"X-Hook-Key": guard, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=280) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read()[:150].decode(errors="replace")
        if e.code == 404:
            raise HTTPException(502, "pipeline offline — activate it in the n8n UI first")
        raise HTTPException(502, f"pipeline failed: {detail}")
    except Exception as e:
        raise HTTPException(504, f"pipeline timed out or unreachable: {str(e)[:120]}")


# ── system info ────────────────────────────────────────────────────────────

@app.get("/api/system")
def system_info():
    from collections import Counter
    counts = Counter(t["status"] for t in _tasks.values())
    animation_enabled = bool(getattr(getattr(cfg, "animation", None), "enabled", False))
    return {
        "kernel": {"version": app.version, "port": cfg.kernel.port,
                   "core_agents": cfg.kernel.core_agents},
        "models": cfg.ollama.models.model_dump(),
        "nim": cfg.nim.model_dump(),
        "animation": {"enabled": animation_enabled},
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


class AnimationIn(BaseModel):
    enabled: bool = False


@app.get("/api/animation")
def get_animation():
    return {"enabled": bool(getattr(getattr(cfg, "animation", None), "enabled", False))}


@app.post("/api/animation")
def set_animation(body: AnimationIn):
    """Studio ANIMATION master switch (persisted to stack.toml [animation])."""
    global cfg
    try:
        cfg.animation.enabled = body.enabled
    except Exception:
        raise HTTPException(500, "animation config unavailable")
    try:
        toml_path = STACK_ROOT / "stack.toml"
        text = toml_path.read_text(encoding="utf-8")
        if "[animation]" not in text:
            text = text.rstrip() + "\n\n[animation]\nenabled = false\n"
        start = text.find("[animation]")
        end = text.find("\n[", start + len("[animation]"))
        end = end if end != -1 else len(text)
        block = text[start:end]
        block = re.sub(r"(enabled\s*=\s*)(true|false)",
                       rf"\1{'true' if body.enabled else 'false'}", block, count=1)
        toml_path.write_text(text[:start] + block + text[end:], encoding="utf-8")
    except Exception as e:
        logger.error("failed to persist [animation]: %s", e)
        raise HTTPException(500, f"applied in memory but could not save: {e}")
    return {"enabled": body.enabled}


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
        "engine": cfg.nim.engine,
        "offload_llm": cfg.nim.offload_llm,
        "offload_vision": cfg.nim.offload_vision,
        "offload_images": cfg.nim.offload_images,
        "text_model": cfg.nim.text_model,
        "vision_model": cfg.nim.vision_model,
        "image_model": cfg.nim.image_model,
        "api_key_present": bool(_nvidia_key_resolved()),
    }


def _nvidia_key_resolved() -> str:
    try:
        from pipeline.nvidia_gen import resolve_api_key
        return resolve_api_key(cfg.nim) or ""
    except Exception:
        return ""


class NimEngineIn(BaseModel):
    engine: str = "local"
    offload_llm: bool | None = None
    offload_vision: bool | None = None
    offload_images: bool | None = None

@app.post("/api/nim/engine")
def set_nim_engine(body: NimEngineIn):
    """Set the generation engine + offload flags (updates in-memory config)."""
    global cfg
    if body.engine not in ("local", "nvidia"):
        raise HTTPException(400, "engine must be 'local' or 'nvidia'")
    if body.engine == "nvidia" and not _nvidia_key_resolved():
        raise HTTPException(400, "no NVIDIA API key — set NVIDIA_API_KEY or .agent-secrets/nvidia_key")
    try:
        # Update in-memory config only (TOML write is unreliable)
        cfg.nim.engine = body.engine
        if body.offload_llm is not None:
            cfg.nim.offload_llm = body.offload_llm
        if body.offload_vision is not None:
            cfg.nim.offload_vision = body.offload_vision
        if body.offload_images is not None:
            cfg.nim.offload_images = body.offload_images
        # Keep the selection available after a kernel restart. This updates
        # only the [nim] block and preserves the rest of stack.toml.
        toml_path = STACK_ROOT / "stack.toml"
        text = toml_path.read_text(encoding="utf-8")
        nim_start = text.find("[nim]")
        next_section = text.find("\n[", nim_start + 5)
        end = next_section if next_section != -1 else len(text)
        block = text[nim_start:end]
        block = re.sub(r"(engine\s*=\s*)\"[^\"]*\"", rf'\1"{body.engine}"', block, count=1)
        for field in ("offload_llm", "offload_vision", "offload_images"):
            value = getattr(cfg.nim, field)
            block = re.sub(rf"({field}\s*=\s*)(true|false)", rf"\1{'true' if value else 'false'}", block, count=1)
        toml_path.write_text(text[:nim_start] + block + text[end:], encoding="utf-8")
        logger.info("NIM engine set to %s (in-memory update)", body.engine)
        return nim_models()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("failed to update NIM engine: %s", e)
        raise HTTPException(500, str(e))


def _provider_registry_payload() -> dict:
    """Return registry data without exposing credentials or secret values."""
    selections = {
        capability: getattr(cfg.providers, capability).model_dump()
        for capability in ("llm", "vision", "t2i", "i2i", "i2v", "tts")
    }
    providers = {}
    for provider_id, definition in cfg.providers.registry.items():
        credential_present = bool(definition.credential_env and os.environ.get(definition.credential_env))
        if provider_id == "nvidia_nim":
            credential_present = bool(_nvidia_key_resolved())
        providers[provider_id] = {
            **definition.model_dump(),
            "id": provider_id,
            "credential_present": credential_present,
        }
    return {
        "selections": selections,
        "providers": providers,
        "fallback": cfg.fallback.model_dump(),
    }


def _persist_provider_selections() -> None:
    """Persist capability selections without rewriting unrelated TOML content."""
    toml_path = STACK_ROOT / "stack.toml"
    text = toml_path.read_text(encoding="utf-8")
    start = text.find("[providers]\n")
    if start < 0:
        raise RuntimeError("stack.toml missing [providers] section")
    end = text.find("\n[providers.registry", start)
    if end < 0:
        end = len(text)
    block = text[start:end]
    for capability in ("llm", "vision", "t2i", "i2i", "i2v", "tts"):
        selection = getattr(cfg.providers, capability)
        replacement = rf'\1{{ provider = "{selection.provider}"' + (
            rf', model = "{selection.model}"' if selection.model else ""
        ) + " }"
        pattern = rf"(?m)^({capability}\s*=\s*)\{{[^\n]*\}}"
        block, count = re.subn(pattern, replacement, block, count=1)
        if not count:
            block += f'\n{capability} = {{ provider = "{selection.provider}" }}'
    toml_path.write_text(text[:start] + block + text[end:], encoding="utf-8")


@app.get("/api/providers")
def list_providers():
    return _provider_registry_payload()


class ProviderSettingsIn(BaseModel):
    selections: dict[str, dict[str, str]] = Field(default_factory=dict)


@app.post("/api/providers/settings")
def set_provider_settings(body: ProviderSettingsIn):
    global cfg
    capabilities = {"llm", "vision", "t2i", "i2i", "i2v", "tts"}
    for capability, selection in body.selections.items():
        if capability not in capabilities:
            raise HTTPException(400, f"unsupported capability: {capability}")
        provider_id = selection.get("provider", "")
        provider = cfg.providers.registry.get(provider_id)
        if provider is None:
            raise HTTPException(400, f"unknown provider: {provider_id}")
        if capability not in provider.capabilities:
            raise HTTPException(400, f"provider {provider_id!r} does not support {capability}")
        if not provider.enabled:
            raise HTTPException(400, f"provider {provider_id!r} is disabled")
        if provider.kind == "hosted" and not _provider_registry_payload()["providers"][provider_id]["credential_present"]:
            raise HTTPException(400, f"provider {provider_id!r} has no configured credentials")
        selected = getattr(cfg.providers, capability)
        selected.provider = provider_id
        selected.model = selection.get("model", "")
    try:
        _persist_provider_selections()
    except Exception as exc:
        logger.error("failed to persist provider selections: %s", exc)
        raise HTTPException(500, f"provider settings applied in memory but could not be saved: {exc}")
    return _provider_registry_payload()


@app.post("/api/providers/reset-local")
def reset_provider_settings():
    defaults = {"llm": "ollama", "vision": "ollama", "tts": "voice_studio"}
    for capability, provider_id in defaults.items():
        selected = getattr(cfg.providers, capability)
        selected.provider = provider_id
        selected.model = ""
    try:
        _persist_provider_selections()
    except Exception as exc:
        logger.error("failed to persist local provider defaults: %s", exc)
        raise HTTPException(500, f"local defaults applied in memory but could not be saved: {exc}")
    return _provider_registry_payload()


@app.post("/api/nim/test")
def test_nim():
    """Live test: one chat call to the configured NVIDIA text model. Verifies the
    API key + endpoint so the Studio 'TEST' button gives real confirmation."""
    if not _nvidia_key_resolved():
        raise HTTPException(400, "no NVIDIA API key configured")
    try:
        from pipeline.nvidia_gen import NvidiaClient
        client = NvidiaClient(cfg.nim)
        out = client.chat(
            "Reply with exactly: OK", max_tokens=500,
            model=getattr(cfg.nim, "text_model", "deepseek-ai/deepseek-v4-flash-0731"),
        )
        if out is None:
            raise HTTPException(502, "NVIDIA API call failed (see kernel log)")
        return {"ok": True, "model": cfg.nim.text_model, "reply": out[:200]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/nim/model")
def set_nim_model(body: NimModelIn):
    """Set the active NIM model permanently (writes to stack.toml, reloads config)."""
    global cfg
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
        cfg = reload_config()
        logger.info("NIM model switched to %s (written to stack.toml)", body.model)
        return {"active": body.model, "models": cfg.nim.models}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("failed to update NIM model: %s", e)
        raise HTTPException(500, str(e))


# ── Studio pipeline bridge (anime/manga: script intake -> video) ──────────

PIPELINE_ENGINE = STACK_ROOT / "olympus" / "engines" / "pipeline"
if str(PIPELINE_ENGINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ENGINE))

from pipeline.blueprint import Blueprint, STAGE_ORDER
from pipeline.scores import Scores

_locks: dict[tuple, threading.Thread] = {}
_lock_map = threading.Lock()
_stop_requests: set[str] = set()


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
            results.append({"slug": bp.slug, "story_id": bp.story_id,
                            "fps": bp.fps, "created": bp.created})
        except Exception:
            continue
    results.sort(key=lambda p: p.get("created", ""), reverse=True)
    return results


class ProjectIn(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    brief_text: str | None = None
    script_text: str | None = None
    fps: int = 24
    mode: str = "0b"


@app.post("/api/pipeline/projects", status_code=201)
def pipeline_create(body: ProjectIn):
    import run as prun
    import tempfile

    slug = body.slug.strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", slug):
        raise HTTPException(400, "slug must be alphanumeric (letters, digits, _ , -)")
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if project_dir.exists():
        raise HTTPException(409, f"project {slug!r} exists")
    seed = body.brief_text or body.script_text or ""
    with tempfile.TemporaryDirectory() as tmp:
        seed_path = Path(tmp) / "seed.txt"
        seed_path.write_text(seed, encoding="utf-8")
        try:
            prun.new_project(slug, seed_path, fps=body.fps,
                             projects_dir=project_dir.parent, mode=body.mode)
        except Exception as e:
            raise HTTPException(400, str(e))
    (project_dir / "input").mkdir(parents=True, exist_ok=True)
    if body.mode == "0b" and body.brief_text:
        brief_md = body.brief_text
        if "word_target:" not in brief_md:
            brief_md = "---\nword_target: 800\n---\n\n" + brief_md
        (project_dir / "input" / "brief.md").write_text(brief_md, encoding="utf-8")
    elif body.mode in ("0a", "0s") and body.script_text:
        (project_dir / "input" / "source.txt").write_text(body.script_text, encoding="utf-8")
    bp = Blueprint.load(project_dir)
    return {"slug": bp.slug, "story_id": bp.story_id, "fps": bp.fps,
            "created": bp.created, "mode": bp.mode}


@app.get("/api/pipeline/{slug}/status")
def pipeline_status(slug: str):
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if not (project_dir / "blueprint.json").exists():
        raise HTTPException(404, f"no project: {slug!r}")
    bp = Blueprint.load(project_dir)
    try:
        ledger = Scores(project_dir / "scores.sqlite").report()["stages"]
    except Exception:
        ledger = {}
    stages = {}
    for stage in STAGE_ORDER:
        st = bp.stages.get(stage)
        status = st.status if st else "pending"
        info: dict = {"status": status}
        li = ledger.get(stage) or {}
        info["done"] = bool(li.get("done"))
        info["complete"] = bool(li.get("complete"))
        info["missing_metrics"] = li.get("missing_metrics", [])
        if status == "done":
            info["metrics"] = li.get("metrics", {})
        stages[stage] = info
    return {"slug": bp.slug, "story_id": bp.story_id, "fps": bp.fps, "mode": bp.mode,
            "animation_enabled": bool(getattr(getattr(cfg, "animation", None), "enabled", False)),
            "stages": stages}


class StageRunIn(BaseModel):
    source: str | None = None
    source_text: str | None = None
    panels: str | None = None
    word_target: int | None = None
    brief: str | None = None
    force: bool = False


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
            if body.force:
                try:
                    with Scores(project_dir / "scores.sqlite") as _sc:
                        _sc.clear_stage(stage)
                except Exception:
                    pass
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
                prun.run_stage(slug, stage, projects_dir=project_dir.parent,
                               source_path=source_path, panel_upload=body.panels,
                               word_target=body.word_target, brief_path=brief_path,
                               force=body.force)
                ok = True
            except Exception as exc:
                err_msg = f"{type(exc).__name__}: {exc}"
            finally:
                with _lock_map:
                    _locks.pop(key, None)
                if not ok:
                    (project_dir / "logs").mkdir(parents=True, exist_ok=True)
                    (project_dir / "logs" / f"{stage}.error").write_text(err_msg, encoding="utf-8")
                    try:
                        bp = Blueprint.load(project_dir)
                        entry = bp.stages.get(stage)
                        if entry is not None:
                            entry.status = "failed"
                            entry.ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                            bp.write(project_dir)
                    except Exception:
                        pass
        t = threading.Thread(target=worker, daemon=True, name=f"pipe-{slug}-{stage}")
        _locks[key] = t
        t.start()
    return {"slug": slug, "stage": stage, "status": "running"}


class RunAllIn(BaseModel):
    brief: str | None = None
    source_text: str | None = None
    source: str | None = None
    panels: str | None = None
    word_target: int | None = None
    step: bool = False
    quick: bool = False


@app.post("/api/pipeline/{slug}/run-all")
def pipeline_run_all(slug: str, body: RunAllIn | None = None):
    """Run every remaining stage in STAGE_ORDER (resume-safe)."""
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
                _stop_requests.discard(slug)
                prun.run_all(slug, projects_dir=project_dir.parent,
                             brief_path=project_dir / "input" / "brief.md"
                             if (project_dir / "input" / "brief.md").exists() else None,
                             source_path=source_path, panel_upload=body.panels,
                             word_target=body.word_target, run_critique=False,
                             step=body.step, quick=body.quick,
                             should_stop=lambda: slug in _stop_requests)
            except Exception as exc:
                (project_dir / "logs").mkdir(parents=True, exist_ok=True)
                (project_dir / "logs" / "run_all.error").write_text(
                    f"{type(exc).__name__}: {exc}", encoding="utf-8")
            finally:
                _stop_requests.discard(slug)
                with _lock_map:
                    _locks.pop(key, None)
        t = threading.Thread(target=worker, daemon=True, name=f"pipe-{slug}-all")
        _locks[key] = t
        t.start()
    return {"slug": slug, "status": "running"}


@app.post("/api/pipeline/{slug}/stop")
def pipeline_stop_run(slug: str):
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if not (project_dir / "blueprint.json").exists():
        raise HTTPException(404, f"no project: {slug!r}")
    _stop_requests.add(slug)
    return {"slug": slug, "status": "stop requested"}


@app.post("/api/pipeline/quick-test", status_code=201)
def pipeline_quick_test():
    import run as prun
    import tempfile
    from datetime import datetime

    slug = f"quicktest_{datetime.now().strftime('%H%M%S')}"
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if project_dir.exists():
        raise HTTPException(409, f"project {slug!r} exists — wait and retry")
    brief = ("---\nword_target: 300\n---\n\nA short anime test: a lone swordsman "
             "defends a mountain village from a shadow wolf on a stormy night. "
             "Protagonist Kael (silver hair, green eyes, worn armor).")
    with tempfile.TemporaryDirectory() as tmp:
        seed_path = Path(tmp) / "seed.txt"
        seed_path.write_text(brief, encoding="utf-8")
        try:
            prun.new_project(slug, seed_path, fps=24,
                             projects_dir=PIPELINE_ENGINE / "projects", mode="0b")
        except Exception as e:
            raise HTTPException(400, str(e))
    (project_dir / "input").mkdir(parents=True, exist_ok=True)
    (project_dir / "input" / "brief.md").write_text(brief, encoding="utf-8")
    key = (slug, "_all")
    with _lock_map:
        def worker():
            try:
                prun.run_all(slug, projects_dir=PIPELINE_ENGINE / "projects",
                             brief_path=project_dir / "input" / "brief.md",
                             run_critique=False, step=False, quick=True,
                             should_stop=lambda: slug in _stop_requests)
            except Exception as exc:
                (project_dir / "logs").mkdir(parents=True, exist_ok=True)
                (project_dir / "logs" / "run_all.error").write_text(
                    f"{type(exc).__name__}: {exc}", encoding="utf-8")
            finally:
                _stop_requests.discard(slug)
                with _lock_map:
                    _locks.pop(key, None)
        t = threading.Thread(target=worker, daemon=True, name=f"pipe-{slug}-all")
        _locks[key] = t
        t.start()
    return {"slug": slug, "status": "running", "mode": "0b", "quick": True}


@app.get("/api/pipeline/{slug}/log/{stage}")
def pipeline_stage_log(slug: str, stage: str):
    project_dir = PIPELINE_ENGINE / "projects" / slug
    if not (project_dir / "blueprint.json").exists():
        raise HTTPException(404, f"no project: {slug!r}")
    for p in [project_dir / "logs" / f"{stage}.error",
              project_dir / "logs" / f"{stage}.log",
              project_dir / "logs" / "run_all.error"]:
        if p.exists():
            return {"log": p.read_text(encoding="utf-8", errors="replace")[-20000:],
                    "exists": True, "path": str(p)}
    return {"log": "", "exists": False}


_STAGE_ARTIFACT_GLOBS: dict[str, list[str]] = {
    "stage0": ["input/script.txt", "input/brief.md", "stage0_scenes.json"],
    "stage0_dossier": ["intake/dossier.json"],
    "stage1": ["worldbible/world_bible.json", "worldbible/contradictions.json"],
    "stage1_world": ["worldbible/world_bible.json", "worldbible/contradictions.json"],
    "stage1r": ["worldbible/refs/*/*.png", "worldbible/refs/_manifest.json"],
    "stage3": ["storyboard/storyboard.json"],
    "stage2": ["screenplay/screenplay.json"],
    "stage3b": ["panels/*_manga.png", "panels/*.png"],
    "stage4": ["audio/**/*.wav", "audio/timeline.json"],
    "stage3c": ["clips/*.mp4"],
    "stage_vlm_review": ["reviews/vlm_review.json"],
    "stage5": ["video/final.mp4", "video/*.srt", "video/*.ffmetadata"],
}

_ARTIFACT_MIME = {
    "json": "application/json", "txt": "text/plain", "md": "text/plain",
    "srt": "text/plain", "ffmetadata": "text/plain",
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
                if Path(m).suffix.lower() in _PANEL_EXTS:
                    (panels_dir / Path(m).name).write_bytes(zf.read(m))
                    written += 1
        if not written:
            raise HTTPException(400, "zip contained no panel images")
        return {"written": written}
    if ext not in _PANEL_EXTS:
        raise HTTPException(400, f"unsupported file type {ext!r}")
    (panels_dir / fname.name).write_bytes(data)
    return {"written": 1}


# ── static dashboard ───────────────────────────────────────────────────────

# Multi-page dashboard: olympus/web/pages/<slug>.html + olympus/web/css/*.css +
# olympus/web/js/*.js, served from clean URLs (/home, /tasks, …). The original
# single-page assets (/styles.css, /app.js, /web/index.html) stay reachable.
_DASHBOARD_SLUGS = {"home", "tasks", "wiki", "commerce",
                    "automations", "voice", "studio", "system"}

_NO_CACHE = {
    "Cache-Control": "no-store, max-age=0, must-revalidate, proxy-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _web_file(path) -> FileResponse:
    if not path.is_file():
        raise HTTPException(404, f"unknown asset: {path.name!r}")
    return FileResponse(path, headers=_NO_CACHE)


@app.get("/", include_in_schema=False)
def index():
    return _web_file(WEB_DIR / "pages" / "home.html")


@app.get("/css/{asset}", include_in_schema=False)
def web_css(asset: str):
    return _web_file(WEB_DIR / "css" / asset)


@app.get("/js/{asset}", include_in_schema=False)
def web_js(asset: str):
    return _web_file(WEB_DIR / "js" / asset)


@app.get("/pages/{asset}", include_in_schema=False)
def web_page_file(asset: str):
    return _web_file(WEB_DIR / "pages" / asset)


# Clean page URLs (/home, /tasks, …) plus the legacy SPA assets.
@app.get("/{asset}", include_in_schema=False)
def web_asset(asset: str):
    if asset in _DASHBOARD_SLUGS:
        return _web_file(WEB_DIR / "pages" / f"{asset}.html")
    if asset in ("styles.css", "app.js"):
        return _web_file(WEB_DIR / asset)
    raise HTTPException(404, f"unknown asset: {asset!r}")


# ── Studio API (used by W.A.T. studio_* tools) ─────────────────────────────
# GPU work for other machines: image (FLUX.2 klein via ComfyUI), voice, short
# video (SVD). Every job goes through pipeline.gpu_lock.gpu_batch, which unloads
# Ollama first, so ComfyUI and Ollama never share the 8 GB card.
# Auth: Bearer token from $STUDIO_TOKEN or ~/.config/wat/studio.token.

STUDIO_OUT = Path(os.environ.get("STUDIO_OUT", str(Path.home() / "Studio" / "out")))
_STUDIO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$")


def _studio_token() -> str:
    tok = os.environ.get("STUDIO_TOKEN", "")
    if not tok:
        try:
            tok = (Path.home() / ".config" / "wat" / "studio.token").read_text().strip()
        except OSError:
            tok = ""
    return tok


def _studio_auth(request: Request) -> None:
    tok = _studio_token()
    got = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not tok or not hmac.compare_digest(tok, got):
        raise HTTPException(401, "studio token missing or invalid")


WAT_DB = Path(os.environ.get("WAT_DB", str(Path.home() / "Dev" / "wat" / "state" / "wat.db")))


def _studio_gpu_guard() -> None:
    """Refuse while a W.A.T. GPU task runs here: gpu_batch would unload its Ollama model
    mid-run. (The W.A.T. governor checks the other direction via the GPU lock file.)"""
    if not WAT_DB.exists():
        return
    import sqlite3
    try:
        c = sqlite3.connect(f"file:{WAT_DB}?mode=ro", uri=True, timeout=3)
        rows = c.execute("select name from tasks where status='running' and gpu=1 limit 3").fetchall()
        c.close()
    except sqlite3.Error:
        return
    if rows:
        raise HTTPException(409, "GPU busy with W.A.T. task(s): " + ", ".join(r[0] for r in rows)
                            + " - try again in a few minutes")


def _studio_dest(kind: str, ext: str) -> Path:
    STUDIO_OUT.mkdir(parents=True, exist_ok=True)
    return STUDIO_OUT / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}.{ext}"


class StudioImageIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    seed: int | None = None


class StudioTTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice: str = "af_heart"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class StudioVideoIn(BaseModel):
    prompt: str | None = Field(default=None, max_length=2000)
    image_file: str | None = None
    seed: int | None = None
    frames: int = Field(default=14, ge=8, le=25)
    fps: float = Field(default=6.0, ge=2, le=24)


@app.post("/api/studio/image")
def studio_image(body: StudioImageIn, request: Request):
    _studio_auth(request)
    _studio_gpu_guard()
    from pipeline.comfy_client import render_panel
    t0, seed = time.time(), body.seed if body.seed is not None else secrets.randbelow(2**31)
    dest = _studio_dest("image", "png")
    try:
        render_panel(body.prompt, dest, seed)
    except TimeoutError as e:
        raise HTTPException(504, str(e)[:300])
    except Exception as e:
        raise HTTPException(503, f"image render failed: {str(e)[:300]}")
    return {"file": dest.name, "seed": seed, "seconds": round(time.time() - t0, 1)}


@app.post("/api/studio/tts")
def studio_tts(body: StudioTTSIn, request: Request):
    _studio_auth(request)
    _studio_gpu_guard()
    from pipeline.voice_client import synth
    t0, dest = time.time(), _studio_dest("voice", "wav")
    path, used = synth(body.text, dest, voice=body.voice, speed=body.speed)
    if not used:
        Path(path).unlink(missing_ok=True)
        raise HTTPException(503, "no TTS engine answered (Voice Studio down or GPU busy)")
    return {"file": Path(path).name, "seconds": round(time.time() - t0, 1)}


@app.post("/api/studio/video")
def studio_video(body: StudioVideoIn, request: Request):
    _studio_auth(request)
    _studio_gpu_guard()
    from pipeline.comfy_client import animate_panel, render_panel
    t0, seed = time.time(), body.seed if body.seed is not None else secrets.randbelow(2**31)
    if body.image_file:
        if not _STUDIO_NAME.match(body.image_file) or not (STUDIO_OUT / body.image_file).is_file():
            raise HTTPException(404, "image_file not found in studio output")
        still = STUDIO_OUT / body.image_file
    elif body.prompt:
        still = _studio_dest("still", "png")
        try:
            render_panel(body.prompt, still, seed)
        except Exception as e:
            raise HTTPException(503, f"still render failed: {str(e)[:300]}")
    else:
        raise HTTPException(400, "give prompt or image_file")
    dest = _studio_dest("video", "mp4")
    try:
        out = animate_panel(still, dest, seed, frames=body.frames, fps=body.fps)
    except Exception as e:
        raise HTTPException(503, f"animation failed: {str(e)[:300]}")
    return {"file": Path(out).name, "still": still.name, "seed": seed, "seconds": round(time.time() - t0, 1)}


@app.get("/api/studio/file/{name}")
def studio_file(name: str, request: Request):
    _studio_auth(request)
    if not _STUDIO_NAME.match(name) or not (STUDIO_OUT / name).is_file():
        raise HTTPException(404, "no such studio file")
    return FileResponse(STUDIO_OUT / name)


@app.get("/api/studio/status")
def studio_status():
    from pipeline import gpu_lock
    def up(url):
        try:
            urllib.request.urlopen(url, timeout=3).read(64)
            return True
        except Exception:
            return False
    holder = ""
    try:
        holder = gpu_lock.LOCK_PATH.read_text()[:200] if gpu_lock.LOCK_PATH.exists() else ""
    except OSError:
        pass
    recent = sorted(STUDIO_OUT.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:10] if STUDIO_OUT.exists() else []
    return {"comfyui": up(gpu_lock.COMFYUI_URL + "/system_stats"), "voice": up(cfg.voice.url + "/api/voices"),
            "gpu_lock": holder, "token_configured": bool(_studio_token()),
            "recent": [p.name for p in recent]}


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
