"""comfy_client: resume finished renders, retry transient CUDA OOM (5-hour runs)."""
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline import comfy_client as cc  # noqa: E402


@pytest.fixture(autouse=True)
def no_lock(monkeypatch):
    class NoLock:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(cc, "gpu_batch", NoLock)
    monkeypatch.setattr(cc.time, "sleep", lambda s: None)
    monkeypatch.delenv("OLYMPUS_FORCE_RENDER", raising=False)


def test_existing_panel_is_kept(tmp_path, monkeypatch):
    dest = tmp_path / "p.png"
    dest.write_bytes(b"x" * 20_000)
    monkeypatch.setattr(cc, "_render_panel", lambda *a, **k: pytest.fail("must not re-render"))
    assert cc.render_panel("prompt", dest, 1) == dest


def test_force_render_re_renders(tmp_path, monkeypatch):
    dest = tmp_path / "p.png"
    dest.write_bytes(b"x" * 20_000)
    monkeypatch.setenv("OLYMPUS_FORCE_RENDER", "1")
    calls = []
    monkeypatch.setattr(cc, "_render_panel", lambda *a, **k: calls.append(1) or dest)
    cc.render_panel("prompt", dest, 1)
    assert calls == [1]


def test_tiny_or_missing_file_is_rendered(tmp_path, monkeypatch):
    dest = tmp_path / "p.png"
    dest.write_bytes(b"x" * 100)          # a broken stub, not a real panel
    calls = []
    monkeypatch.setattr(cc, "_render_panel", lambda *a, **k: calls.append(1) or dest)
    cc.render_panel("prompt", dest, 1)
    assert calls == [1]


def test_oom_is_retried_after_freeing_gpu(tmp_path, monkeypatch):
    dest = tmp_path / "p.png"
    attempts, freed = [], []

    def flaky(*a, **k):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError('{"exception_type": "torch.OutOfMemoryError"}')
        return dest
    monkeypatch.setattr(cc, "_render_panel", flaky)
    monkeypatch.setattr(cc, "_request", lambda url, payload=None: freed.append(url) or {})
    assert cc.render_panel("prompt", dest, 1) == dest
    assert len(attempts) == 3 and all(u.endswith("/free") for u in freed) and len(freed) == 2


def test_oom_gives_up_after_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "_render_panel", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("CUDA out of memory")))
    monkeypatch.setattr(cc, "_request", lambda url, payload=None: {})
    with pytest.raises(RuntimeError):
        cc.render_panel("prompt", tmp_path / "p.png", 1)


def test_other_errors_are_not_retried(tmp_path, monkeypatch):
    attempts = []
    def broken(*a, **k):
        attempts.append(1)
        raise RuntimeError("missing node type: LTXDirector")
    monkeypatch.setattr(cc, "_render_panel", broken)
    with pytest.raises(RuntimeError):
        cc.render_panel("prompt", tmp_path / "p.png", 1)
    assert attempts == [1]


def test_existing_clip_is_kept(tmp_path, monkeypatch):
    dest = tmp_path / "c.mp4"
    dest.write_bytes(b"x" * 50_000)
    monkeypatch.setattr(cc, "_animate_panel", lambda *a, **k: pytest.fail("must not re-animate"))
    assert cc.animate_panel(tmp_path / "p.png", dest, 1) == dest
