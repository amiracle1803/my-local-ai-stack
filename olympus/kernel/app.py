"""Olympus kernel — FastAPI service on port 4600.

Endpoints match the original kernel's contract (recovered from
E:\\AI\\Models\\hermes\\skills\\local-agent-hub-ops\\references\\olympus-instance-notes.md):

    GET    /api/health              health + agent count + GPU status
    GET    /api/agents              registered agents
    POST   /api/agents/reload       hot-reload agent .md files
    POST   /api/agents/factory      create an agent .md programmatically
    DELETE /api/agents/{aid}        delete (refuses core agents)
    POST   /api/tasks               submit ({"text": "...", "agent": "..."})
    GET    /api/tasks               list tasks
    GET    /api/tasks/{tid}         task record (answer field is `result`)
    POST   /api/tasks/{tid}/rerun   re-run as a new task
    POST   /api/tasks/{tid}/retry   retry a failed task in place

Run (from olympus/):  ..\\.venv\\Scripts\\python.exe -m uvicorn kernel.app:app --host 0.0.0.0 --port 4600
"""

from __future__ import annotations

import json
import subprocess
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import services
from .agents import AgentRegistry
from .config import WEB_DIR, load_config
from .tasks import TaskManager

app = FastAPI(title="Olympus", version="2.0.0-rebuild")
registry = AgentRegistry()
tasks = TaskManager(registry)


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


def _gpu_status() -> dict:
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


def _ollama_ok() -> bool:
    try:
        url = load_config()["ollama"]["base_url"].rstrip("/") + "/api/version"
        with urllib.request.urlopen(url, timeout=3) as resp:
            json.load(resp)
        return True
    except Exception:
        return False


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "agents": registry.count(),
        "ollama": _ollama_ok(),
        "gpu": _gpu_status(),
    }


@app.get("/api/agents")
def list_agents() -> list[dict]:
    return [a.to_public() for a in registry.all()]


@app.post("/api/agents/reload")
def reload_agents() -> dict:
    return {"reloaded": registry.reload()}


@app.post("/api/agents/factory", status_code=201)
def create_agent(body: AgentIn) -> dict:
    try:
        agent = registry.create(body.id, body.name, body.domain, body.model,
                                body.keywords, body.description, body.system_prompt)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return agent.to_public()


@app.delete("/api/agents/{aid}")
def delete_agent(aid: str) -> dict:
    try:
        registry.delete(aid)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except FileNotFoundError:
        raise HTTPException(404, f"no agent '{aid}'")
    return {"deleted": aid}


@app.post("/api/tasks", status_code=201)
def submit_task(body: TaskIn) -> dict:
    try:
        return tasks.submit(body.text, body.agent)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/tasks")
def list_tasks() -> list[dict]:
    return tasks.list()


@app.get("/api/tasks/{tid}")
def get_task(tid: int) -> dict:
    task = tasks.get(tid)
    if task is None:
        raise HTTPException(404, f"no task {tid}")
    return task


@app.post("/api/tasks/{tid}/rerun", status_code=201)
def rerun_task(tid: int) -> dict:
    try:
        return tasks.rerun(tid)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/tasks/{tid}/retry")
def retry_task(tid: int) -> dict:
    try:
        return tasks.retry(tid)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


def _vault_root() -> "Path":
    from pathlib import Path
    return Path(load_config()["paths"]["vault"])


@app.get("/api/brain/notes")
def brain_notes(folder: str = "") -> list[dict]:
    """List markdown notes in the vault (read-only). folder='' is vault root."""
    root = _vault_root()
    base = (root / folder).resolve()
    if not str(base).startswith(str(root.resolve())) or not base.is_dir():
        raise HTTPException(404, "no such folder")
    dirs = sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    notes = sorted(p.name for p in base.glob("*.md"))
    return [{"type": "dir", "name": d} for d in dirs] + [{"type": "note", "name": n} for n in notes]


@app.get("/api/brain/note")
def brain_note(path: str) -> dict:
    """Return one vault note rendered to sanitized HTML."""
    import bleach
    import markdown as md
    root = _vault_root()
    p = (root / path).resolve()
    if not str(p).startswith(str(root.resolve())) or not p.is_file():
        raise HTTPException(404, "no such note")
    html = md.markdown(p.read_text(encoding="utf-8", errors="replace"),
                       extensions=["tables", "fenced_code"])
    safe = bleach.clean(html, tags=[
        "p", "h1", "h2", "h3", "h4", "ul", "ol", "li", "strong", "em", "a",
        "code", "pre", "blockquote", "table", "thead", "tbody", "tr", "th",
        "td", "hr", "br", "img",
    ], attributes={"a": ["href"], "img": ["src", "alt"]})
    return {"path": path, "html": safe}


class TTSIn(BaseModel):
    text: str = Field(min_length=1)
    voice: str = "af_heart"
    speed: float = 1.0


@app.get("/api/voice/voices")
def voice_voices() -> list:
    """Proxy to Voice Studio so the dashboard avoids cross-origin calls."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:5050/api/voices", timeout=5) as r:
            return json.load(r)
    except Exception:
        raise HTTPException(503, "Voice Studio is not running — start it from Services")


@app.post("/api/voice/tts")
def voice_tts(body: TTSIn) -> Response:
    req = urllib.request.Request(
        "http://127.0.0.1:5050/api/tts",
        data=json.dumps(body.model_dump()).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
    except Exception:
        raise HTTPException(503, "Voice Studio is not running — start it from Services")
    return Response(content=data, media_type="audio/wav")


@app.get("/api/services")
def list_services() -> list[dict]:
    return services.status_all()


@app.post("/api/services/{name}/start")
def start_service(name: str) -> dict:
    try:
        return services.start(name)
    except KeyError:
        raise HTTPException(404, f"unknown service '{name}' (known: {list(services.SERVICES)})")
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
