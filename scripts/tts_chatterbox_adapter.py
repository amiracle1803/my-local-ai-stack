#!/usr/bin/env python3
"""Isolated Chatterbox-Turbo adapter for Olympus Voice Studio.

The pipeline passes the request path through ``OLYMPUS_TTS_REQUEST``. Keeping
this adapter outside the stack venv prevents Chatterbox's torch dependencies
from colliding with ComfyUI or the main Python environment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    request_path = Path(os.environ["OLYMPUS_TTS_REQUEST"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    from chatterbox.tts import ChatterboxTTS
    import torchaudio

    model = ChatterboxTTS.from_pretrained(device="cuda")
    kwargs = {}
    reference = request.get("reference")
    if reference and Path(reference).exists():
        kwargs["audio_prompt_path"] = reference
    wav = model.generate(request["text"], **kwargs)
    output = Path(request["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    # PCM16 so the pipeline's wave-module readers accept the file.
    torchaudio.save(str(output), wav.cpu(), model.sr, encoding="PCM_S", bits_per_sample=16)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
