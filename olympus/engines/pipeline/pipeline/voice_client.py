"""Voice Studio TTS client with silent-wav fallback."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
import wave
import shutil
from pathlib import Path

from .gpu_lock import gpu_batch

_KOKORO_VOICE_RE = re.compile(r"^[ab][mf]_[a-z0-9_]+$")


def _require_gpu_headroom(min_free_gb: float = 4.5) -> None:
    """Refuse GPU TTS while ComfyUI or another process occupies the card."""
    if not shutil.which("nvidia-smi"):
        return
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return
    free_gb = float(result.stdout.splitlines()[0].strip()) / 1024.0
    if free_gb < min_free_gb:
        raise RuntimeError(
            f"GPU TTS blocked: only {free_gb:.2f} GiB free; stop/unload ComfyUI first"
        )


def _silent_wav(path: Path, seconds: float = 2.0, rate: int = 22050) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = max(1, int(seconds * rate))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return path


def synth(text: str, dest: Path, voice: str = "af_heart", speed: float = 1.0,
          reference: Path | None = None, style: str = "") -> tuple[Path, bool]:
    """Synthesize via Voice Studio (:5050). Returns (path, used_tts).

    Falls back to a duration-scaled silent wav so assembly never blocks.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        from stack.config import cfg

        engine = getattr(cfg.voice, "engine", "kokoro")
        if engine == "qwen3-tts-0.6b":
            command = getattr(cfg.voice, "qwen3_tts_command", "")
            if command:
                try:
                    with gpu_batch(f"tts:{engine}", getattr(cfg.voice, "gpu_lock_timeout_seconds", 900)):
                        _require_gpu_headroom()
                        return _synth_external(command, text, dest, voice, speed, reference, style)
                except Exception:
                    # GPU-backed provider is unavailable (busy/VRAM); degrade to
                    # the CPU Kokoro fallback so a run is never blocked.
                    engine = "kokoro"
            else:
                # Provider is selected, but no isolated command is configured yet.
                # Use Voice Studio rather than silently pretending it ran.
                engine = "kokoro"
        if engine == "kokoro":
            kokoro_command = getattr(cfg.voice, "kokoro_command", "")
            if kokoro_command:
                try:
                    return _synth_external(kokoro_command, text, dest, voice, speed,
                                           reference, style)
                except Exception:
                    pass  # fall through to Voice Studio (kokoro or espeak-ng)
        safe_voice = voice if _KOKORO_VOICE_RE.match(voice) else getattr(cfg.voice, "default_voice", "af_heart")
        url = cfg.voice.url + "/api/tts"
        payload = json.dumps({"text": text[:800], "voice": safe_voice, "speed": speed,
                              "style": style}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
        return dest, True
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        seconds = max(1.0, min(12.0, len(text.split()) / 2.5))
        return _silent_wav(dest, seconds), False


def _synth_external(command: str, text: str, dest: Path, voice: str, speed: float,
                    reference: Path | None, style: str) -> tuple[Path, bool]:
    """Run a configured isolated TTS adapter using a small JSON request file."""
    with tempfile.TemporaryDirectory(prefix="olympus-tts-") as tmp:
        request_path = Path(tmp) / "request.json"
        request_path.write_text(json.dumps({"text": text[:2000], "voice": voice,
                                            "speed": speed, "style": style,
                                            "reference": str(reference) if reference else "",
                                            "output": str(dest)}), encoding="utf-8")
        env = os.environ.copy()
        env["OLYMPUS_TTS_REQUEST"] = str(request_path)
        subprocess.run(command, shell=True, check=True, timeout=300, env=env,
                       capture_output=True, text=True)
    if not dest.exists():
        raise RuntimeError("configured TTS adapter produced no WAV")
    return dest, True


def provider_matrix() -> list[dict[str, object]]:
    """Return the local TTS candidates and their hardware strategy.

    These are capability declarations used by preflight; model downloads are
    intentionally separate so a test cannot silently consume the GPU budget.
    2026-10-26: chatterbox / f5-tts / spark-tts removed from the system —
    kokoro (CPU) and qwen3-tts (CUDA) are the only installed engines.
    """
    return [
        {"id": "kokoro", "expressiveness": "medium", "device": "cpu", "status": "installed"},
        {"id": "qwen3-tts-0.6b", "expressiveness": "very_high", "device": "cuda", "status": "recommended"},
        {"id": "espeak-ng", "expressiveness": "low", "device": "cpu", "status": "fallback"},
    ]


def provider_status() -> dict[str, object]:
    """Return tested provider state without importing optional TTS packages."""
    return {
        "voice_studio": "fallback-tested",
        "kokoro": "isolated-kokoro-webui-venv-cpu",
        "qwen3-tts": "cuda-tested-isolated-venv-2026-10-26",
        "kokoro_env": "/home/amire/Documents/Personal projects/pipeline/tts/kokoro-webui/Kokoro-82M-WebUI/myenv",
        "qwen3_env": "/home/amire/Documents/Personal projects/pipeline/tts/qwen3-venv",
        "recommended": "qwen3-tts-0.6b",
        "recommendation_reason": "winner of the 2026-10-26 five-model shootout; Apache-2.0; ~4.6GB peak VRAM under the GPU lease",
        "gpu_policy": "exclusive lock with ComfyUI; stop/unload ComfyUI before first model load",
    }
