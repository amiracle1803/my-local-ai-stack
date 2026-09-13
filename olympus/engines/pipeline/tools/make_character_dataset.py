"""Generate a character training set (for LoRA) from a text description.

Renders N consistent images of one character via krea2 (or a chosen workflow)
across varied poses/angles/lighting, captioned for kohya/ai-toolkit training.
The user wants character LoRAs so each scene's narration matches the right
character.

Usage:
  python tools/make_character_dataset.py --name gustav --out loras/gustav \
      --desc "a 17-year-old boy, dirty blond short hair, perfectly toned body, maroon school uniform" \
      --n 16
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.comfy_client import ComfyClient  # noqa: E402
from pipeline.config import PipelineConfig  # noqa: E402

STYLE = "anime 2d illustration, clean linework, cel shading, high detail"
NEG = ("lowres, bad anatomy, extra fingers, cropped, worst quality, low quality, "
       "jpeg artifacts, signature, watermark, blurry, text, letters")

# Varied poses/angles so the LoRA learns the character, not one pose.
POSES = [
    "standing, full body, front view",
    "standing, three-quarter view",
    "close-up portrait, facing camera",
    "profile view",
    "sitting, relaxed",
    "running, dynamic action pose",
    "fighting stance",
    "looking over shoulder",
    "walking toward camera",
    "seated, pensive",
    "arms crossed, confident",
    "side profile, dramatic lighting",
    "back view, turning",
    "kneeling, determined",
    "standing, low angle, heroic",
    "head and shoulders, serious expression",
]
SCENES = [
    "in a school courtyard", "at a cliff edge at dusk", "in a dark forest",
    "in a modern sci-fi city street", "in a dim room", "in a large arena",
    "on a rooftop at night", "in a futuristic classroom",
]

# Anime style variety so the LoRA generalizes across looks. The user wants the
# Classroom of the Elite (COTE) anime style -- realistic proportions, sharp clean
# lineart, subdued muted palette, tense atmosphere -- so every style line is a
# COTE-flavored variation (subtle lighting/grade shifts, not divergent genres).
STYLES = [
    "Classroom of the Elite anime style, semi-realistic proportions, sharp clean lineart, subdued muted color palette, detailed expressive eyes, tense atmosphere",
    "Classroom of the Elite style, clean cel shading, crisp outlines, muted desaturated tones, realistic school setting",
    "Classroom of the Elite anime, refined lineart, subtle gradient shading, cool restrained palette, psychological drama mood",
    "COTE anime style, precise anatomy, clean background, soft muted colors, serious composed expressions",
    "Classroom of the Elite style, detailed realistic faces, sharp linework, understated tones, contemplative mood",
    "COTE style, semi-realistic, elegant clean lines, muted cool palette, focused tense lighting",
    "Classroom of the Elite anime, balanced realistic proportions, crisp edges, subdued color grade, quiet intensity",
    "COTE anime style, clean polished lineart, muted natural colors, detailed modern classroom, calm tension",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--desc", required=True, help="character appearance description")
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--workflow", default="image_txt2img_krea2.json")
    ap.add_argument("--model", default="krea2_turbo-Q4_K_M.gguf")
    args = ap.parse_args()

    pcfg = PipelineConfig.load()
    comfy = ComfyClient(pcfg)
    if not comfy.healthy():
        print("ComfyUI not reachable"); sys.exit(1)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Trigger-token the model should learn for this character (kohya style).
    token = args.name.lower()
    base = f"{args.desc}, {token}"

    rows = []
    for i in range(args.n):
        pose = POSES[i % len(POSES)]
        scene = SCENES[i % len(SCENES)]
        style = STYLES[i % len(STYLES)]
        prompt = f"{base}, {pose}, {scene}, {style}"
        tag = f"{args.name}_{i:04d}"
        print(f"--- {tag} ---")
        try:
            imgs = comfy.generate(
                args.workflow,
                {"PROMPT_POS": prompt, "WIDTH": 832, "HEIGHT": 1216,
                 "SEED": int(time.time() * 1000) % 2**31, "STEPS": 8,
                 "CFG": 1.0, "SAVE_PREFIX": tag}, dest=out)
        except Exception as e:
            print(f"  !! render failed: {e}"); continue
        if not imgs:
            print("  !! no image"); continue
        img = imgs[0]
        # Caption: the character token + pose/scene (kohya style). Style left
        # generic so the LoRA's base style isn't over-fit to one look.
        cap = f"{token}, {pose}, {scene}"
        img.with_suffix(".txt").write_text(cap, encoding="utf-8")
        rows.append({"image": img.name, "caption": cap, "prompt": prompt, "style": style})
        print(f"  {img.name} | style[{i % len(STYLES)}] -> {cap}")

    (out / "_index.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"done: {len(rows)} images in {out}")


if __name__ == "__main__":
    main()