#!/usr/bin/env python3
"""Isolated Kokoro-82M adapter for the Olympus pipeline.

Sibling of scripts/tts_chatterbox_adapter.py. Runs inside the user's existing
Kokoro WebUI venv ("spech webui copy/Kokoro-82M-WebUI/myenv") so it sidesteps
the Voice Studio kokoro ABI breakage (transformers/torchvision mismatch in the
shared env) that was silently degrading all TTS to espeak-ng.

The pipeline passes the request path through ``OLYMPUS_TTS_REQUEST``
({"text", "voice", "speed", "style", "reference", "output"}).
CPU is forced: Kokoro-82M is fast enough on CPU and this keeps the RTX 4070
free for ComfyUI/LTX without a GPU-lock handshake.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    request_path = Path(os.environ["OLYMPUS_TTS_REQUEST"])
    request = json.loads(request_path.read_text(encoding="utf-8"))

    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")  # CPU on purpose, see docstring
    os.environ.setdefault("HF_HUB_OFFLINE", "1")       # weights already cached locally

    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code="a", device="cpu", repo_id="hexgrad/Kokoro-82M")
    voice = request.get("voice") or "af_heart"
    speed = float(request.get("speed") or 0.88)  # 0.88 = the WebUI default pacing
    chunks = [audio for _, _, audio in pipeline(request["text"], voice=voice, speed=speed)]
    if not chunks:
        raise RuntimeError("kokoro produced no audio")
    audio = np.concatenate(chunks)

    output = Path(request["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    # PCM16 so the pipeline's wave-module readers accept the file.
    sf.write(str(output), audio, 24000, subtype="PCM_16")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
