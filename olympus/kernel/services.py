"""Service launcher — lets agents/dashboard start local apps via the kernel.

    GET  /api/services               status of every known service
    POST /api/services/{name}/start  launch one (no-op if already running)

Services are Windows processes; "running" is detected by health URL when the
service has one, else by process name. Starting is fire-and-forget: apps like
Docker Desktop take a while to come up, so poll status afterwards.
"""

from __future__ import annotations

import os
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\amire\AppData\Local"))
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Service:
    name: str
    description: str
    health_url: str | None      # preferred liveness check
    process_name: str | None    # fallback liveness check (tasklist)
    start_args: list[str]       # command for subprocess.Popen
    cwd: str | None = None


SERVICES: dict[str, Service] = {s.name: s for s in [
    Service(
        name="obsidian",
        description="Obsidian (vault + Local REST API plugin on :27123)",
        health_url="http://127.0.0.1:27123/",
        process_name="Obsidian.exe",
        start_args=[str(LOCALAPPDATA / "Programs" / "Obsidian" / "Obsidian.exe")],
    ),
    Service(
        name="docker",
        description="Docker Desktop (engine for n8n/Langfuse/Qdrant containers)",
        health_url=None,
        process_name="Docker Desktop.exe",
        start_args=[r"C:\Program Files\Docker\Docker\Docker Desktop.exe"],
    ),
    Service(
        name="comfyui",
        description="ComfyUI on :8188 (GPU-heavy; --novram for the 8GB 4070)",
        health_url="http://127.0.0.1:8188/system_stats",
        process_name=None,
        # C: is the primary install; E:\AI\ComfyUI is the weekly-synced mirror
        # (scripts/sync-comfyui.ps1).
        start_args=[
            r"C:\AI\ComfyUI\.venv\Scripts\python.exe", "main.py",
            "--listen", "127.0.0.1", "--port", "8188",
            "--novram", "--disable-cuda-malloc", "--enable-manager",
        ],
        cwd=r"C:\AI\ComfyUI",
    ),
    Service(
        name="voice",
        description="Voice Studio (Kokoro TTS) on :5050",
        health_url="http://127.0.0.1:5050/api/health",
        process_name=None,
        start_args=[
            str(REPO_ROOT / "olympus" / "engines" / "voice" / ".venv" / "Scripts" / "python.exe"),
            "app.py",
        ],
        cwd=str(REPO_ROOT / "olympus" / "engines" / "voice"),
    ),
    Service(
        name="n8n",
        description="n8n automation on :5678 (Docker container)",
        health_url="http://127.0.0.1:5678/healthz",
        process_name=None,
        start_args=["docker", "compose", "up", "-d"],
        cwd=str(REPO_ROOT / "foundation"),
    ),
    Service(
        name="anythingllm",
        description="AnythingLLM Desktop (vault chat) on :3001",
        health_url="http://127.0.0.1:3001/api/ping",
        process_name="AnythingLLM.exe",
        start_args=[str(LOCALAPPDATA / "Programs" / "anythingllm-desktop" / "AnythingLLM.exe")],
    ),
    Service(
        name="langfuse",
        description="Langfuse LLM tracing on :3030 (Docker)",
        health_url="http://127.0.0.1:3030/api/public/health",
        process_name=None,
        start_args=["docker", "compose", "-f", "docker-compose-langfuse.yml", "up", "-d"],
        cwd=str(REPO_ROOT / "foundation"),
    ),
    Service(
        name="mcp gateway",
        description="Docker MCP gateway on :8811 (brave/github/n8n tools)",
        health_url="http://127.0.0.1:8811/sse",
        process_name=None,
        start_args=["cmd", "/c", "start-mcp-gateway.bat"],
        cwd=str(REPO_ROOT / "foundation"),
    ),
]}


def _health_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3):
            return True
    except urllib.error.HTTPError:
        return True  # 401/403/500 still means something is listening
    except Exception:
        return False


def _process_running(name: str) -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        return name.lower() in out.stdout.lower()
    except Exception:
        return False


def is_running(svc: Service) -> bool:
    if svc.health_url and _health_ok(svc.health_url):
        return True
    if svc.process_name:
        return _process_running(svc.process_name)
    return False


def status_all() -> list[dict]:
    return [
        {"name": s.name, "description": s.description, "running": is_running(s)}
        for s in SERVICES.values()
    ]


def start(name: str) -> dict:
    svc = SERVICES.get(name)
    if svc is None:
        raise KeyError(name)
    if is_running(svc):
        return {"name": name, "running": True, "started": False, "note": "already running"}
    exe = Path(svc.start_args[0])
    if exe.is_absolute() and not exe.exists():
        raise FileNotFoundError(f"{exe} does not exist")
    log_dir = Path(__file__).resolve().parent.parent / "data"
    log_dir.mkdir(exist_ok=True)
    log = open(log_dir / f"svc_{svc.name.replace(' ', '_')}.log", "ab")
    subprocess.Popen(
        svc.start_args,
        cwd=svc.cwd,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        stdout=log, stderr=subprocess.STDOUT,
    )
    return {"name": name, "running": False, "started": True,
            "note": "launch requested; poll /api/services until running"}
