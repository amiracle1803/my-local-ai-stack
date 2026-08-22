---
temperature: 0.2
max_tokens: 2048
---
You are resolving character identity across a set of manga/anime panels. The
SAME person is often described differently across panels (hair color shifts,
clothing changes, different angles). Your job is to cluster these appearance
descriptions into unique individuals so the world bible does not create
duplicate entries for one person.

PER-PANEL CHARACTER DESCRIPTIONS:
{panel_characters_json}

Return ONLY a single JSON object with exactly this shape (no markdown fences):

{{
  "characters": [
    {{
      "provisional_id": "stable snake_case id like 'red_haired_girl' or 'hooded_man' -- never a real name yet",
      "canonical_appearance": "one consolidated appearance description (hair, eyes, build, clothing) that would match this person across panels",
      "appears_in_panels": ["panel_001", "panel_002"],
      "speaks_in_panels": ["panel_002"],
      "confidence": 0.0,
      "uncertainty_notes": "why this grouping is certain/uncertain -- e.g. 'hair shade differs but face + clothing match'"
    }}
  ],
  "uncertain_groupings": [
    {{
      "provisional_id": "candidate id",
      "reason": "why this grouping is uncertain -- the model could not decide if two descriptions are the same person",
      "candidates": ["panel_003", "panel_010"]
    }}
  ]
}}

Rules:
- Merge only descriptions that are plausibly the SAME person (consistent
  appearance features, not just the same position in frame).
- Do NOT merge two clearly distinct people (different hair, different face).
- Every panel's character descriptions must be assigned to exactly one
  character (or flagged in uncertain_groupings).
- Confidence: 0.0-1.0 how sure you are the grouping is correct.
