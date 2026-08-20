#!/usr/bin/env python3
"""LTX Director lab smoke gate: queue ONE LTXDirector (V2V director) render
through ComfyClient and report wall time + output path. Run this before letting
the director template take over stage3c. Mirrors the aether-pipeline-v2 STAGE 3
V2V Director (LTX Director 2.0) timeline format.

Usage:  python tools/ltx_director_smoke.py [--template ltx_director_23.json] [--panel <png>]
Exit codes: 0 on success, 2 on ComfyError/ContingencyStop.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.comfy_client import ComfyClient, ComfyError, ContingencyStop  # noqa: E402
from pipeline.config import PipelineConfig  # noqa: E402

_FRAMES = 33
_FPS = 24
_STEPS = 8
_CFG = 1.0
_WIDTH, _HEIGHT = 576, 320
_PROMPT = "anime scene, the character turns their head and breathes, hair and clothes swaying with soft wind physics, slow push-in, cinematic lighting"
_DEST = Path("/tmp/ltx-director-smoke")


def build_timeline(image_file: str, prompt: str, frames: int) -> dict:
    """Build the LTXDirector timeline_data/local_prompts/segment_lengths dict,
    mirroring the aether-pipeline-v2 STAGE 3 timeline format: an empty head
    text segment, an image start keyframe, a text motion beat, and an empty
    tail. Returns a dict with keys timeline_data, local_prompts,
    segment_lengths, guide_strength."""
    segments = [
        {"id": "s_head", "start": 0, "length": 0, "type": "text", "prompt": "", "isEndFrame": False},
        {"id": "s_img", "start": 0, "length": frames, "type": "image",
         "imageFile": image_file, "isEndFrame": False},
        {"id": "s_txt", "start": 0, "length": frames, "type": "text", "prompt": prompt, "isEndFrame": False},
        {"id": "s_tail", "start": frames, "length": 0, "type": "text", "prompt": "", "isEndFrame": False},
    ]
    timeline = {
        "mainTrackEnabled": True,
        "audioTrackEnabled": False,
        "motionTrackEnabled": False,
        "global_prompt": "anime 2d illustration, cel shading, consistent character and background",
        "normalStartFrame": 0,
        "normalDurationFrames": frames,
        "segments": segments,
        "motionSegments": [],
        "audioSegments": [],
    }
    return {
        "timeline_data": json.dumps(timeline),
        "local_prompts": f" | {prompt}\n | ",
        "segment_lengths": f"0,{frames},0",
        "guide_strength": "1.0",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="ltx_director_23.json")
    ap.add_argument("--panel", default=None, help="Path to a source panel PNG.")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    config = PipelineConfig.load()
    comfy = ComfyClient(config)
    if not comfy.healthy():
        print("ComfyUI is not reachable - start it first.")
        return 2
    comfy.unload_ollama()

    test_panel = Path(args.panel) if args.panel else _DEST / "test_panel.png"
    if not test_panel.exists():
        # Fallback: render a tiny start frame via the flux fallback template
        _DEST.mkdir(parents=True, exist_ok=True)
        try:
            paths = comfy.generate(
                "image_txt2img_flux_fallback.json",
                {
                    "PROMPT_POS": "anime character at a shrine, simple background, test frame",
                    "WIDTH": _WIDTH, "HEIGHT": _HEIGHT,
                    "SEED": args.seed,
                    "SAVE_PREFIX": "pipeline/ltx_director_smoke/test_panel",
                },
                dest=_DEST,
            )
            test_panel = paths[0]
            print(f"Generated test panel: {test_panel}")
        except (ComfyError, ContingencyStop) as exc:
            print(f"Failed to generate test panel: {exc}")
            return 2

    uploaded = comfy.upload_image(test_panel, name="ltx_director_smoke_start.png")
    t = build_timeline(uploaded, _PROMPT, _FRAMES)

    start = time.monotonic()
    try:
        paths = comfy.generate(
            args.template,
            {
                "TIMELINE_DATA": t["timeline_data"],
                "LOCAL_PROMPTS": t["local_prompts"],
                "SEGMENT_LENGTHS": t["segment_lengths"],
                "GUIDE_STRENGTH": t["guide_strength"],
                "GLOBAL_PROMPT": "anime 2d illustration, cel shading, consistent character and background",
                "WIDTH": _WIDTH, "HEIGHT": _HEIGHT,
                "FRAMES": _FRAMES, "STEPS": _STEPS,
                "CFG": _CFG, "SEED": args.seed, "FPS": _FPS,
                "SAVE_PREFIX": "pipeline/ltx_director_smoke/smoke",
            },
            dest=_DEST,
        )
    except (ComfyError, ContingencyStop) as exc:
        print(f"ltx_director_smoke FAILED after {time.monotonic() - start:.1f}s: {exc}")
        return 2
    elapsed = time.monotonic() - start

    marker = ENGINE_ROOT / "workflows" / ".ltx_director_smoke_passed"
    marker.write_text(f"passed {elapsed:.1f}s seed={args.seed}\n", encoding="utf-8")
    print(f"LTX Director lab gate marker written: {marker}")
    print(f"template={args.template} seconds={elapsed:.1f} output={paths[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
