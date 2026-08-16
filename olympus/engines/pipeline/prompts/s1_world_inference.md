---
temperature: 0.2
---
You are inferring the WORLD of a story from evidence in its text (design:
era guessed from artifacts -- smartphones => modern; spaceships => futuristic;
swords + no technology => fantasy-medieval; steam engines => industrial).

SCRIPT EXCERPTS (chunked evidence):
{evidence_text}

CHARACTERS ALREADY EXTRACTED (names + roles):
{character_summary}

KNOWN STORY LOCATIONS (from the scene plan -- the world's places):
{known_locations}

Infer the world. Every claim needs at least one short evidence quote from the
excerpts. If the text gives no evidence for a field, make the most
conservative genre-consistent inference and set its confidence below 0.5.

The known story locations above are the scene plan's authoritative places.
Keep EVERY one of them in your "locations" list with a real description and
evidence quote. Only omit a known location if the SCRIPT EXCERPTS show no
trace of it at all. Also add any further locations the excerpts mention that
are missing from the known list. This is what builds the story's usable world
space -- a movie needs its set dressing, not one room.

Return ONLY a single JSON object with exactly this shape (no markdown fences):

{{
  "era": {{"value": "modern|historical|fantasy-medieval|futuristic|industrial|other",
          "evidence": ["short quote 1", "short quote 2"], "confidence": 0.0}},
  "technology": ["notable technology 1", "notable technology 2"],
  "magic_system": {{"exists": false, "rules": "one-sentence summary or empty"}},
  "government": "one-sentence description",
  "class_structure": ["class or stratum 1", "class or stratum 2"],
  "daily_life": {{"food": "...", "sleep": "...", "professions": ["...", "..."]}},
  "economy": {{"system": "one-sentence description", "explained_in_story": false}},
  "locations": [{{"name": "Location Name", "description": "1-2 sentences",
                  "recurring": true, "evidence": "short quote",
                  "angles": ["wide_establishing", "medium_shot", "closeup_counter", "over_shoulder"],
                  "connections": [{{"target_location_id": "loc-other", "connection_type": "connected_by_path",
                                   "distance_description": "5 minutes walk", "travel_difficulty": "easy",
                                   "notes": "main path through town"}}]}}],
  "recurring_assets": [{{"name": "Asset Name", "category": "weapon|prop|vehicle|emblem|other",
                         "description": "1 sentence", "evidence": "short quote"}}]
}}
