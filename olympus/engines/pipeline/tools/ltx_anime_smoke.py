#!/usr/bin/env python3
"""Render one anime LTX smoke clip through the production renderer."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline import ltx2b, ltx_director  # noqa: E402
from pipeline.contracts import validate_media  # noqa: E402

DEFAULT_PROMPT = (
    "Aya, a 16-year-old girl with short black hair, a red scarf and brown wool coat, "
    "is fully visible and unobstructed on the left side of a floating lantern tower's "
    "spiral stairwell at deep indigo dusk. She climbs two steps as her scarf billows "
    "in the wind and warm amber lantern light flickers. The sea of clouds drifts below. "
    "A slow stable push-in preserves her appearance and the background throughout the shot."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["ltx2b", "ltx_director"], default="ltx2b")
    parser.add_argument("--mode", choices=["t2v", "i2v"], default="t2v")
    parser.add_argument("--panel", type=Path, help="Start panel; required for --mode i2v")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--steps", type=int, default=8, help="LTX 2B distilled sampling steps")
    args = parser.parse_args()
    if args.mode == "i2v" and not args.panel:
        parser.error("--mode i2v requires --panel")

    output = args.output or Path.home() / "Videos" / "ltx-director" / f"anime_{args.engine}_{args.mode}.mp4"
    output = output.expanduser()
    frames = ltx2b.frames_for(args.seconds)
    started = time.monotonic()
    if args.engine == "ltx2b":
        result = ltx2b.render_clip(
            args.prompt, output, args.seed,
            panel=args.panel if args.mode == "i2v" else None,
            width=args.width, height=args.height, frames=frames, steps=args.steps,
            prefix=f"olympus/anime_{args.mode}",
        )
    else:
        result = ltx_director.render_director_clip(
            args.panel if args.mode == "i2v" else None, output,
            seed=args.seed, base_url="http://127.0.0.1:8188", motion_prompt=args.prompt,
            frames=frames, width=args.width, height=args.height,
        )
    if not validate_media(result):
        raise RuntimeError(f"renderer did not produce a valid video: {result}")

    report = {
        "output": str(result), "engine": args.engine, "mode": args.mode,
        "seconds_wall": round(time.monotonic() - started, 2), "bytes": result.stat().st_size,
        "seed": args.seed, "frames": frames, "width": args.width, "height": args.height,
        "steps": args.steps if args.engine == "ltx2b" else 8,
    }
    output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
