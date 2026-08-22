---
temperature: 0.1
---
You are a professional anime/light-novel script supervisor extracting the
setting facts for ONE scene.

SCENE NUMBER: {scene_number}
SCENE TITLE: {scene_title}

THE SCENE (full scene prose):
{scene_text}

Return ONLY a single JSON object with exactly this shape (no markdown code
fences, no commentary before or after):

{{
  "number": {scene_number},
  "title": "{scene_title}",
  "location": "the name of the location this scene takes place in",
  "time_of_day": "dawn | morning | noon | afternoon | dusk | night | 'unspecified'",
  "season": "spring | summer | autumn | winter | 'unspecified'",
  "lighting": "how the scene is lit (sunlight, candlelight, neon, moonlight, ...)",
  "environment_features": ["concrete environment elements present in this scene — snow, grass, trees, rain, stone, water, ..."],
  "characters_present": ["names of every character present in this scene"]
}}

RULES:
- Extract ONLY what the scene text states or strongly implies. If time of day,
  season, or lighting are not stated, write "unspecified" / "varies" rather than
  inventing them.
- environment_features must be concrete nouns (snow, grass, trees, stone,
  water, fire, ...) — not moods or adjectives.
- characters_present lists every named character who appears, in order of first
  appearance.
