---
temperature: 0.5
max_tokens: 4096
---
You are writing ONE scene of a cinematic anime episode. This is not a summary -- write the scene as it plays on screen.

EPISODE CONTEXT (where this scene sits in the whole):
{three_act_summary}

THIS SCENE:
- Number: {scene_number}
- Title: {scene_title}
- Act: {act}
- Location: {location}
- Characters present: {characters_present}
- Emotional purpose (what the audience should feel and understand after this scene): {emotional_purpose}
- Narrative function (what story information this scene MUST deliver): {narrative_function}

CHARACTER PROFILES (speech style/personality/wants/fears for characters in this scene):
{character_profiles}

STYLE EXEMPLARS (match this tone/voice/pacing, do not copy content):
{style_exemplars}

TARGET LENGTH: about {word_target} words.

REQUIREMENTS:
- Present tense, third-person limited (anchor to ONE character's POV per scene)
- Open on ACTION or DIALOGUE -- never static description
- Every character speaks in their distinct voice (use their speech patterns, verbal tics, emotional tells)
- Include at least 2 lines of dialogue with clear attribution
- SHOW don't tell: use sensory detail (sound, light, texture, smell, temperature) over abstract narration
- End on a CLEAR BEAT CHANGE: decision made, secret revealed, relationship shifted, danger escalated, or question raised
- The scene's ending state MUST differ from its opening state

FORBIDDEN:
- No "the scene opens with" / "we see" / "the camera shows" meta-language
- No paragraph of pure exposition without character interaction
- No generic "he felt sad/she was angry" -- show it through action/dialogue/physical detail
- No scene ending on a static note

Output ONLY the scene's prose. No title, no scene-number marker, no commentary, no markdown.
