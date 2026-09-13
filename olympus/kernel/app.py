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
import os
import re
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
    if request.url.path in {"/api/voice/tts", "/api/orchestrate", "/api/nim/test"}:
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


# ── static dashboard ───────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")


# Serve the dashboard's split CSS/JS assets. Kept explicit (rather than a broad
# StaticFiles mount) so the root path stays reserved for index.html.
@app.get("/{asset}", include_in_schema=False)
def web_asset(asset: str):
    if asset not in ("styles.css", "app.js"):
        raise HTTPException(404, f"unknown asset: {asset!r}")
    return FileResponse(WEB_DIR / asset)


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
