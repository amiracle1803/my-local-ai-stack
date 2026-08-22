---
temperature: 0.15
---
You are segmenting one chunk of a story script into SCENES. A scene boundary
is a change of location, a clear time skip, or a major cast change. This chunk
may start or end mid-scene -- include partial scenes at the edges anyway; a
merge pass will stitch them.

KNOWN LOCATIONS (use these ids when the scene matches; else "loc-other"):
{location_list}

KNOWN CHARACTERS (use these ids):
{character_list}

KNOWN SCENE SETTINGS (extracted at intake -- time of day / season / environment
per script scene; use them to set ``time_of_day`` and stay consistent, but do
not invent a setting the chunk does not show):
{scene_settings}

SCRIPT CHUNK:
{chunk_text}

Return ONLY a single JSON object with exactly this shape (no markdown fences):

{{
  "scenes": [{{
    "location_id": "loc-...",
    "characters": ["char-id-1", "char-id-2"],
    "summary": "2-3 sentence factual summary of what happens",
    "time_of_day": "morning|day|evening|night|unclear",
    "opens_mid_scene": false,
    "ends_mid_scene": false
  }}]
}}
