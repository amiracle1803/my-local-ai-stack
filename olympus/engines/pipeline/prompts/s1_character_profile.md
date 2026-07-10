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
    "hair": "exact hair color + length/style",
    "eyes": "exact eye color/shape",
    "skin": "exact skin tone",
    "build": "exact body build (e.g. slender, athletic, stocky)",
    "clothing_primary": "their default/most-worn outfit, concrete",
    "distinguishing_feature": "one unmistakable visual marker (scar, mark, prosthetic, etc)"
  }},
  "appearance_invented": true or false,
  "sd_prompt": "a single prose sentence or two, roughly 40-60 words, describing ONLY physical appearance (hair, eyes, skin, build, outfit, distinguishing features), reusing the exact adjectives you put in the appearance fields above. NO camera terms, NO lighting, NO mood, NO pose, NO quality tags (no 'dramatic lighting', 'cinematic', 'detailed', 'anime style', 'dynamic pose', 'high contrast', 'background', 'scene', etc). Do NOT mention the word count anywhere in the text",
  "voice_id_suggestion": "one voice id chosen from the VOICE TABLE below",
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

APPEARANCE RULES (important):
- EVERY appearance field must be a concrete, non-empty value. Never write
  "none", "unknown", or leave a field blank.
- Fill each field from the script passages where they describe it.
- Where the script gives NO information for a field, INVENT something ordinary
  and genre-appropriate that fits the character's role, personality, and the
  world implied by the passages (a plausible hair/eye/skin, a sensible build,
  a fitting outfit, one small distinguishing feature).
- Set `appearance_invented` to true if you invented ANY appearance detail that
  the script did not state; set it to false only if every appearance field is
  directly grounded in the passages.

VOICE TABLE (pick the single best-fitting id for `voice_id_suggestion`):
- Male + formal/deep -> am_eric, am_onyx
- Male + young/energetic -> am_adam, am_puck
- Male + villain/grave -> am_michael, am_fenrir
- Female + protagonist/warm -> af_heart, af_nova
- Female + cool/analytical -> af_jessica, af_kore
- Female + narrator-style -> af_bella, af_nicole
- British male -> bm_george, bm_lewis
- British female -> bf_emma, bf_isabella

Base non-appearance fields strictly on the passages given; use "none"/"unknown"
only for the non-appearance fields when they are not evidenced.
