---
temperature: 0.1
---
You are a professional anime/light-novel story bible editor extracting a RICH
character dossier from the script passages that mention one character.

CHARACTER NAME: {character_name}

ALL PASSAGES MENTIONING THIS CHARACTER (sentences that name them, plus the
following sentence when it continues about them with a pronoun):
{context_block}

Return ONLY a single JSON object with exactly this shape (no markdown code
fences, no commentary before or after):

{{
  "name": "{character_name}",
  "role": "protagonist | antagonist | mentor | ally | obstacle | neutral",
  "gender": "male | female | nonbinary | unknown",
  "race": "species/race/ethnicity (e.g. human, elf, android, 'half-elf'); 'unknown' if never stated",
  "age": "concrete or an age band (e.g. '17', 'mid-20s', 'elderly'); 'unknown' if never stated",
  "height": "concrete if stated (e.g. 'tall', '5'8', 'shorter than average'); 'unknown' otherwise",
  "body_build": "slender / athletic / stocky / wiry / heavyset / petite / ...; 'unknown' if never stated",
  "hair": {{
    "color": "exact color (crimson, aqua, raven-black, ...)",
    "length": "buzz cut / short / shoulder-length / waist-length / ...",
    "style": "straight / wavy / twin tails / messy / braid / ..."
  }},
  "eyes": "exact eye color",
  "skin": "exact skin tone",
  "clothing": "their default/most-worn outfit, concrete (garments + colors)",
  "distinguishing_features": "one unmistakable visual marker (scar, mark, prosthetic, accessory) or 'none'",
  "appearance_summary": "a single vivid paragraph (60-100 words) describing their full appearance — hair, eyes, skin, build, outfit, distinguishing features — reusing the exact adjectives above",
  "personality_traits": ["5 specific behavioral-pattern traits, not generic adjectives"],
  "key_skills": ["what they are notably good at (combat, magic, hacking, cooking, ...) or 'none evidenced'"],
  "behavioral_patterns": ["2-4 recurring habits/reactions (how they respond to stress, authority, strangers)"],
  "family_background": "their family history / upbringing / home life; 'unknown' if never stated",
  "general_background": "their backstory and life situation before the story (occupation, origin, past events)",
  "friends": ["names of people they are friends with (from the passages)"],
  "family": [
    {{ "name": "relative name", "relation": "mother / older brother / adoptive father / ..." }}
  ],
  "relationships": [
    {{ "other_name": "other character's name", "type": "friend | rival | mentor | romantic interest | enemy | ...", "description": "how they feel about / interact with that person" }}
  ],
  "wants": "what they want this episode/story",
  "fears": "what they are most afraid of",
  "arc_end": "where they end up emotionally/situationally by the end of the passages"
}}

RULES (important):
- Base every field on the passages given. For any fact the script does NOT
  state, write "unknown" (or "none" / an empty list) -- do NOT invent backstory.
- The ONE exception is color-poor appearance: if the script never names a hair
  or eye color, choose a vivid, genre-appropriate saturated color (crimson,
  aqua, violet, emerald, ...) so the character reads as clearly colored, never
  grey. Do this ONLY for hair.color / eyes / skin when those are missing.
- Friends / family / relationships: only list people who appear or are clearly
  referenced in the passages. Do not fabricate relatives.
