"""Root config.json loader.

setup.bat imports this (`from olympus.shared.lib.config import load_config`)
to know which Ollama models to pull. Kept deliberately tiny: the kernel itself
uses olympus/olympus.toml (see kernel/config.py); this file only serves the
root-level config.json contract shared with the archived projects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]

_DEFAULTS: dict[str, Any] = {
    "vault_path": "olympus/engines/vault-sample",
    "chat_model": "llama3.1:8b",
    "embed_model": "nomic-embed-text",
    "max_passes": 3,
    "flask_port": 8750,
    "repos": [],
}


def load_config() -> dict[str, Any]:
    cfg = dict(_DEFAULTS)
    path = REPO_ROOT / "config.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    return cfg
