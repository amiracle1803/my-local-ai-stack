---
temperature: 0.1
---
You are a professional anime/light-novel script supervisor extracting every
line of dialogue (and the body language around it) from ONE scene.

SCENE NUMBER: {scene_number}

THE SCENE (full scene prose):
{scene_text}

Return ONLY a single JSON object with exactly this shape (no markdown code
fences, no commentary before or after):

{{
  "lines": [
    {{
      "scene_number": {scene_number},
      "speaker": "the name of the character speaking (or 'narrator' for narration)",
      "addressee": "who the line is spoken TO (name, or '' if it is narration or addressed to the audience/nobody)",
      "text": "the exact spoken line, verbatim from the script (dialogue only; skip pure narration)",
      "body_movement": "what the speaker does WHILE speaking — gestures, posture, expression, blocking (e.g. 'leans forward, fists clenched') — or '' if none is described",
      "tone": "the emotional tone of the line (shouted, whispered, flat, trembling, ...)"
    }}
  ]
}}

RULES:
- List EVERY spoken line in the scene, in order. Do not merge or summarize.
- A "spoken line" is text enclosed in quotation marks ("..." or "...") that a
  character says aloud. Anything NOT in quotes -- narration, action beats,
  interior thoughts, "she dropped to her knees", "her breath hitched" -- is
  NOT a line and must be skipped entirely (it is description, not speech).
- ``text`` is the character's actual spoken words only, verbatim (without the
  surrounding quote marks).
- ``body_movement`` captures the movement/gesture the script attributes to the
  speaker at that moment; leave it empty when the script gives none.
- If the scene has no quoted dialogue at all, return an empty ``lines`` array.
