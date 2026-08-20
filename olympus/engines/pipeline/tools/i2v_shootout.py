#!/usr/bin/env python3
"""Full-res I2V shootout gates: run each model at its production config,
motion-gate with verify_clip_motion, append to /tmp/i2v-shootout/results.tsv.

Runs sequentially (8GB VRAM — never parallel). Detached via setsid so the
client can outlive the shell; poll /tmp/i2v-shootout/results.tsv."""
from __future__ import annotations

import sys, time, json
from pathlib import Path
from PIL import Image

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.comfy_client import ComfyClient, ComfyError, ContingencyStop
from pipeline.config import PipelineConfig
from pipeline.stage3c_animation import verify_clip_motion

OUT = Path("/tmp/i2v-shootout")
OUT.mkdir(exist_ok=True)
PANEL_SRC = ENGINE_ROOT / "projects" / "prismrebel" / "panels" / "blk-001" / "sh-001-01.png"
PROMPT = (
    "[camera: slow pan left] "
    "[motion: the character turns their head and breathes, coat fabric sways "
    "gently in the wind] anime scene, cinematic lighting, dynamic composition, "
    "shallow depth of field"
)
NEG = "morphing, warping, flicker, jitter, text, watermark, low quality, deformed, static, freeze frame"
SEED = 42

# model -> (template, {patches})
RUNS = [
    ("svd_xt", "video_svd.json", {
        "WIDTH": 832, "HEIGHT": 480, "FRAMES": 25, "STEPS": 20,
        "CFG": 3.0, "SEED": SEED, "MOTION_BUCKET": 127, "FPS": 6,
        "SVD_MODEL": "svd_xt-fp16.safetensors",
    }),
    ("ltx2b", "video_i2v_ltx_2b.json", {
        "WIDTH": 1216, "HEIGHT": 704, "FRAMES": 81, "STEPS": 20,
        "CFG": 5.0, "SEED": SEED, "FPS": 16,
    }),
]

def prep_panel(w: int, h: int, name: str) -> Path:
    img = Image.open(PANEL_SRC).convert("RGB")
    W, H = img.size
    crop_h = int(W * 9 / 16)
    if crop_h > H:
        crop_w = int(H * 16 / 9); left = (W - crop_w) // 2
        img = img.crop((left, 0, left + crop_w, H))
    else:
        top = (H - crop_h) // 2
        img = img.crop((0, top, W, top + crop_h))
    img = img.resize((w, h), Image.LANCZOS)
    p = OUT / name
    img.save(p)
    return p

def main():
    cfg = PipelineConfig.load()
    comfy = ComfyClient(cfg, timeout_s=7200.0)
    if not comfy.healthy():
        print("ComfyUI not reachable", file=sys.stderr); return 2
    comfy.unload_ollama()

    results = OUT / "results.tsv"
    if not results.exists():
        results.write_text("model\tseconds\taxis\tcam_speed\tcam_net\tcam_dir\tcam_jitter\tscene_speed\tverified\toutput\n")

    for key, tmpl, patches in RUNS:
        marker = OUT / f"{key}.done"
        if marker.exists():
            print(f"skip {key} (already done)"); continue
        w, h = patches["WIDTH"], patches["HEIGHT"]
        panel = prep_panel(w, h, f"{key}_panel.png")
        try:
            up = comfy.upload_image(panel, name=f"gate_{key}_start.png")
        except Exception as e:
            print(f"{key} upload FAIL: {e}", file=sys.stderr); continue
        t0 = time.monotonic()
        try:
            patch_set = {"START_FRAME": up, **patches, "SAVE_PREFIX": f"pipeline/i2v_gate/{key}"}
            if key != "svd_xt":
                patch_set["MOTION_PROMPT"] = PROMPT
                patch_set["PROMPT_NEG"] = NEG
            paths = comfy.generate(tmpl, patch_set, dest=OUT)
        except (ComfyError, ContingencyStop) as e:
            elapsed = time.monotonic() - t0
            with open(results, "a") as fh:
                fh.write(f"{key}\t{elapsed:.1f}\tERROR\t-\t-\t-\t-\t-\tfalse\t{e}\n")
            print(f"{key} FAIL {elapsed:.1f}s: {e}", file=sys.stderr)
            continue
        elapsed = time.monotonic() - t0
        clip = paths[0]
        m = verify_clip_motion(clip)
        line = f"{key}\t{elapsed:.1f}\t{m['motion_axis']}\t{m['cam_speed_px']}\t{m['cam_net_px']}\t{m['cam_directed']}\t{m['cam_jitter']}\t{m['scene_speed_px']}\t{m['motion_verified']}\t{clip}\n"
        with open(results, "a") as fh:
            fh.write(line)
        print(f"{key} {elapsed:.1f}s axis={m['motion_axis']} cam_net={m['cam_net_px']}px scene={m['scene_speed_px']}px -> {clip}")
        marker.write_text(line)

if __name__ == "__main__":
    raise SystemExit(main())