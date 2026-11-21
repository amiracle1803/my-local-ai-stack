"""Overlay (fx) and sound-effect (sfx) generators."""

import math
import sys
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline import fx, sfx  # noqa: E402

W, H = 640, 360


def _check_rgba(p: Path, size=(W, H)):
    im = Image.open(p)
    assert im.mode == "RGBA" and im.size == size
    a = np.asarray(im)[..., 3]
    assert (a == 255).any() or (a > 100).any()
    assert (a == 0).any()


def test_system_window(tmp_path):
    p = fx.system_window("[Quest Complete] The Heart Flame has been found. Reward: +500 EXP",
                         tmp_path / "s.png", W, H)
    _check_rgba(p)
    _check_rgba(fx.system_window("word " * 400, tmp_path / "s2.png", W, H))


def test_caption(tmp_path):
    _check_rgba(fx.caption("He never saw it coming", tmp_path / "c.png", W, H))
    _check_rgba(fx.caption("x", tmp_path / "c1.png", W, H, position="upper"))
    _check_rgba(fx.caption("loooong " * 200 + "A" * 500, tmp_path / "c2.png", W, H))


def test_speed_lines(tmp_path):
    a = fx.speed_lines(tmp_path / "a.png", W, H, seed=1)
    b = fx.speed_lines(tmp_path / "b.png", W, H, seed=1)
    _check_rgba(a)
    assert a.read_bytes() == b.read_bytes()
    arr = np.asarray(Image.open(a))[..., 3]
    assert arr[H // 2, W // 2] == 0


def test_thumbnail(tmp_path):
    src = tmp_path / "src.png"
    Image.new("RGB", (900, 900), (40, 90, 160)).save(src)
    p = fx.thumbnail(src, "The last lantern went out", tmp_path / "t.png", episode=12)
    assert Image.open(p).size == (1280, 720)
    p2 = fx.thumbnail(src, "Supercalifragilisticexpialidocious " * 5, tmp_path / "t2.png")
    assert Image.open(p2).size == (1280, 720)


@pytest.mark.parametrize("name,fn,dur", [
    ("whoosh", sfx.whoosh, 0.45), ("impact", sfx.impact, 0.9),
    ("chime", sfx.chime, 1.1), ("riser", sfx.riser, 1.4),
])
def test_sfx(tmp_path, name, fn, dur):
    p = fn(tmp_path / f"{name}.wav")
    with wave.open(str(p)) as w:
        assert w.getframerate() == 44100 and w.getnchannels() == 1 and w.getsampwidth() == 2
        assert abs(w.getnframes() / 44100 - dur) <= 0.02
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    db = 20 * math.log10(np.abs(pcm).max() / 32768)
    assert -4 <= db <= -2


def test_ensure_library(tmp_path):
    lib = sfx.ensure_library(tmp_path / "sfx")
    assert set(lib) == {"whoosh", "impact", "chime", "riser"}
    assert all(p.exists() for p in lib.values())
    before = {k: p.stat().st_mtime_ns for k, p in lib.items()}
    lib2 = sfx.ensure_library(tmp_path / "sfx")
    assert before == {k: p.stat().st_mtime_ns for k, p in lib2.items()}
