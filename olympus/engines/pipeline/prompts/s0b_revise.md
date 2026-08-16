---
temperature: 0.5
max_tokens: 4096
---
You are revising ONE scene of an anime/light-novel episode based on targeted
guidance. Rewrite the FULL scene -- do not just patch the flagged parts in
isolation -- while preserving its events, characters, dialogue attribution,
present-tense third-person-limited narration, and its ending state (what
changed by the end of the scene).

CURRENT SCENE:
{scene_text}

GUIDANCE TO ADDRESS:
{guidance}

Output ONLY the revised scene's prose, complete and self-contained. No title,
no scene-number marker, no commentary, no markdown formatting, no preamble
like "Here is the revised scene".
