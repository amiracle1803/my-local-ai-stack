#!/usr/bin/env python3
"""
prompts.py — turn parsed character JSON into ComfyUI-ready CLIP positive /
negative prompt pairs. Unifies the two generate_clip_prompts scripts (v1 used
`description_raw` capped at 300 chars; v2 used `description` capped at 40 words)
into one function parameterized by those choices.
"""

import json
from pathlib import Path
from typing import Dict

from . import config


def load_characters(path: Path) -> list:
    """Read a characters JSON ({"characters": [...]}) and return the list."""
    return json.loads(path.read_text(encoding="utf-8"))["characters"]


def build_prompts(
    characters: list,
    desc_field: str = "description",
    word_limit: int | None = None,
    char_limit: int | None = None,
) -> Dict[str, Dict[str, str]]:
    """Build {name: {positive, negative}} CLIP prompts for each character.

    The description is pulled from `desc_field` and truncated either to a
    number of `word_limit` words or `char_limit` characters (whichever is set).
    """
    prompts = {}
    for c in characters:
        name = c["name"]
        desc = c.get(desc_field) or ""
        if word_limit:
            desc = " ".join(desc.split()[:word_limit])
        elif char_limit:
            desc = desc[:char_limit]
        prompts[name] = {
            "positive": config.build_character_prompt(name, desc),
            "negative": config.BASE_NEGATIVE,
        }
    return prompts


def main(input: str, output: str, desc_field: str = "description",
         words: int | None = None, chars: int | None = None) -> int:
    """CLI entry: read characters JSON, write CLIP prompts JSON."""
    prompts = build_prompts(load_characters(Path(input)), desc_field, words, chars)
    out = Path(output)
    out.write_text(json.dumps(prompts, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated prompts for {len(prompts)} characters -> {out}")
    return 0
