---
temperature: 0.1
---
You are a professional anime/light-novel production designer extracting a RICH
location dossier (with a full 360-degree view) from the script passages that
describe one setting.

LOCATION NAME: {location_name}

ALL PASSAGES DESCRIBING THIS LOCATION:
{context_block}

Return ONLY a single JSON object with exactly this shape (no markdown code
fences, no commentary before or after):

{{
  "id": "snake_case_id",
  "name": "{location_name}",
  "description": "a vivid 2-4 sentence description of the place (layout, materials, mood)",
  "interior_exterior": "interior | exterior | both",
  "time_of_day": "the primary time of day it is seen (dawn / morning / noon / afternoon / dusk / night) or 'varies'",
  "season": "the season the story takes place in (spring / summer / autumn / winter) or 'unspecified'",
  "weather": "typical weather (clear, overcast, snowing, raining, ...) or 'varies'",
  "lighting": "how the space is lit (natural sunlight, lanterns, neon, moonlight, ...)",
  "environment_features": ["concrete environment elements present — e.g. snow, pine trees, tall grass, cobblestone, sand, water, stone walls, foliage"],
  "recurring": true or false,
  "views_360": [
    {{ "angle": "a camera-angle label", "description": "what this angle shows, as a concrete image prompt fragment" }},
    ...
  ]
}}

360-VIEW RULES (important):
- Provide 4-6 angles that together give FULL spatial coverage of the location
  so an image model can render it from every direction. Use angle labels like:
  wide_establishing, medium_shot, closeup_counter, over_shoulder, top_down,
  reverse_angle, north, south, east, west, entrance, interior_facing, etc.
- Each description must be a self-contained, concrete image prompt fragment
  (naming the setting's key features) so it can be dropped directly into a
  diffusion prompt. Reuse the exact environment_features you listed above.
- If the script names a season/time/weather, keep those exact values. If it
  does not, choose a consistent, genre-appropriate default and keep it
  consistent with the other locations.
