#!/usr/bin/env python3
"""Fresh-panel 2-frame Wan test (2026-08-20): generate 2 fresh panels via
Flux-2-Klein, generate a genuinely distinct end frame for each, then run the
wan_ti2v_2f.json two-keyframe template. Logs start/end frames + motion gate."""
from __future__ import annotations

import sys, time, json
from pathlib import Path
from PIL import Image

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.comfy_client import ComfyClient, ComfyError, ContingencyStop
from pipeline.config import PipelineConfig
from pipeline.stage3c_animation import verify_clip_motion

OUT = Path("/tmp/wan22-2f-fresh")
OUT.mkdir(exist_ok=True)
NEG = (
    "character redesign, changing clothes, face distortion, extra arms, extra fingers, "
    "duplicated subject, flicker, morphing, text, watermark, extreme camera shake, "
    "sudden scene change, low-detail face, static, still image"
)

# shot -> (start prompt, end prompt, start seed, end seed)
SHOTS = [
    ("sh-001-01",
     "violet shoulder-length hair with slight wave, cyan almond-shaped eyes, pale skin dotted with faint freckles, slender and agile build, deep emerald bodysuit with silver trim detailing, glowing blue scar on left cheek, The Chroma Weaving Academy, a place where color is studied and controlled, sterile gray structures, wide shot, low angle, Kaela crouched behind a desk, her back to the viewer, night lighting, anime 2d illustration, cel shading, clean linework, no text",
     "violet shoulder-length hair with slight wave, cyan almond-shaped eyes, pale skin dotted with faint freckles, slender and agile build, deep emerald bodysuit with silver trim detailing, glowing blue scar on left cheek, The Chroma Weaving Academy, medium shot, Kaela straightens up and turns her head toward camera, alert expression, night lighting, anime 2d illustration, cel shading, clean linework, no text",
     111, 222),
    ("sh-001-02",
     "violet shoulder-length hair with slight wave, cyan almond-shaped eyes, pale skin dotted with faint freckles, slender and agile build, deep emerald bodysuit with silver trim detailing, The Chroma Weaving Academy, medium shot, Kaela looks up warily, night lighting, anime 2d illustration, cel shading, clean linework, no text",
     "violet shoulder-length hair with slight wave, cyan almond-shaped eyes, pale skin dotted with faint freckles, slender and agile build, deep emerald bodysuit with silver trim detailing, The Chroma Weaving Academy, medium shot, Kaela steps forward one pace, hand reaching for her hip, alert, night lighting, anime 2d illustration, cel shading, clean linework, no text",
     333, 444),
]

def gen_frame(comfy, prompt, seed, name, dest, *, res=(672, 384)):
    paths = comfy.generate("image_txt2img_flux_fallback.json", {
        "PROMPT_POS": prompt,
        "PROMPT_NEG": NEG,
        "WIDTH": res[0], "HEIGHT": res[1],
        "SEED": seed, "STEPS": 20, "CFG": 2.0,
        "SAVE_PREFIX": f"pipeline/i2v_fresh/{name}",
    }, dest=dest)
    return paths[0]

def main():
    cfg = PipelineConfig.load()
    comfy = ComfyClient(cfg, timeout_s=7200.0)
    assert comfy.healthy(), "comfy down"
    comfy.unload_ollama()

    report = []
    for sid, start_p, end_p, sseed, eseed in SHOTS:
        print(f"\n=== {sid} ===", flush=True)
        # 1. fresh start panel
        t0 = time.monotonic()
        start = gen_frame(comfy, start_p, sseed, f"{sid}_start", OUT / sid)
        print(f"  start panel {time.monotonic()-t0:.1f}s {start}", flush=True)
        # 2. fresh end panel (distinct moment)
        t0 = time.monotonic()
        end = gen_frame(comfy, end_p, eseed, f"{sid}_end", OUT / sid)
        print(f"  end panel   {time.monotonic()-t0:.1f}s {end}", flush=True)
        # 3. upload both + run 2-frame wan
        t0 = time.monotonic()
        su = comfy.upload_image(start, name=f"{sid}_f_start.png")
        eu = comfy.upload_image(end, name=f"{sid}_f_end.png")
        try:
            paths = comfy.generate("wan_ti2v_2f.json", {
                "MOTION_PROMPT": "the character moves through the action, turning toward camera, hair and clothing flow, subtle cinematic push-in, stable anime illustration, consistent face and outfit",
                "PROMPT_NEG": NEG,
                "START_FRAME": su, "END_FRAME": eu,
                "WIDTH": 672, "HEIGHT": 384, "FRAMES": 33, "STEPS": 14,
                "CFG": 2.5, "SEED": 42, "FPS": 16,
                "SAVE_PREFIX": f"pipeline/i2v_fresh/{sid}_clip",
            }, dest=OUT / sid)
            clip = paths[0]
            m = verify_clip_motion(clip)
            print(f"  wan 2f {time.monotonic()-t0:.1f}s {clip}", flush=True)
            print(f"  MOTION: axis={m['motion_axis']} cam_net={m['cam_net_px']}px "
                  f"cam_dir={m['cam_directed']} scene={m['scene_speed_px']}px "
                  f"verified={m['motion_verified']}", flush=True)
            report.append((sid, m['motion_axis'], m['cam_net_px'], m['cam_directed'],
                           m['scene_speed_px'], m['motion_verified']))
        except (ComfyError, ContingencyStop) as e:
            print(f"  wan 2f FAIL {time.monotonic()-t0:.1f}s: {e}", flush=True)
            report.append((sid, "ERROR", 0, 0, 0, False))

    print("\n=== VERDICT ===", flush=True)
    for r in report:
        print(r)

if __name__ == "__main__":
    raise SystemExit(main())
