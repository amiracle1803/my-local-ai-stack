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
CHARACTER ACTION: {character_action}
POSITIONING: {positioning}
FACIAL EXPRESSION: {facial}
HAS DIALOGUE: {has_dialogue}

STRICT RULES:
- If CHARACTERS IN FRAME is a name (not "none"), the [character] slot MUST be
  that name followed by a concrete, visible action that matches the beat --
  e.g. "Kana turns her head", "Hana steps forward", "Kana reaches toward the
  shelf". Never write "none" when a character is named on screen.
- Derive the action from SHOT BEAT + CHARACTER ACTION + POSITIONING. If the
  beat only describes environment, still give the named character a small
  physical motion (looks up, turns, breathes, shifts weight, steps).
- The [motion] slot is only for environment elements (wind, water, fabric,
  light, leaves) -- always secondary to the character action.
- Under 30 words total. If HAS DIALOGUE, character action is "speaks" plus at
  most one small gesture.

Return ONLY the motion prompt, no commentary.
