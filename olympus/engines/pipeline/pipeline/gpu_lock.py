"""Process-level mutex for GPU workloads shared by ComfyUI and TTS.

On an 8 GB card Ollama and ComfyUI must never hold VRAM at once. Beyond the
filesystem mutex, acquiring the batch actively unloads resident Ollama
models, and releasing it asks ComfyUI to free its cache, so one tenant never
silently starves the other.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path


LOCK_PATH = Path(os.environ.get("OLYMPUS_GPU_LOCK", "/tmp/olympus-gpu.lock"))
OLLAMA_URL = os.environ.get("OLYMPUS_OLLAMA_URL", "http://127.0.0.1:11434")
COMFYUI_URL = os.environ.get("OLYMPUS_COMFYUI_URL", "http://127.0.0.1:8188")


def _post(url: str, payload: dict, timeout: float = 30) -> None:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=timeout).read()


def unload_ollama(ollama_url: str = OLLAMA_URL) -> None:
    """Unload every resident Ollama model so the card is free for ComfyUI.

    Tolerant: if Ollama is offline there is simply nothing to unload."""
    try:
        with urllib.request.urlopen(f"{ollama_url}/api/ps", timeout=5) as response:
            models = [m["name"] for m in json.loads(response.read()).get("models", [])]
    except (OSError, ValueError):
        return
    for name in models:
        try:
            _post(f"{ollama_url}/api/generate", {"model": name, "keep_alive": 0})
        except (OSError, ValueError):
            pass


def free_comfyui(comfy_url: str = COMFYUI_URL) -> None:
    """Ask ComfyUI to unload models and free cached VRAM. Tolerant to downtime."""
    try:
        _post(f"{comfy_url}/free", {"unload_models": True, "free_memory": True})
    except (OSError, ValueError):
        pass


@contextmanager
def gpu_batch(owner: str, timeout: float = 900):
    """Hold an exclusive GPU batch: lease -> unload Ollama -> work -> free VRAM -> release."""
    import fcntl

    from . import game_mode
    game_mode.wait_clear()  # a Steam game owns the GPU: wait for it to end (W.A.T. gaming_guard)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"GPU lock timeout while waiting for {owner}")
                time.sleep(0.25)
        handle.seek(0)
        handle.truncate()
        handle.write(owner)
        handle.flush()
        unload_ollama()
        try:
            yield
        finally:
            free_comfyui()
            handle.seek(0)
            handle.truncate()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
