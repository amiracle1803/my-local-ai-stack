"""Load and expose olympus.toml.

The kernel is started with cwd=olympus/ (see start.bat / run.bat), but we
resolve paths relative to this file so imports work from the repo root too.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

OLYMPUS_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = OLYMPUS_ROOT / "olympus.toml"
AGENTS_DIR = OLYMPUS_ROOT / "agents"
DATA_DIR = OLYMPUS_ROOT / "data"
WEB_DIR = OLYMPUS_ROOT / "web"

_cache: dict[str, Any] | None = None


def load_config(force: bool = False) -> dict[str, Any]:
    global _cache
    if _cache is None or force:
        with open(CONFIG_PATH, "rb") as f:
            _cache = tomllib.load(f)
        DATA_DIR.mkdir(exist_ok=True)
    return _cache


def resolve_model(role: str) -> str:
    """Map a model role (worker, planner, ...) to a concrete Ollama model.

    Unknown roles fall back to 'worker' so a typo in an agent file degrades
    gracefully instead of 404ing against Ollama.
    """
    models = load_config()["models"]
    return models.get(role) or models["worker"]
