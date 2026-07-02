"""
Shared fixtures for Agent Atlas tests.
Sets up an isolated in-memory SQLite DB and a minimal config so tests
run without Hermes / Claude / Perplexity being online.
"""
import os
import sys
from pathlib import Path

import pytest

# Make sure the backend package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

# Point to a temporary SQLite so tests never touch the real DB
@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_atlas.sqlite"
    import app.storage.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    db_mod.init_db()
    yield


@pytest.fixture(autouse=True)
def load_test_config(tmp_path, monkeypatch):
    """Write a minimal models.yml + one agent YAML into tmp_path and load it."""
    import yaml, app.config.loader as cfg_mod

    config_dir = tmp_path / "config"
    agents_dir = config_dir / "agents"
    agents_dir.mkdir(parents=True)

    models_yml = {
        "models": {
            "hermes_local": {
                "provider": "local",
                "endpoint": "http://localhost:11434/v1/chat/completions",
                "model": "hermes-2",
                "capabilities": ["general", "private"],
                "max_tokens": 512,
                "temperature": 0.7,
            }
        },
        "routing": {
            "allow_remote_models": False,
            "allow_remote_search": False,
            "default_model": "hermes_local",
            "privacy_first": True,
        },
    }
    (config_dir / "models.yml").write_text(yaml.dump(models_yml))

    orchestrator_yml = {
        "id": "orchestrator",
        "display_name": "Executive Orchestrator",
        "layer": "control",
        "description": "Test orchestrator",
        "model_preference": ["hermes_local"],
        "system_prompt": "You are the orchestrator.",
    }
    (agents_dir / "orchestrator.yml").write_text(yaml.dump(orchestrator_yml))

    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    cfg_mod.ConfigLoader._models = {}
    cfg_mod.ConfigLoader._agents = {}
    cfg_mod.ConfigLoader._loaded = False
    cfg_mod.ConfigLoader.load()
    yield
