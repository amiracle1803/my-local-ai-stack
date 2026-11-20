#!/usr/bin/env python3
"""A/B render bench: the same shots through several [render] profile variants.

    python tools/bench_render.py --project lanternfall_v3c_ep01 --out /tmp/bench \
        --panels legacy,klein4b,klein9b --clips ltx2b,ltx2b_up,ltx13b,ltx13b_up

Panels reuse each shot's real prompt / negative / character sheets (panels/*.json).
Clips animate the first shot's panel from the LAST panel variant. Writes timings.json and
a contact sheet (panels.png) so variants can be compared side by side.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))
sys.path.insert(0, str(ENGINE_ROOT.parent.parent.parent))

from stack.config import RenderProfile  # noqa: E402
from pipeline import comfy_client, ltx2b  # noqa: E402

LEGACY = RenderProfile()
PANEL_VARIANTS = {
    "legacy": LEGACY,
    "klein4b": LEGACY.model_copy(update={"panel_width": 1280, "panel_height": 720,
                                         "panel_steps": 4, "panel_cfg": 1.0}),
    "klein9b": LEGACY.model_copy(update={"panel_unet": "flux-2-klein-9b-Q5_K_M.gguf",
                                         "panel_clip": "qwen_3_8b_fp8mixed.safetensors",
                                         "panel_width": 1280, "panel_height": 720,
                                         "panel_steps": 4, "panel_cfg": 1.0}),
}
PANEL_VARIANTS["klein9b_sharp"] = PANEL_VARIANTS["klein9b"].model_copy(
    update={"panel_upscale": "2x-AnimeSharpV4_RCAN.safetensors"})
LTX13 = {"video_unet": "LTXV-13B-0.9.8-distilled-Q4_K_M.gguf",
         "video_vae": "LTXV-13B-0.9.8-distilled-VAE.safetensors"}
UP = {"video_upscale": "ltxv-spatial-upscaler-0.9.8.safetensors"}
CLIP_VARIANTS = {
    "ltx2b": LEGACY,
    "ltx2b_up": LEGACY.model_copy(update={"video_width": 768, "video_height": 448, **UP}),
    "ltx13b": LEGACY.model_copy(update={"video_width": 768, "video_height": 448, **LTX13}),
    "ltx13b_up": LEGACY.model_copy(update={"video_width": 768, "video_height": 448, **LTX13, **UP}),
}
CLIP_VARIANTS["ltx13b_up_pp"] = CLIP_VARIANTS["ltx13b_up"].model_copy(update={"video_img_compression": 35})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--shots", default="sc001_sh001,sc001_sh007,sc002_sh006")
    ap.add_argument("--panels", default=",".join(PANEL_VARIANTS))
    ap.add_argument("--clips", default="")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--clip-shot", type=int, default=0, help="index into --shots for the clips")
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    args = ap.parse_args()
    proj = ENGINE_ROOT / "projects" / args.project
    args.out.mkdir(parents=True, exist_ok=True)
    timings: dict = {}
    tpath = args.out / "timings.json"
    if tpath.exists():
        timings = json.loads(tpath.read_text())
    metas = []
    for key in args.shots.split(","):
        side = next(proj.glob(f"panels/*_{key}_panel_v001.json"))
        meta = json.loads(side.read_text())
        meta["_key"] = key
        meta["_refs"] = [str(proj / r) for r in meta.get("character_sheets", [])]
        metas.append(meta)

    def timed(name: str, fn) -> None:
        t0 = time.time()
        try:
            fn()
            timings[name] = round(time.time() - t0, 1)
        except Exception as e:  # noqa: BLE001
            timings[name] = f"FAILED: {type(e).__name__}: {str(e)[:300]}"
        print(f"{name}: {timings[name]}", flush=True)
        tpath.write_text(json.dumps(timings, indent=2))

    panel_names = [p for p in args.panels.split(",") if p]
    for pv in panel_names:
        prof = PANEL_VARIANTS[pv]
        for m in metas:
            dest = args.out / f"panel_{pv}_{m['_key']}.png"
            timed(dest.stem, lambda: comfy_client.render_panel(
                m["prompt"], dest, seed=1234,
                base_url=args.url, negative=m.get("negative_prompt", ""), references=m["_refs"], prof=prof))
    for cv in [c for c in args.clips.split(",") if c]:
        prof = CLIP_VARIANTS[cv]
        m = metas[args.clip_shot]
        panel = args.out / f"panel_{panel_names[-1] if panel_names else 'legacy'}_{m['_key']}.png"
        dest = args.out / f"clip_{cv}_{m['_key']}.mp4"
        prompt = __import__("pipeline.stages", fromlist=["motion_prompt"]).motion_prompt(m)
        timed(dest.stem, lambda: ltx2b.render_clip(prompt, dest, 1234, panel=panel, base_url=args.url,
                                                   frames=ltx2b.frames_for(args.seconds), prof=prof))
    _contact_sheet(args.out, panel_names, metas)
    return 0


def _contact_sheet(out: Path, variants: list[str], metas: list[dict]) -> None:
    from PIL import Image, ImageDraw
    cw, ch = 640, 360
    sheet = Image.new("RGB", (cw * len(metas), (ch + 24) * len(variants)), "white")
    d = ImageDraw.Draw(sheet)
    for r, pv in enumerate(variants):
        for c, m in enumerate(metas):
            f = out / f"panel_{pv}_{m['_key']}.png"
            if f.exists():
                with Image.open(f) as im:
                    sheet.paste(im.convert("RGB").resize((cw, ch)), (c * cw, r * (ch + 24) + 24))
            d.text((c * cw + 6, r * (ch + 24) + 6), f"{pv} / {m['_key']}", fill="black")
    sheet.save(out / "panels.png")


if __name__ == "__main__":
    raise SystemExit(main())
