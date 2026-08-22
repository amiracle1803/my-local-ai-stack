---
temperature: 0.2
max_tokens: 2048
---
You are analyzing a single manga/anime panel for a story import pipeline. The
image is attached. Examine it carefully and describe ONLY what is visible.

PANEL FILENAME: {panel_name}
PANEL ORDER: {panel_order}

Return ONLY a single JSON object with exactly this shape (no markdown fences):

{{
  "panel_id": "{panel_id}",
  "characters": [
    {{
      "hair": "exact hair color/style",
      "eyes": "exact eye color/shape",
      "skin": "skin tone",
      "build": "body build",
      "clothing": "clothing colors and style -- be precise (this drives character identity)",
      "position_in_frame": "left/center/right/foreground/background",
      "specific_expression": "their expression"
    }}
  ],
  "action": "start state -> end state of what happens in this panel",
  "dialogue": [
    {{
      "speaker": "description of who speaks (e.g. 'girl with red hair on the left'), or 'narration'",
      "text": "exact bubble text, verbatim",
      "bubble_type": "speech|thought|narration|screaming"
    }}
  ],
  "mood": "one of: tense|peaceful|dramatic|action|emotional|mysterious|triumphant|ominous",
  "setting": {{
    "interior_exterior": "interior|exterior|abstract",
    "description": "the physical setting visible",
    "time_of_day": "morning|noon|afternoon|evening|night|unclear"
  }},
  "shot_type": "one of: wide|medium|close_up|detail|action",
  "panel_notes": "anything important: text panels, SFX, unusual composition, or 'unclear' if the image is blank/garbled"
}}

Rules:
- Exact dialogue text only -- no paraphrase.
- If the panel is blank/corrupted/illegible, set panel_notes to "unclear/garbled" and
  leave characters/dialogue empty. Do not invent content that is not visible.
