"""Pipeline GPU work waits out a Steam game and redoes a render the game cut off."""

import json
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline import comfy_client, game_mode  # noqa: E402


def _flag(tmp_path, monkeypatch, **d):
    f = tmp_path / "gaming.json"
    f.write_text(json.dumps(d))
    monkeypatch.setattr(game_mode, "FLAG", f)
    return f


def test_active_needs_a_fresh_heartbeat(tmp_path, monkeypatch):
    _flag(tmp_path, monkeypatch, active=True, heartbeat=time.time())
    assert game_mode.active()
    _flag(tmp_path, monkeypatch, active=True, heartbeat=time.time() - 600)
    assert not game_mode.active()  # dead guard: fail open
    _flag(tmp_path, monkeypatch, active=False, ended=time.time())
    assert game_mode.happened_since(time.time() - 5) and not game_mode.happened_since(time.time() + 5)


def test_wait_clear_blocks_until_game_ends(tmp_path, monkeypatch):
    f = _flag(tmp_path, monkeypatch, active=True, heartbeat=time.time())
    ticks = []

    def sleep(s):
        ticks.append(s)
        if len(ticks) == 3:
            f.write_text(json.dumps({"active": False, "ended": time.time()}))
    game_mode.wait_clear(sleep=sleep, log=lambda *a, **k: None)
    assert len(ticks) == 3


def test_render_cut_off_by_a_game_is_redone(tmp_path, monkeypatch):
    f = _flag(tmp_path, monkeypatch, active=False)
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:  # the guard stopped ComfyUI mid-render
            f.write_text(json.dumps({"active": False, "ended": time.time() + 1}))
            raise ConnectionRefusedError("comfy down")
        return "panel.png"
    monkeypatch.setattr(game_mode, "wait_clear", lambda *a, **k: None)
    assert comfy_client._with_oom_retry(fn, "http://x") == "panel.png" and len(calls) == 2


def test_unrelated_errors_still_raise(tmp_path, monkeypatch):
    _flag(tmp_path, monkeypatch, active=False)
    import pytest

    def fn():
        raise ValueError("bad graph")
    with pytest.raises(ValueError):
        comfy_client._with_oom_retry(fn, "http://x")
