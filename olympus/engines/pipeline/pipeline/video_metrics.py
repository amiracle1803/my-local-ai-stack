"""Deterministic video/story quality gates (stage5 closing metrics).

Complements the VLM review (subjective) with cheap, objective, fully
testable checks that do not need a GPU or a vision model:

- :func:`repeat_detect` -- catches the "same scene repeated 3x" artifact that
  a naive ``-stream_loop`` produced: near-duplicate frame pairs separated by
  exactly one clip period. A ping-pong loop (forward+reverse) defeats this
  because the frame at ``t`` and the frame at ``t+period`` are reversed, not
  identical.
- :func:`segment_align_ratio` -- the fraction of shot segments whose video
  stream duration matches their audio stream within a tolerance (the
  audio/visual alignment metric, deterministic form of av_sync).
- :func:`location_diversity` -- distinct locations used across scenes divided
  by total scenes (a 1.0 floor means every scene moves somewhere new; a value
  near 0 means the whole video happens in one place -> the "weak world"
  complaint).

All functions are pure or ffmpeg-only (no torch, no Ollama) so they run in
unit tests and on a freshly assembled video alike.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_FFMPEG = "ffmpeg"
_REPEAT_SAMPLE_STEP_S = 0.5
_REPEAT_SIM_THRESHOLD = 0.85  # fraction of 64 hash bits agreeing = near-duplicate
_ALIGN_TOLERANCE_S = 0.05


# --------------------------------------------------------------------------
# frame extraction + perceptual hash (no GPU)
# --------------------------------------------------------------------------
def _extract_frame(video_path: Path, t: float) -> Image.Image | None:
    """Extract the frame at time ``t`` (seconds) as a PIL RGB image."""
    with tempfile.TemporaryDirectory(prefix="vmetrics_") as tmp:
        out = Path(tmp) / "frame.jpg"
        cmd = [
            _FFMPEG, "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(video_path),
            "-frames:v", "1", "-q:v", "2", str(out),
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        if not out.exists():
            return None
        try:
            return Image.open(out).convert("RGB")
        except OSError:
            return None


def dhash(img: Image.Image) -> int:
    """64-bit perceptual hash: 9x8 grayscale, row-pair difference bits."""
    gray = ImageOps.grayscale(img).resize((9, 8), Image.LANCZOS)
    pixels = list(gray.tobytes())  # 72 bytes, row-major (avoids deprecated getdata)
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if pixels[row * 9 + col] > pixels[row * 9 + col + 1] else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _similarity(a: int, b: int) -> float:
    return 1.0 - (_hamming(a, b) / 64.0)


# --------------------------------------------------------------------------
# repeat detection (the P0 artifact)
# --------------------------------------------------------------------------
def repeat_detect(
    video_path: Path,
    period_s: float,
    *,
    dur_s: float | None = None,
    sample_step_s: float = _REPEAT_SAMPLE_STEP_S,
    threshold: float = _REPEAT_SIM_THRESHOLD,
) -> dict[str, Any]:
    """Count near-duplicate frame pairs separated by exactly ``period_s``.

    A hard-cut ``-stream_loop`` re-shows identical clip frames one period
    apart -> very high similarity. A ping-pong (forward+reverse) loop shows
    the *reversed* content one period apart -> low similarity, so the check
    is a regression guard for the naive loop, not a false-positive on motion.

    Returns:
        ``{"repeat_events", "sim_max", "sim_mean", "frames_sampled",
        "period_s", "verdict"}``. ``verdict`` is ``"ok"`` when no pair crossed
        the threshold, ``"repeat"`` when one or more did, and ``"inconclusive"``
        when frames could not be extracted.
    """
    if period_s <= 0:
        return _repeat_result(0, 0.0, 0.0, 0, period_s, "inconclusive")
    if dur_s is None:
        dur_s = _probe_duration(video_path)
    if dur_s is None or dur_s <= period_s * 1.2:
        # no room for a full loop; nothing to catch
        return _repeat_result(0, 0.0, 0.0, 0, period_s, "ok")

    times = [i * sample_step_s for i in range(int(dur_s / sample_step_s) + 1)]
    frames: dict[float, int] = {}
    for t in times:
        img = _extract_frame(video_path, t)
        if img is None:
            continue
        frames[t] = dhash(img)

    # Exact ``frames.get(round(t + period_s, 3))`` never matched because the
    # sample grid (sample_step_s) does not generally land on ``period_s``
    # (e.g. 0.5 s grid vs 5.0625 s clip) -- zero pairs were ever compared and
    # ``frames_sampled`` always read 0. Look up the nearest sampled frame to
    # ``t + period_s`` within half a sample step instead.
    step = max(sample_step_s, 1e-3)
    sorted_t = sorted(frames)

    def _nearest(target: float) -> int | None:
        lo, hi = 0, len(sorted_t) - 1
        if target <= sorted_t[0]:
            return sorted_t[0]
        if target >= sorted_t[-1]:
            return sorted_t[-1]
        while lo <= hi:
            mid = (lo + hi) // 2
            if sorted_t[mid] < target:
                lo = mid + 1
            else:
                hi = mid - 1
        cands = [sorted_t[max(0, hi)], sorted_t[min(len(sorted_t) - 1, lo)]]
        return min(cands, key=lambda x: abs(x - target))

    sims: list[float] = []
    events = 0
    for t in sorted_t:
        if t + period_s > dur_s:
            break
        near = _nearest(t + period_s)
        if near is None or abs(near - (t + period_s)) > step / 2:
            continue
        sim = _similarity(frames[t], frames[near])
        sims.append(sim)
        if sim >= threshold:
            events += 1

    sim_max = max(sims) if sims else 0.0
    sim_mean = sum(sims) / len(sims) if sims else 0.0
    verdict = "ok" if not sims else ("repeat" if events else "ok")
    return _repeat_result(events, sim_max, sim_mean, len(sims), period_s, verdict)


def _repeat_result(
    events: int, sim_max: float, sim_mean: float, sampled: int,
    period_s: float, verdict: str,
) -> dict[str, Any]:
    return {
        "repeat_events": events, "sim_max": round(sim_max, 3),
        "sim_mean": round(sim_mean, 3), "frames_sampled": sampled,
        "period_s": round(period_s, 3), "verdict": verdict,
    }


def _probe_duration(path: Path) -> float | None:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20, check=True)
        return float(out.stdout.decode().strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None


def _probe_video_frames(path: Path) -> int | None:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=nb_read_frames",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        return int(out.stdout.decode().strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None


# --------------------------------------------------------------------------
# audio / visual alignment ratio (deterministic av_sync)
# --------------------------------------------------------------------------
def segment_align_ratio(
    durations: list[tuple[float, float]],
    tolerance_s: float = _ALIGN_TOLERANCE_S,
) -> float:
    """Fraction of (video_dur, audio_dur) segment pairs within ``tolerance_s``.

    ``1.0`` = every segment's picture lasts exactly as long as its sound.
    Used as the deterministic form of the mandatory ``av_sync_error_ms``
    metric -- measured per segment instead of once on the final file.
    """
    if not durations:
        return 0.0
    aligned = sum(1 for v, a in durations if abs(v - a) <= tolerance_s)
    return aligned / len(durations)


# --------------------------------------------------------------------------
# world/location diversity (the "weak world" complaint)
# --------------------------------------------------------------------------
def location_diversity(scenes: list[dict[str, Any]]) -> float:
    """Distinct locations across scenes / total scenes. 1.0 = every scene
    moves somewhere new; ~0.0 = the whole story happens in one place."""
    total = len(scenes)
    if not total:
        return 0.0
    distinct = len({s.get("location") for s in scenes if s.get("location")})
    if distinct == 0:
        return 0.0
    return round(distinct / total, 3)
