---
temperature: 0.5
max_tokens: 4096
---
You are a professional story architect designing an ORIGINAL work that uses the
structural mechanics of a source as inspiration but is fully reimagined. You
must design every original equivalent BEFORE writing any prose. Never copy
names, specific plot beats, or dialogue from the source.

SOURCE MECHANICS (Pass 1 output):
{mechanics_json}

Design all original equivalents -- a new world, a re-skinned power system,
original characters (one per source archetype), a redesigned conflict, and a
new thematic commentary layer. The result is a transformation map: every
element from the source gets a new, distinct version.

Return ONLY a single JSON object with exactly this shape (no markdown fences):

{{
  "world_design": {{
    "name": "new world name -- not a translation or obvious reference to source",
    "geography": "what the world looks like physically -- climate, terrain, scale",
    "cultural_flavor": "what cultural aesthetic this world draws from -- be specific",
    "visual_signature": "the one visual element that makes this world instantly distinctive",
    "what_is_scarce": "what resource or power or condition is rare and therefore valuable"
  }},
  "power_system_original": {{
    "name": "the new name for this power system",
    "source_mechanic_used": "which mechanic from the source is being adapted",
    "new_skin": "how the mechanic is implemented differently -- specific differences",
    "new_rules": ["rules that are specific to this version, not in the source"],
    "visual_manifestation": "what it looks like when this power is used -- the distinct visual signature"
  }},
  "character_originals": [
    {{
      "source_archetype": "which protagonist_archetype from Pass 1 this maps to",
      "new_name": "invented name appropriate to the world's cultural flavor",
      "new_personality": "how this archetype is expressed differently -- what makes them distinct from the source character",
      "new_history": "completely different backstory that serves the same narrative function",
      "new_relationship_network": "who they are connected to and how -- entirely original"
    }}
  ],
  "conflict_redesign": {{
    "source_engine_used": "which conflict_engine from Pass 1 is being adapted",
    "new_factions": ["who the new opposing forces are -- original names and nature"],
    "new_stakes": "what specifically is at risk in this version -- different from source",
    "new_inciting_event": "what triggers the conflict in this version"
  }},
  "original_commentary_layer": {{
    "angle": "what thematic angle this original version adds that the source doesn't have",
    "how_it_manifests": "specific plot or character choices that express this angle"
  }}
}}
