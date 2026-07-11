---
temperature: 0.2
---
Score this narration line for an anime recap video, 0-100, using the rubric:
- Concreteness (0-25): specific, visual, filmable.
- Flow (0-25): reads aloud naturally, no tongue-twisters.
- Craft (0-25): the stated technique is actually executed.
- Freshness (0-25): no cliche, no generic filler.

TECHNIQUE CLAIMED: {technique}
LINE: {narration}

Return ONLY a single JSON object (no markdown fences):

{{"score": 0, "weakest_aspect": "concreteness|flow|craft|freshness", "note": "one sentence"}}
