"""
state.py  --  Remember what we've already processed, so nightly/hourly jobs
              don't redo work or create duplicates.

State is stored as small JSON files under <vault>/_generated/.state/.
Each subsystem uses its own namespace, e.g.:
    load_state("second_brain")   # processed note hashes, extracted item ids
    load_state("research")       # seen RSS entry ids
    load_state("repos")          # last-seen commit per repo

There is also a simple file lock so two runs can't stomp on each other.
"""

from __future__ import annotations
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .notes import generated_dir


def _state_dir() -> Path:
    p = generated_dir() / ".state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_state(namespace: str) -> dict:
    fp = _state_dir() / f"{namespace}.json"
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - corrupt state shouldn't crash a job
            print(f"[state] {namespace}.json unreadable; starting fresh.")
    return {}


def save_state(namespace: str, data: dict) -> None:
    fp = _state_dir() / f"{namespace}.json"
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(fp)  # atomic on the same filesystem -> no half-written state


@contextmanager
def lock(namespace: str, stale_seconds: int = 3600):
    """
    Prevent overlapping runs. If a lock is older than `stale_seconds` it is
    assumed dead (e.g. the PC was force-rebooted mid-run) and reclaimed.

    Usage:
        with lock("second_brain"):
            ... do work ...
    """
    lock_path = _state_dir() / f"{namespace}.lock"
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age < stale_seconds:
            raise RuntimeError(
                f"'{namespace}' is already running (lock is {int(age)}s old). "
                f"If that's wrong, delete: {lock_path}"
            )
        print(f"[state] stale lock for '{namespace}' ({int(age)}s) -> reclaiming.")

    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass
