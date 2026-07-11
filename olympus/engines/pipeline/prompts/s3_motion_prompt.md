---
temperature: 0.3
---
Write a motion prompt for an image-to-video model, using ONLY this grammar:
[camera: static|slow push-in|slow pull-back|pan-left|pan-right|handheld-subtle]
[motion: 2-3 physical elements that move, comma-separated]
[character: one clear action, or "none"]

SHOT COMPOSITION: {composition}
SHOT BEAT: {beat}
CHARACTERS IN FRAME: {characters}
HAS DIALOGUE: {has_dialogue}

Keep it under 30 words total. If the shot has dialogue, the character action
must be "speaks" plus at most one small gesture.

Return ONLY the motion prompt, no commentary.
