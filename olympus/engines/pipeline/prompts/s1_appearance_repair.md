---
temperature: 0.2
---
You are completing a character's physical appearance for an anime story bible.
Some appearance fields came back empty or "none" and MUST be filled.

CHARACTER NAME: {character_name}

PASSAGES MENTIONING THIS CHARACTER:
{context_block}

CURRENT APPEARANCE (some fields are missing/empty and need values):
{current_appearance}

FIELDS THAT STILL NEED A CONCRETE VALUE: {missing_fields}

Return ONLY a single JSON object with exactly these six keys, every one a
concrete non-empty value (never "none"/"unknown"/blank):

{{
  "hair": "hair color + length/style",
  "eyes": "eye color/shape",
  "skin": "skin tone",
  "build": "body build",
  "clothing_primary": "default outfit",
  "distinguishing_feature": "one clear visual marker"
}}

For fields already grounded in the passages, keep the existing value. For the
missing fields, invent something vivid and genre-appropriate that fits this
character's role and the world implied by the passages. Do not contradict any
detail the passages state. Prefer saturated, memorable colors (crimson,
aqua, violet, emerald, gold) over plain "dark", "grey", or "black"; characters
should read as clearly colored, not monochrome.
