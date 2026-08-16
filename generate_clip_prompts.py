#!/usr/bin/env python3
"""
generate_clip_prompts.py
Generate ComfyUI-ready CLIP positive/negative prompts per character
from mystic_eyes_characters.json for stages 0-3 conditioning.
"""

import json
from pathlib import Path

STORY_ROOT = Path("/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/Ai youtube story/Full ai video production/Mystic Eyes My Eyes Steal the Laws of Cultivation")
CHAR_JSON = STORY_ROOT / "mystic_eyes_characters.json"

BASE_POSITIVE = "Cinematic panel-to-panel animation, smooth motion between comic panels, consistent character appearance, detailed backgrounds, professional animation quality, 24fps smooth motion, manhwa webtoon style, Korean comic art"
BASE_NEGATIVE = "blurry, low quality, distorted, deformed, bad anatomy, extra limbs, missing limbs, floating, disconnected, flickering, inconsistent, morphing, watermark, text, logo, signature, blurry, low resolution, pixelated, noisy, grainy, oversaturated, undersaturated, color shift, hue shift"

def load_characters():
    with open(CHAR_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return data["characters"]

def build_prompts():
    chars = load_characters()
    out = {}
    for c in chars:
        name = c["name"]
        # Use description_raw as character-specific traits
        char_trait = c["description_raw"][:300]
        positive = f"{BASE_POSITIVE}, character: {name}, {char_trait}"
        negative = BASE_NEGATIVE
        out[name] = {"positive": positive, "negative": negative}
    return out

if __name__ == "__main__":
    prompts = build_prompts()
    out_path = STORY_ROOT / "mystic_eyes_clip_prompts.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(prompts, f, indent=2, ensure_ascii=False)
    print(f"Generated prompts for {len(prompts)} characters")
    print(f"Saved to {out_path}")
    # Show example
    example_name = list(prompts.keys())[0]
    print(f"\nExample {example_name}:")
    print(prompts[example_name]["positive"][:300])