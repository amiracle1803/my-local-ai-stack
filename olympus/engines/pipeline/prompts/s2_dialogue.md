---
temperature: 0.4
---
You are writing the dialogue lines for ONE scene of an anime episode, staying
true to each character's established speech style. Use ONLY characters from
the speech style cards. Not every shot needs dialogue -- silence is fine.
Base the lines on what the scene summary says happens; do not invent new
plot events.

SCENE SUMMARY: {scene_summary}
SHOTS IN THIS SCENE (id + beat):
{shot_list}

SPEECH STYLE CARDS:
{style_cards}

Rules per line: match the character's register and patterns; a "clipped"
speaker stays under 20 words; a "verbose" speaker uses at least 6; mark
emotion; mark pause_class as one of: interruption, casual, considered,
complex_decision, dramatic_reveal.

Return ONLY a single JSON object with exactly this shape (no markdown fences):

{{
  "lines": [{{
    "shot_id": "sh-001-02",
    "char_id": "char-...",
    "text": "the spoken line",
    "emotion": "neutral|hesitant|angry|joyful|fearful|resolute|sad",
    "pause_class": "casual",
    "audio_thought": false
  }}]
}}
