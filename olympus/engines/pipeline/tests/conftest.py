"""Shared test isolation: the suite must never wait on a real Steam game running on this machine."""

import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))


@pytest.fixture(autouse=True)
def _isolated_gaming_flag(tmp_path, monkeypatch):
    from pipeline import game_mode

    monkeypatch.setattr(game_mode, "FLAG", tmp_path / "gaming.json")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """No network in tests: the director LLM pass and cloud image providers are off unless a
    test turns them on (director tests inject a fake llm)."""
    monkeypatch.setenv("OLYMPUS_DIRECTOR", "0")
    monkeypatch.setenv("OLYMPUS_CLOUD_IMAGES", "0")
