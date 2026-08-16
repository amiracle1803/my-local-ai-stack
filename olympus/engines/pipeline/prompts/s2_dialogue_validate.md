# Stage 2 dialogue voice-validation

You validate dialogue lines for TTS rendering compatibility. Each line will be
synthesized by Kokoro TTS. Flag any issues that would cause audible artifacts
or unnatural delivery.

## Per-shot validation items
For each shot with dialogue:

1. **Length check**: A line longer than 40 words gets a ``too_long`` flag.
   Kokoro 82M handles up to ~15 seconds; longer lines should be split at
   natural sentence boundaries.

2. **Punctuation check**: The line should end with ``.`` ``!`` ``?`` or ``"``.
   Missing terminal punctuation causes trailing audio glitches.

3. **Narration vs dialogue**: Mark the line as ``narration`` (inner) or
   ``dialogue`` (inner). Narration gets the _narrator mesh/splice voice;
   dialogue gets the assigned character voice. If both appear in one line,
   flag ``mixed_narration_dialogue``.

4. **Whispered/shouted markers**: If the screenplay marks a line with
   parenthetical delivery notes ``(whispered)`` ``(shouting)`` ``(trailing off)``
   ``(cutting in)`` or ``(inner thought)``, extract the delivery_spec into
   the per-line ``delivery`` field. Lines without markers get ``delivery: null``.

5. **Name-to-character mapping**: Verify every speaker name in the screenplay
   maps to a ``voice_profile`` (char-* id → VoiceSpec). Unknown characters
   get the narrator fallback.

## Output JSON schema
```json
{
  "shot_id": "...",
  "lines": [
    {
      "index": 0,
      "speaker": "character_name",
      "char_id": "char-01",
      "text": "The dialogue text.",
      "type": "dialogue",
      "delivery": null,
      "word_count": 5,
      "flags": [],
      "split_suggestion": null
    }
  ],
  "issues_found": 0
}
```

## Voice assignment reference (design §4.4.1)
- _narrator voice: `am_adam` with speed 1.0 (reserved, never assigned to characters)
- Character voices: assigned deterministically by the voice_client module
- The ``validate`` step only flags issues; it NEVER mutates voice assignments
