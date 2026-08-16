#!/usr/bin/env python3
"""Wan2.2-TI2V-5B lab smoke gate (design M-AP-3): queue ONE Wan2.2 I2V render
through ComfyClient and gate it on REAL optical-flow-verified motion before
letting the wan_ti2v template take over stage3c.

Admission rule (2026-08-12): the render must show BOTH directed camera motion
(pan / push-in, not shake) AND scene motion (subject / foreground moving),
verified with the calibrated optical-flow gate in stage3c's
``verify_clip_motion``. A static or shake-only render FAILS the gate:
no marker, exit code 3.

The smoke runs at the template's REAL production config (1216x704, 81 frames,
flowmatch_pusa 20 steps, cfg 5.0) with a REAL stage-3C.4 project panel as the
start frame — no resolution shrinking, no synthetic gradient. The panel is
center-cropped to 16:9 in-place (never squashed).

Usage:  python tools/wan_smoke.py [--panel /abs/panel.png]
Exit codes: 0 = passed + marker written, 2 = ComfyError/ContingencyStop,
            3 = rendered but motion gate failed (no marker).
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
from pipeline.stage3c_animation import verify_clip_motion  # noqa: E402

# A clean, single minded motion prompt: ONE camera move + natural scene motion.
# An overloaded prompt (walk+hair+coat+rain+embers+dolly at once) makes Wan
# warp; a short render makes 17-frame artifacts look like morphing.
_PROMPT = (
    "[camera: slow pan left] "
    "[motion: the character turns their head and breathes, coat fabric sways "
    "gently in the wind] anime scene, cinematic lighting, dynamic composition, "
    "shallow depth of field"
)
_PROMPT_NEG = "morphing, warping, flicker, jitter, text, watermark, low quality, deformed, static, freeze frame"
_SEED = 42
_CFG = 5.0
_FPS = 16
# Production resolution the wan_ti2v.json template stages its empty embeds
# at (node 8 WanVideoEmptyEmbeds) — the start frame MUST be uploaded at this
# exact size: WanVideoEncode VAE-encodes at native input size while empty
# embeds fix 1216x704, and a smaller start frame crashes the sampler with a
# latent tensor mismatch ([18,32] vs [44,48]).
_WAN_W, _WAN_H = 1216, 704
_DEST = Path("/tmp/wan-smoke")
_DEFAULT_PANEL = (
    ENGINE_ROOT / "projects" / "prismrebel" / "panels" / "blk-001" / "sh-001-01.png"
)


def _prepare_panel(src: Path) -> Path:
    """Center-crop the real project panel to 16:9 and upscale to the template's
    native production resolution (1216x704).

    No resolution shrinking and no aspect distortion: the panel is cropped in
    place, then LANCZOS-upscaled to the 1216x704 that wan_ti2v.json's empty
    embeds are staged at. was never squashed — the previous run's 512x288
    start frame crashed the sampler because WanVideoEncode VAE-encodes at
    native size while empty embeds are 1216x704 (latent [44,48] vs [18,32])."""
    from PIL import Image

    if not src.exists():
        raise SystemExit(f"panel not found: {src} (exit 2)")
    img = Image.open(src).convert("RGB")
    w, h = img.size
    crop_h = int(w * 9 / 16)
    if crop_h > h:  # panel taller than 16:9 -> crop width instead
        crop_w = int(h * 16 / 9)
        left = (w - crop_w) // 2
        img = img.crop((left, 0, left + crop_w, h))
    else:
        top = (h - crop_h) // 2
        img = img.crop((0, top, w, top + crop_h))
    img = img.resize((_WAN_W, _WAN_H), Image.LANCZOS)
    out = _DEST / "smoke_panel.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="wan_ti2v.json")
    ap.add_argument("--panel", type=Path, default=_DEFAULT_PANEL,
                    help="real stage-3C.4 panel to animate (default prismrebel sh-001-01)")
    args = ap.parse_args()

    config = PipelineConfig.load()
    # Full-res 81-frame Wan on the 8GB card can run ~10-20 min; the client
    # default 600s poll deadline must not abort a legitimate smoke.
    comfy = ComfyClient(config, timeout_s=3600.0)
    if not comfy.healthy():
        print("ComfyUI is not reachable - start it first.")
        return 2
    comfy.unload_ollama()

    panel = _prepare_panel(args.panel)
    # Only the production config lives here: template defaults carry the
    # real 1216x704 x 81-frame x flowmatch_pusa-20-step settings. Nothing
    # below shrinks width/height, frame count, or steps.
    print(f"Start frame (real 16:9 crop of {args.panel}): {panel}")

    start = time.monotonic()
    try:
        uploaded = comfy.upload_image(panel, name="wan_smoke_start.png")
        paths = comfy.generate(
            args.template,
            {
                "MOTION_PROMPT": _PROMPT,
                "PROMPT_NEG": _PROMPT_NEG,
                "START_FRAME": uploaded,
                "CFG": _CFG, "SEED": _SEED, "FPS": _FPS,
                "SAVE_PREFIX": "pipeline/wan_smoke/smoke",
            },
            dest=_DEST,
        )
    except (ComfyError, ContingencyStop) as exc:
        print(f"wan_smoke FAILED after {time.monotonic() - start:.1f}s: {exc}")
        return 2
    elapsed = time.monotonic() - start
    clip = paths[0]

    motion = verify_clip_motion(clip)
    print(f"template={args.template} seconds={elapsed:.1f} output={clip}")
    print(f"motion gate: axis={motion['motion_axis']} "
          f"cam={motion['cam_speed_px']}px net={motion['cam_net_px']}px "
          f"dir={motion['cam_directed']} scene={motion['scene_speed_px']}px")

    # Both axes are required before Wan gets unlocked — a clip with only a
    # dead camera pan over a frozen scene still fails the smoke gate.
    if args.template == "wan_ti2v.json":
        if motion["motion_axis"] != "camera+scene":
            print(
                f"wan_smoke REJECTED: axis={motion['motion_axis']} — need "
                "camera+scene. NO marker written (video_router keeps Wan locked "
                "out)."
            )
            return 3
        marker = ENGINE_ROOT / "workflows" / ".wan_smoke_passed"
        marker.write_text(
            f"passed {elapsed:.1f}s seed={_SEED} axis={motion['motion_axis']} "
            f"cam={motion['cam_speed_px']}px scene={motion['scene_speed_px']}px\n",
            encoding="utf-8",
        )
        print(f"Wan2.2 lab gate marker written: {marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())