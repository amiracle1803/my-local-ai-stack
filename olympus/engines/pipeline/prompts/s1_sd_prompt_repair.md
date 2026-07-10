---
temperature: 0.2
---
You are rewriting a Stable Diffusion appearance prompt for an anime character
so it meets strict formatting rules.

CHARACTER NAME: {character_name}

EXACT APPEARANCE FACTS TO USE (reuse these adjectives verbatim):
{appearance_facts}

CURRENT PROMPT (needs fixing):
{sd_prompt}

WHAT IS WRONG: {issues}

Rewrite the prompt so that it:
- is between 40 and 60 words (count carefully),
- describes ONLY physical appearance built from the appearance facts above,
- contains NO camera terms, NO lighting, NO mood, NO pose, NO scene/background,
  and NO quality tags (no "dramatic lighting", "cinematic", "detailed",
  "anime style", "dynamic pose", "high contrast", "background", "scene", etc),
- does NOT repeat any word or phrase to reach the length -- every clause must
  add a DISTINCT appearance detail; if you are short, add new concrete details
  (hair texture, eye shape, posture of dress, accessories) rather than
  restating ones already given,
- does NOT mention the word count anywhere.

Output ONLY the rewritten prompt text -- no JSON, no quotes, no preamble, no
commentary.
