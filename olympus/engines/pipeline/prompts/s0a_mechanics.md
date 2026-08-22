---
temperature: 0.1
max_tokens: 2048
---
You are a professional story analyst. Extract only the STRUCTURAL MECHANICS of
the following source text. Do NOT reproduce plot, characters, names, or
specific scenes -- only the abstract machinery the story runs on.

SOURCE TEXT (first portion):
{source_text}

Return ONLY a single JSON object with exactly this shape (no markdown fences):

{{
  "power_system_type": "what category (cultivation/LitRPG stats/magic system/ability-based/etc)",
  "power_mechanics": ["each specific rule of how the power works -- be precise"],
  "progression_model": "how characters grow stronger (training/leveling/awakening/consumption/etc)",
  "conflict_engine": "one of: zero-sum-competition / betrayal-from-within / external-invasion / internal-corruption / knowledge-vs-power / identity-dissolution",
  "conflict_specifics": "what makes this particular conflict work structurally -- not the characters, the tension",
  "protagonist_archetype": "one of: reluctant-hero / amoral-genius / underdog-overcomer / broken-redeemer / outsider-observer / chosen-by-circumstance",
  "protagonist_behavioral_pattern": "how the protagonist specifically responds to problems -- their decision-making pattern",
  "emotional_hooks": ["specific emotional pull the story uses -- be concrete"],
  "world_rules": ["internal logic rules that make the setting feel consistent"],
  "themes": ["idea or question the story explores"],
  "what_makes_it_original": "what genuinely distinguishes this from generic examples of the genre"
}}
