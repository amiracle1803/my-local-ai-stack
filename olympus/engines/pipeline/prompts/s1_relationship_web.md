---
temperature: 0.2
---
You are mapping the relationship between exactly two characters of a story,
using only the evidence excerpts below (sentences where both appear near each
other).

CHARACTER A: {char_a} ({role_a})
CHARACTER B: {char_b} ({role_b})

EVIDENCE (script sentences mentioning both):
{evidence_text}

Describe their relationship. If the evidence shows the relationship changing
over the story, record each change as an evolution point (approximate
position: "early", "middle", or "late"). If the evidence is too thin to
establish any relationship, set "type" to "unclear".

Return ONLY a single JSON object with exactly this shape (no markdown fences):

{{
  "type": "allies|rivals|enemies|family|mentor-student|romantic|strangers|unclear|other",
  "notes": "1-2 sentences grounded in the evidence",
  "evolves": [{{"at": "early|middle|late", "becomes": "new relationship type"}}]
}}
