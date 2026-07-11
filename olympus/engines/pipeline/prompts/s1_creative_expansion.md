---
temperature: 0.5
---
You are enriching a thin entry in a story's world bible. Everything you
invent must be consistent with the story's world and NEVER contradict the
existing facts below. Invented material should feel inevitable, not random.

WORLD SUMMARY:
{world_summary}

ENTRY TYPE: {entry_type}
ENTRY NAME: {entry_name}
EXISTING FACTS (canon -- do not contradict):
{existing_facts}

THIN FIELDS TO ENRICH: {thin_fields}

Return ONLY a single JSON object mapping each thin field name to its enriched
value (strings; 1-3 sentences each). No markdown fences, no commentary:

{{
  "field_name": "enriched value"
}}
