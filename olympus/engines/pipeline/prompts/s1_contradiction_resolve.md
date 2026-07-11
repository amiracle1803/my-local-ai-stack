---
temperature: 0.1
---
Two extracted facts about the same subject in one story contradict each other.
Resolve the contradiction by majority evidence: whichever claim the script
excerpts support more strongly wins. This is a tie-break call -- be decisive.

SUBJECT: {subject}
FIELD: {field}
CLAIM 1: {claim_1}
CLAIM 2: {claim_2}

SCRIPT EVIDENCE:
{evidence_text}

Return ONLY a single JSON object with exactly this shape (no markdown fences):

{{
  "winner": 1,
  "resolved_value": "the winning claim's value, possibly cleaned up",
  "reason": "one sentence citing the deciding evidence"
}}
