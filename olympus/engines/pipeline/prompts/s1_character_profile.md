---
temperature: 0.1
---
You are a professional anime/light-novel story bible editor extracting a
character profile from every passage in the script that mentions them.

CHARACTER NAME: {character_name}

ALL PASSAGES MENTIONING THIS CHARACTER (sentences that name them, plus the
following sentence when it continues about them with a pronoun):
{context_block}

Return ONLY a single JSON object with exactly this shape (no markdown code
fences, no commentary before or after):

{{
  "name": "{character_name}",
  "aliases": ["any shortened names, nicknames, or titles used for them"],
  "appearance": {{
    "hair": "exact, thumbnail-recognizable description",
    "eyes": "exact, thumbnail-recognizable description",
    "skin": "exact, thumbnail-recognizable description",
    "build": "exact, thumbnail-recognizable description",
    "clothing_primary": "their default/most-worn outfit, exact",
    "distinguishing_feature": "one unmistakable visual marker (scar, mark, prosthetic, etc), or 'none' if none is stated"
  }},
  "sd_prompt": "40-60 words describing ONLY appearance (hair, eyes, build, outfit, distinguishing features) for a diffusion model -- no camera angles, no scene/lighting/action description",
  "speech_style": {{
    "category": "one short label for how they talk (e.g. terse, formal, sarcastic, warm)",
    "avg_words_per_line": "short | medium | long",
    "vocabulary_register": "e.g. plain, formal, archaic, slangy",
    "distinctive_patterns": "verbal tics, catchphrases, or speech habits, or 'none' if none is evident"
  }},
  "personality": {{
    "traits": ["5 specific behavioral-pattern traits, not generic adjectives"],
    "core_drive": "what fundamentally motivates them",
    "core_fear": "what they are most afraid of"
  }},
  "role": "protagonist | antagonist | mentor | ally | obstacle | neutral",
  "arc_this_episode": {{
    "starts": "where they are emotionally/situationally at the start of what you've read",
    "ends": "where they are by the end of what you've read -- must differ from the start if the text shows change, otherwise repeat the start"
  }},
  "first_episode": "a short label for the episode/story this text is from, or 'unknown' if not stated"
}}

Base every field strictly on the passages given. If a field is not evidenced
in the text, use an empty string, "none", or "unknown" rather than inventing
detail that contradicts the source.
