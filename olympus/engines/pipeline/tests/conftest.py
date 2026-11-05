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
