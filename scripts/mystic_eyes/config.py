#!/usr/bin/env python3
"""
config.py — shared paths, prompt templates and constants for the Mystic Eyes
ComfyUI pipeline. All the v1/v2 scripts used to hardcode these individually;
centralizing them here removes that duplication.
"""

import os
from pathlib import Path

# Root folder that holds the Mystic Eyes story source + generated JSON.
# Overridable via MYSTIC_EYES_ROOT so the tools can point at a mirror, a test
# fixture, or the drive under a different mount without editing this file.
_STORY_ROOT = Path(
    "/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/"
    "Ai youtube story/Full ai video production/"
    "Mystic Eyes My Eyes Steal the Laws of Cultivation"
)
STORY_ROOT = Path(os.environ.get("MYSTIC_EYES_ROOT") or _STORY_ROOT)

# Source text files parsed into character data.
APPEARANCE_FILE = STORY_ROOT / "Character apperence and description.txt"
GUIDE_FILE = STORY_ROOT / "Character list- guide.txt"

# Output JSON produced at each stage of the pipeline (input → characters → prompts).
CHARACTERS_JSON = STORY_ROOT / "mystic_eyes_characters.json"
CHARACTERS_FINAL_JSON = STORY_ROOT / "mystic_eyes_characters_final.json"
CHARACTERS_V2_JSON = STORY_ROOT / "mystic_eyes_characters_v2.json"
CLIP_PROMPTS_JSON = STORY_ROOT / "mystic_eyes_clip_prompts.json"
CLIP_PROMPTS_FINAL_JSON = STORY_ROOT / "mystic_eyes_clip_prompts_final.json"

# Base ComfyUI workflow the builders clone and stamp character/scene data into,
# and the folder that per-character workflows are written to. Both are
# overridable via env vars (MYSTIC_EYES_BASE_WF / MYSTIC_EYES_WF_OUT) for
# testing or for machines where ComfyUI lives elsewhere.
BASE_WORKFLOW = Path(
    os.environ.get("MYSTIC_EYES_BASE_WF")
    or "/home/amire/Downloads/my-local-ai-stack/ComfyUI/workflows/"
    "ltx23_panels_first_last_improved_stages4-7.json"
)
WORKFLOW_OUT_DIR = Path(
    os.environ.get("MYSTIC_EYES_WF_OUT")
    or "/home/amire/Downloads/my-local-ai-stack/ComfyUI/workflows/mystic_eyes_per_character"
)

# Node ids in the base workflow that hold the CLIP text (11 = positive,
# 12 = negative) and the first/last panel image loaders (5 = first, 6 = last).
POS_NODE_ID, NEG_NODE_ID = 11, 12
FIRST_IMAGE_NODE_ID, LAST_IMAGE_NODE_ID = 5, 6

# Stable CLIP conditioning appended to every prompt for visual consistency.
BASE_POSITIVE = (
    "Cinematic panel-to-panel animation, smooth motion between comic panels, "
    "consistent character appearance, detailed backgrounds, professional animation "
    "quality, 24fps smooth motion, manhwa webtoon style, Korean comic art"
)
BASE_NEGATIVE = (
    "blurry, low quality, distorted, deformed, bad anatomy, extra limbs, missing "
    "limbs, floating, disconnected, flickering, inconsistent, morphing, watermark, "
    "text, logo, signature, blurry, low resolution, pixelated, noisy, grainy, "
    "oversaturated, undersaturated, color shift, hue shift"
)

# Characters we already know exist, used by the KNOWN_NAMES parse strategy to
# slice the appearance file deterministically instead of guessing boundaries.
KNOWN_NAMES = [
    "Kyrian (Early Arc — Royal Order)",
    "Kyrian (Wilderness Arc)",
    "Kyrian (Sect/Bloody Court Arc)",
    "Liora",
    "Rurik",
    "General Harken",
    "Kael",
    "Elyria",
    "Lina",
    "Wei Feng",
    "Mu Yanyu",
    "Old Wang",
    "Dong Zhen",
    "Bai Zhu",
    "Li Fen",
    "Yan Ling",
    "Kai",
    "Mei Li",
]


def build_character_prompt(name: str, description: str, limit: int | None = None) -> str:
    """Compose the full positive CLIP prompt for one character.

    `description` may be truncated to `limit` characters (used by the legacy
    parse strategy) or left whole. Truncation defaults to 40 words for the
    "final" prompt style used by v2.
    """
    if limit is not None:
        description = description[:limit]
    return f"{BASE_POSITIVE}, character: {name}, {description}"


def safe_name(name: str) -> str:
    """Turn an arbitrary character name into a filesystem-safe slug."""
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name).replace(" ", "_")
