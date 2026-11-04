#!/usr/bin/env python3
"""Isolated Qwen3-TTS adapter for Olympus Voice Studio.

The pipeline passes the request path through ``OLYMPUS_TTS_REQUEST`` (same
contract as tts_chatterbox_adapter.py). Keeping this adapter outside the
stack venv prevents Qwen3-TTS's torch dependencies from colliding with
ComfyUI or the main Python environment.

Model default is the 1.7B-CustomVoice — the winner of the 2026-10-26 local
shootout (see ~/Videos/tts-shootout/). Override with OLYMPUS_QWEN3_TTS_MODEL.
Voice ids map to Qwen premium speakers; anything else (kokoro-style ids like
af_heart, character names) falls back to the narrator voice from the test.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# kokoro-style / arbitrary ids -> Qwen premium speakers (CustomVoice set)
_SPEAKERS = {
    "aiden": "Aiden", "ryan": "Ryan", "vivian": "Vivian", "serena": "Serena",
    "uncle_fu": "Uncle_Fu", "dylan": "Dylan", "eric": "Eric",
    "ono_anna": "Ono_Anna", "sohee": "Sohee",
}
_DEFAULT_INSTRUCT = "Calm, tense narration, like a somber movie voice-over."


def main() -> int:
    request_path = Path(os.environ["OLYMPUS_TTS_REQUEST"])
    request = json.loads(request_path.read_text(encoding="utf-8"))

    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    model_name = os.environ.get("OLYMPUS_QWEN3_TTS_MODEL",
                                "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
    speaker = _SPEAKERS.get(str(request.get("voice", "")).strip().lower(), "Aiden")

    # Per-character VoiceSpec styles override the narration default; a
    # non-1.0 speed nudges delivery through the instruct (Qwen has no
    # direct speed parameter).
    instruct = str(request.get("style") or "").strip() or _DEFAULT_INSTRUCT
    speed = float(request.get("speed") or 1.0)
    if abs(speed - 1.0) > 0.05:
        instruct += " Speak noticeably slower." if speed < 1.0 else " Speak briskly."

    model = Qwen3TTSModel.from_pretrained(model_name, device_map="cuda:0",
                                           dtype=torch.bfloat16)
    wavs, sr = model.generate_custom_voice(
        text=request["text"][:2000], language="English",
        speaker=speaker, instruct=instruct)

    wav = np.asarray(wavs[0])
    peak = float(np.max(np.abs(wav)))
    if peak > 0:
        wav = wav / peak * 0.95  # peak-normalize; stage5 mixes at unity

    output = Path(request["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), wav, sr, subtype="PCM_16")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
