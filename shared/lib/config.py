"""
config.py  --  One place that every script reads its settings from.

How it works:
  1. Start from the DEFAULTS below.
  2. If a file called `config.json` exists at the repo root, overlay its values.
  3. Any environment variable named AISTACK_<KEY> (uppercase) overrides both.

Relative paths (vault_path, task_inbox, task_outbox) are resolved against the
repo root, so the whole thing works no matter which folder you launch it from.

You normally only ever change ONE thing: `vault_path` -> point it at your real
Obsidian vault. Everything else has a safe default.
"""

from __future__ import annotations
import json
import os
from pathlib import Path

# repo root = two levels up from this file (shared/lib/config.py -> repo root)
ROOT = Path(__file__).resolve().parents[2]

DEFAULTS = {
    # --- Ollama (the local model engine) -----------------------------------
    # OpenAI-compatible endpoint (note the /v1). Used by the openai SDK + Instructor.
    "ollama_base_url": "http://localhost:11434/v1",
    # Native endpoint, used for health checks (/api/tags).
    "ollama_native_url": "http://localhost:11434",

    # --- Models -------------------------------------------------------------
    # One chat model is used everywhere to keep downloads/complexity small.
    # Swap by editing config.json and running: ollama pull <model>
    "chat_model": "llama3.1:8b",
    "embed_model": "nomic-embed-text",

    # --- Where your notes live ---------------------------------------------
    # Empty/relative -> resolved under the repo. Set this to your Obsidian vault.
    "vault_path": "vault",
    # Agents ONLY ever write inside this subfolder of the vault. Your own notes
    # are never modified. Safe to delete this folder; it will be regenerated.
    "generated_subdir": "_generated",

    # --- Project 1 task dropbox --------------------------------------------
    "task_inbox": "apps/project1-ops-hub/task-inbox",
    "task_outbox": "apps/project1-ops-hub/task-outbox",
    "task_done": "apps/project1-ops-hub/done",
    "flask_port": 8750,

    # --- Behaviour ----------------------------------------------------------
    "request_timeout": 600,   # seconds; local models can be slow on CPU
    "max_passes": 3,          # looped-reasoning passes (draft -> critique -> revise)

    # --- Optional integrations (off by default) ----------------------------
    "langfuse_enabled": False,
    "repos": [],              # list of local git repo paths for Project 3 digests
}

_RELATIVE_KEYS = ("vault_path", "task_inbox", "task_outbox", "task_done")


def load_config() -> dict:
    cfg = dict(DEFAULTS)

    cfg_file = ROOT / "config.json"
    if cfg_file.exists():
        try:
            user = json.loads(cfg_file.read_text(encoding="utf-8"))
            # ignore blank values so an empty field falls back to the default
            for k, v in user.items():
                if v not in (None, ""):
                    cfg[k] = v
        except Exception as exc:  # noqa: BLE001 - we want to keep running
            print(f"[config] WARNING: could not parse config.json ({exc}). Using defaults.")

    # environment overrides (handy for scheduled tasks / testing)
    for key in list(cfg.keys()):
        env = os.environ.get("AISTACK_" + key.upper())
        if env is not None and env != "":
            cfg[key] = env

    # resolve relative paths against the repo root
    for key in _RELATIVE_KEYS:
        p = Path(str(cfg[key]))
        if not p.is_absolute():
            p = ROOT / p
        cfg[key] = str(p)

    cfg["root"] = str(ROOT)
    return cfg


if __name__ == "__main__":
    # `python shared/lib/config.py` prints the resolved config for debugging.
    import pprint
    pprint.pp(load_config())
