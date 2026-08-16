#!/usr/bin/env python3
"""
generate_clip_prompts_v2.py using final characters JSON
"""

import json
from pathlib import Path

STORY_ROOT = Path("/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/Ai youtube story/Full ai video production/Mystic Eyes My Eyes Steal the Laws of Cultivation")
CHAR_JSON = STORY_ROOT / "mystic_eyes_characters_final.json"

BASE_POSITIVE = "Cinematic panel-to-panel animation, smooth motion between comic panels, consistent character appearance, detailed backgrounds, professional animation quality, 24fps smooth motion, manhwa webtoon style, Korean comic art"
BASE_NEGATIVE = "blurry, low quality, distorted, deformed, bad anatomy, extra limbs, missing limbs, floating, disconnected, flickering, inconsistent, morphing, watermark, text, logo, signature, blurry, low resolution, pixelated, noisy, grainy, oversaturated, undersaturated, color shift, hue shift"

with open(CHAR_JSON, encoding="utf-8") as f:
    data = json.load(f)

prompts = {}
for c in data["characters"]:
    name = c["name"]
    desc = c["description"]
    # truncate description for prompt length
    short_desc = " ".join(desc.split()[:40])
    positive = f"{BASE_POSITIVE}, character: {name}, {short_desc}"
    prompts[name] = {"positive": positive, "negative": BASE_NEGATIVE}

out_path = STORY_ROOT / "mystic_eyes_clip_prompts_final.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(prompts, f, indent=2, ensure_ascii=False)
print(f"Generated prompts for {len(prompts)} characters -> {out_path}")