"""Objective video/story quality gates (video_metrics) -- no GPU, no vision
model. The deterministic half of the stage5 quality report."""

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from pipeline.video_metrics import (
    dhash,
    location_diversity,
    repeat_detect,
    segment_align_ratio,
    _similarity,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# --------------------------------------------------------------------------
# dhash
# --------------------------------------------------------------------------
def test_dhash_same_image_is_identical():
    img = Image.new("RGB", (64, 36), (120, 30, 200))
    assert dhash(img) == dhash(img.copy())


def test_dhash_different_images_differ():
    import random
    rng = random.Random(42)
    red = Image.new("L", (64, 36))
    red.putdata([rng.randint(0, 255) for _ in range(64 * 36)])
    rng = random.Random(99)
    blue = Image.new("L", (64, 36))
    blue.putdata([rng.randint(0, 255) for _ in range(64 * 36)])
    assert _similarity(dhash(red.convert("RGB")), dhash(blue.convert("RGB"))) < 0.6


def test_dhash_similar_images_close():
    import random
    rng = random.Random(0)
    base = Image.new("L", (64, 36))
    pixels = [rng.randint(0, 255) for _ in range(64 * 36)]
    base.putdata(pixels)
    nudge = base.copy()
    nudge.putpixel((20, 18), 255)
    assert _similarity(dhash(base.convert("RGB")), dhash(nudge.convert("RGB"))) > 0.9


# --------------------------------------------------------------------------
# segment_align_ratio
# --------------------------------------------------------------------------
def test_align_ratio_perfect():
    assert segment_align_ratio([(10.0, 10.0), (5.0, 5.01)]) == 1.0


def test_align_ratio_mixed():
    assert segment_align_ratio([(10.0, 10.0), (10.0, 8.0), (5.0, 5.0)]) == pytest.approx(2 / 3)


def test_align_ratio_empty():
    assert segment_align_ratio([]) == 0.0


# --------------------------------------------------------------------------
# location_diversity (the "weak world" complaint)
# --------------------------------------------------------------------------
def test_location_diversity_full_movement():
    scenes = [{"location": "loc-a"}, {"location": "loc-b"}, {"location": "loc-c"}]
    assert location_diversity(scenes) == 1.0


def test_location_diversity_single_place():
    scenes = [{"location": "loc-a"} for _ in range(6)]
    assert location_diversity(scenes) == pytest.approx(1 / 6, abs=0.001)


def test_location_diversity_empty():
    assert location_diversity([]) == 0.0


def test_location_diversity_no_location_field():
    assert location_diversity([{"summary": "x"}, {"summary": "y"}]) == 0.0


# --------------------------------------------------------------------------
# repeat_detect -- needs ffmpeg to synthesize videos
# --------------------------------------------------------------------------
@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not available")
def test_repeat_detect_no_loop_is_ok(tmp_path):
    """A continuous non-repeating motion clip must not be flagged. Uses an
    ffmpeg random-noise source so frames at t and t+period are genuinely
    different (testsrc has a regular scrolling pattern that dHash reads as a
    repeat -- not a good 'continuous' fixture)."""
    vid = tmp_path / "continuous.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "nullsrc=s=128x72:d=6:r=10,geq=random(1)*255:128:128",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vid),
    ], capture_output=True, check=True)
    res = repeat_detect(vid, period_s=2.0)
    assert res["verdict"] == "ok", res
    assert res["repeat_events"] == 0


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not available")
def test_repeat_detect_hard_loop_is_flagged(tmp_path):
    """A naive -stream_loop re-showing the same 1s clip must be caught."""
    clip = tmp_path / "one_sec.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=128x72:rate=10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
    ], capture_output=True, check=True)
    looped = tmp_path / "looped.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-stream_loop", "3", "-i", str(clip), "-t", "4",
        "-c:v", "copy", str(looped),
    ], capture_output=True, check=True)
    res = repeat_detect(looped, period_s=1.0)
    assert res["verdict"] == "repeat"
    assert res["repeat_events"] > 0
    assert res["sim_max"] >= 0.85


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not available")
def test_repeat_detect_short_video_is_ok(tmp_path):
    """dur <= period (nothing to loop) is always ok -- and must not probe."""
    vid = tmp_path / "short.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x36:rate=10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vid),
    ], capture_output=True, check=True)
    res = repeat_detect(vid, period_s=5.0)
    assert res["verdict"] == "ok"
    assert res["repeat_events"] == 0
