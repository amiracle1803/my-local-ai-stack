"""Game mode (W.A.T. tools/gaming_guard on the Legion): while a Steam game runs, the GPU is the
game's. The guard stops ComfyUI and keeps Ollama off the card; pipeline GPU work waits here and
resumes on its own when the game ends.

The flag (~/.cache/wat/gaming.json) carries a heartbeat. A flag from a guard that stopped beating
is ignored, so a dead guard can never stall the pipeline forever.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

FLAG = Path(os.environ.get("WAT_GAMING_FLAG", Path.home() / ".cache" / "wat" / "gaming.json"))
MAX_SILENCE = 120.0


def _read(flag: Path | None = None) -> dict:
    try:
        return json.loads(Path(flag or FLAG).read_text())
    except (OSError, ValueError):
        return {}


def active(flag: Path | None = None) -> bool:
    d = _read(flag)
    return bool(d.get("active")) and time.time() - float(d.get("heartbeat") or 0) < MAX_SILENCE


def happened_since(t: float, flag: Path | None = None) -> bool:
    """A game is on now, or one ended after `t` (a job that started before it was cut off)."""
    d = _read(flag)
    return active(flag) or float(d.get("ended") or 0) > t


def comfy_up(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/system_stats", timeout=5):
            return True
    except Exception:  # noqa: BLE001
        return False


def wait_clear(base_url: str | None = None, poll: float = 15.0, up_timeout: float = 300.0,
               flag: Path | None = None, sleep=time.sleep, log=print) -> None:
    """Block while a game runs; then (if given) until ComfyUI answers again."""
    if active(flag):
        log("game mode: waiting for the game to end before using the GPU", flush=True)
        while active(flag):
            sleep(poll)
    if base_url:
        waited = 0.0
        while not comfy_up(base_url) and waited < up_timeout:
            sleep(5)
            waited += 5
