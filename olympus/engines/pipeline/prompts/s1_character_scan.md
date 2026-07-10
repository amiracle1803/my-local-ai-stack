---
temperature: 0.1
---
You are doing a careful full-text character inventory pass over one chunk of
a longer script. This chunk may start or end mid-scene -- that is expected.

SCRIPT CHUNK:
{chunk_text}

List every character name mentioned in this chunk, including shortened names,
nicknames, and titles used to refer to a person (e.g. "the old sage", "Captain
Rell"). Do not include the narrator unless the narrator is a named character
in the story. Do not include generic group references ("the villagers", "the
guards") unless a specific individual is named.

Return ONLY a single JSON object with exactly this shape (no markdown code
fences, no commentary before or after):

{{
  "names": ["Name One", "Name Two"]
}}

If no character names appear in this chunk, return {{"names": []}}.
