---
temperature: 0.5
max_tokens: 1500
---
You are writing ONE scene of an anime/light-novel episode. Write with full
attention on this scene alone -- do not summarize the rest of the episode.

EPISODE CONTEXT (where this scene sits in the whole):
{three_act_summary}

THIS SCENE:
- Number: {scene_number}
- Title: {scene_title}
- Act: {act}
- Location: {location}
- Characters present: {characters_present}
- Emotional purpose (what the audience should feel and understand after this
  scene): {emotional_purpose}
- Narrative function (what story information this scene must deliver):
  {narrative_function}

CHARACTER PROFILES (speech style/personality/wants/fears for the characters
present in this scene):
{character_profiles}

STYLE EXEMPLARS (match this tone/voice, do not copy the content):
{style_exemplars}

TARGET LENGTH: about {word_target} words.

Write the scene now as narrative prose, present tense, third-person limited.
Character dialogue in quotation marks, clearly attributed. Open on action or
dialogue rather than environment description. Include at least one line of
dialogue. End on a clear beat that has changed something from how the scene
opened (a decision made, information revealed, relationship shifted, or
danger escalated) -- the scene's ending state must be different from its
opening state.

Output ONLY the scene's prose. No title, no scene-number marker, no
commentary, no markdown formatting.
