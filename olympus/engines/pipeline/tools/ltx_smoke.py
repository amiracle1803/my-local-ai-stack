#!/usr/bin/env python3
"""LTX model_lab smoke gate (design M-AP-3): queue ONE LTX I2V render through
ComfyClient and report wall time + output path. Run this before letting an
LTX template take over stage3c.

Usage:  python tools/ltx_smoke.py [--template video_i2v_ltx_2b.json]
Exit codes: 0 on success, 2 on ComfyError/ContingencyStop.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.comfy_client import ComfyClient, ComfyError, ContingencyStop  # noqa: E402
from pipeline.config import PipelineConfig  # noqa: E402

# Minimal 480x270 x 17 frames @ 16fps = ~1s clip, 6 steps for speed
# This is small enough to run in ~30-60s on 8GB VRAM
_PROMPT = "anime scene, gentle camera pan, warm lighting, subtle motion"
_SEED = 42
_WIDTH, _HEIGHT = 480, 270
_FRAMES = 17
_STEPS = 6
_FPS = 16
_DEST = Path("/tmp/ltx-smoke")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="video_i2v_ltx_2b.json")
    args = ap.parse_args()

    config = PipelineConfig.load()
    comfy = ComfyClient(config)
    if not comfy.healthy():
        print("ComfyUI is not reachable - start it first.")
        return 2
    comfy.unload_ollama()

    # Need a start frame - create a simple test image or use existing panel
    # For the smoke test, we'll generate a simple solid color panel via a quick txt2img
    # But the LTX workflow needs a START_FRAME. Let's check if we have a test panel.
    test_panel = Path("/tmp/ltx-smoke/test_panel.png")
    test_panel.parent.mkdir(parents=True, exist_ok=True)

    # Quick fallback: create a minimal test panel if none exists
    if not test_panel.exists():
        # Use flux fallback to generate a simple start frame
        try:
            paths = comfy.generate(
                "image_txt2img_flux_fallback.json",
                {
                    "PROMPT_POS": "anime character, simple background, test frame",
                    "WIDTH": _WIDTH, "HEIGHT": _HEIGHT,
                    "SEED": _SEED,
                    "SAVE_PREFIX": "pipeline/ltx_smoke/test_panel",
                },
                dest=test_panel.parent,
            )
            test_panel = paths[0]
            print(f"Generated test panel: {test_panel}")
        except (ComfyError, ContingencyStop) as exc:
            print(f"Failed to generate test panel: {exc}")
            return 2

    start = time.monotonic()
    try:
        uploaded = comfy.upload_image(test_panel, name="ltx_smoke_start.png")
        paths = comfy.generate(
            args.template,
            {
                "MOTION_PROMPT": _PROMPT,
                "START_FRAME": uploaded,
                "WIDTH": _WIDTH, "HEIGHT": _HEIGHT,
                "FRAMES": _FRAMES, "STEPS": _STEPS,
                "SEED": _SEED, "FPS": _FPS,
                "SAVE_PREFIX": "pipeline/ltx_smoke/smoke",
            },
            dest=_DEST,
        )
    except (ComfyError, ContingencyStop) as exc:
        print(f"ltx_smoke FAILED after {time.monotonic() - start:.1f}s: {exc}")
        return 2
    elapsed = time.monotonic() - start

    # A passing LTX render satisfies the model_lab gate (design M-AP-3) --
    # video_router routes to LTX only once this marker exists.
    if args.template in ("video_i2v_ltx_2b.json", "video_i2v_ltx_22b.json", "ltx2b_i2v.json", "ltx22b_i2v.json"):
        marker = ENGINE_ROOT / "workflows" / ".ltx_smoke_passed"
        marker.write_text(f"passed {elapsed:.1f}s seed={_SEED}\n", encoding="utf-8")
        print(f"LTX lab gate marker written: {marker}")
    elif args.template in ("video_i2v_ltx_23b_tiled.json", "ltx23_i2v_8gb.json"):
        marker = ENGINE_ROOT / "workflows" / ".ltx23_smoke_passed"
        marker.write_text(f"passed {elapsed:.1f}s seed={_SEED}\n", encoding="utf-8")
        print(f"LTX23 lab gate marker written: {marker}")

    print(f"template={args.template} seconds={elapsed:.1f} output={paths[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())