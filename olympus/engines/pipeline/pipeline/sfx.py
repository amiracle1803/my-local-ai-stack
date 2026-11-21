"""Procedural sound effects (numpy + stdlib wave): 44.1 kHz mono 16-bit PCM."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
PEAK_DB = -3.0


def _t(dur: float) -> np.ndarray:
    return np.arange(int(round(dur * SR))) / SR


def _lowpass(x: np.ndarray, cutoff: np.ndarray | float) -> np.ndarray:
    """One-pole low-pass with per-sample cutoff (Hz)."""
    cut = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = 1.0 - np.exp(-2 * np.pi * cut / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def _highpass_simple(x: np.ndarray, cutoff: float) -> np.ndarray:
    return x - _lowpass(x, cutoff)


def _finish(x: np.ndarray, dest: Path, fade: float = 0.004, fade_out: float = 0.02) -> Path:
    """Fade edges, peak-normalize to -3 dBFS, write WAV."""
    x = np.asarray(x, dtype=float).copy()
    n = len(x)
    fi, fo = min(n // 2, int(fade * SR)), min(n // 2, int(fade_out * SR))
    if fi:
        x[:fi] *= np.linspace(0, 1, fi)
    if fo:
        x[-fo:] *= np.linspace(1, 0, fo)
    peak = float(np.max(np.abs(x))) or 1.0
    x *= 10 ** (PEAK_DB / 20) / peak
    pcm = np.round(x * 32767).astype("<i2")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return dest


def whoosh(dest: Path, dur: float = 0.45) -> Path:
    """Airy swoosh: noise through a low-pass sweeping up then down."""
    t = _t(dur)
    u = t / dur
    noise = np.random.default_rng(1).standard_normal(len(t))
    cutoff = 300 + 5200 * np.sin(np.pi * u) ** 1.5
    y = _lowpass(_lowpass(noise, cutoff), cutoff)
    y = _highpass_simple(y, 150)
    env = np.sin(np.pi * u) ** 2 * (0.4 + 0.6 * u)
    return _finish(y * env, dest, fade=0.01)


def impact(dest: Path, dur: float = 0.9) -> Path:
    """Cinematic hit: pitch-dropping sine boom plus bright transient, soft-clipped."""
    t = _t(dur)
    freq = 35 + 35 * np.exp(-t / 0.12)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    boom = np.sin(phase) * np.exp(-t / 0.28)
    rng = np.random.default_rng(2)
    noise = rng.standard_normal(len(t))
    click = _highpass_simple(noise, 2000) * np.exp(-t / 0.02) * 0.6
    body = _lowpass(noise, 400) * np.exp(-t / 0.08) * 0.5
    y = np.tanh(2.2 * (boom + click + body))
    return _finish(y, dest, fade=0.0005, fade_out=0.05)


def chime(dest: Path, dur: float = 1.1) -> Path:
    """Game notification: two bright bell notes with harmonics and slight shimmer."""
    t = _t(dur)
    y = np.zeros_like(t)
    for f0, start, amp in ((1318.5, 0.0, 0.8), (1760.0, 0.09, 1.0)):
        tt = np.clip(t - start, 0, None)
        env = (1 - np.exp(-tt / 0.002)) * np.exp(-tt / 0.28) * (t >= start)
        note = np.zeros_like(t)
        for k, hamp in enumerate((1.0, 0.45, 0.25, 0.12), start=1):
            for det in (0.0, 0.0025):
                note += hamp * np.sin(2 * np.pi * f0 * k * (1 + det) * tt + k)
        shimmer = 1 + 0.08 * np.sin(2 * np.pi * 6 * tt)
        y += amp * amp_scale(note) * env * shimmer
    return _finish(y, dest, fade=0.001, fade_out=0.08)


def amp_scale(x: np.ndarray) -> np.ndarray:
    return x / 2.0


def riser(dest: Path, dur: float = 1.4) -> Path:
    """Tension riser: noise + rising sine sweep, crescendo, hard cut at the end."""
    t = _t(dur)
    u = t / dur
    freq = 200 + 1000 * u ** 2
    sweep = np.sin(2 * np.pi * np.cumsum(freq) / SR)
    noise = np.random.default_rng(3).standard_normal(len(t))
    noise = _lowpass(noise, 800 + 6000 * u)
    y = (0.6 * sweep + 0.5 * noise / (np.max(np.abs(noise)) or 1)) * u ** 2.2
    return _finish(y, dest, fade=0.01, fade_out=0.008)


def ensure_library(directory: Path) -> dict[str, Path]:
    """Create the four standard SFX in `directory` if missing; return name -> path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    makers = {"whoosh": whoosh, "impact": impact, "chime": chime, "riser": riser}
    out: dict[str, Path] = {}
    for name, fn in makers.items():
        p = directory / f"{name}.wav"
        if not p.exists():
            fn(p)
        out[name] = p
    return out
