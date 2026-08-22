---
temperature: 0.2
max_tokens: 4096
---
You are synthesizing a screenplay from analyzed manga/anime panels. Every panel
becomes EXACTLY ONE shot. Consecutive panels with the same setting form a
scene. Each shot gets narration (adding what the panel does not show),
resolved character dialogue, and an SD prompt for image generation.

PER-PANEL ANALYSES (vision pass output):
{panel_analyses_json}

RESOLVED CHARACTERS (provisional_id -> what they look like):
{characters_json}

Return ONLY a single JSON object with exactly this shape (no markdown fences):

{{
  "scenes": [
    {{
      "scene_id": "sc-001",
      "location": "inferred location name (a stable id like 'loc-hall')",
      "summary": "one-line summary of what happens in this scene",
      "time_of_day": "morning|noon|afternoon|evening|night|unclear",
      "shots": [
        {{
          "shot_id": "sh-001-01",
          "scene_id": "sc-001",
          "shot_type": "wide|medium|close_up|detail|action",
          "description": "start state -> end state (action-not-state)",
          "narration": "1-2 sentences adding what the panel does not show",
          "dialogue": [
            {{ "character_id": "provisional_id", "text": "exact line" }}
          ],
          "sd_prompt": "anime 2d illustration prompt: characters (appearance) + setting + composition, no camera words",
          "source_panel": "panel_001"
        }}
      ]
    }}
  ]
}}

Rules:
- EVERY analyzed panel must appear as exactly one shot, in order. Missing
  panels get a minimal shot flagged in panel_notes.
- Dialogue text must be copied verbatim from the panel analysis (exact bubble text).
- Narration must not repeat what the panel shows -- it adds off-panel context,
  stakes, or emotional subtext.
- Do not use clichéd narration openers like "little did they know" or "in a
  world where".
- Characters in dialogue use their provisional_id from the resolved characters.
- `sd_prompt` for each shot: 40-60 words, appearance-only character anchors
  first, then setting, then composition. End with "anime 2d illustration,
  manga panel style, high quality linework, cel shading".
