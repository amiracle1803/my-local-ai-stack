"""model_lab smoke gate (design 5.4): queue ONE txt2img render through
ComfyClient and report wall time + output path. Run this before letting a
newly-installed model's template take over an image stage.

Usage:  python tools/model_smoke.py [--template image_txt2img_krea2.json]
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

_PROMPT = "1girl, red hair, mountain shrine, anime 2d illustration, cel shading, test render"
_SEED = 42
_WIDTH, _HEIGHT = 832, 704
_DEST = Path("/tmp/model-smoke")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="image_txt2img_krea2.json")
    args = ap.parse_args()

    config = PipelineConfig.load()
    comfy = ComfyClient(config)
    if not comfy.healthy():
        print("ComfyUI is not reachable - start it first.")
        return 2
    comfy.unload_ollama()

    start = time.monotonic()
    try:
        paths = comfy.generate(
            args.template,
            {
                "PROMPT_POS": _PROMPT,
                "WIDTH": _WIDTH, "HEIGHT": _HEIGHT,
                "SEED": _SEED,
                "SAVE_PREFIX": "pipeline/model_smoke/smoke",
            },
            dest=_DEST,
        )
    except (ComfyError, ContingencyStop) as exc:
        print(f"model_smoke FAILED after {time.monotonic() - start:.1f}s: {exc}")
        return 2
    elapsed = time.monotonic() - start

    # A passing krea2 render satisfies the model_lab gate (design 5.3b) --
    # image_router routes to krea2 only once this marker exists.
    if args.template in ("image_txt2img_krea2.json", "image_krea2.json"):
        marker = ENGINE_ROOT / "workflows" / ".krea2_smoke_passed"
        marker.write_text(f"passed {elapsed:.1f}s seed={_SEED}\n", encoding="utf-8")
        print(f"lab gate marker written: {marker}")
    elif args.template in ("image_txt2img_anima.json", "image_anima.json"):
        marker = ENGINE_ROOT / "workflows" / ".anima_smoke_passed"
        marker.write_text(f"passed {elapsed:.1f}s seed={_SEED}\n", encoding="utf-8")
        print(f"lab gate marker written: {marker}")

    print(f"template={args.template} seconds={elapsed:.1f} output={paths[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
