# Anime Pipeline v2 — Master Plan

> Captured 2026-07-09 from Amir's workflow spec. This is the reference contract
> for the Studio rebuild. v1 code (stages 0–2 partially implemented) lives at
> `E:\Projects\anime-pipeline-updated\anime-pipeline\anime-pipeline\`
> (`app/script_parser.py`, `app/scene_schema.py`, `app/shot_generator.py`,
> `app/llm_client.py`, `scripts/*`). Engine slot in this repo:
> `olympus/engines/pipeline/`.

## Global settings (chosen at project start)

- **FPS**: user-selectable 24–60, fixed per project, passed through to ComfyUI
  (respecting its constraints).
- **Long-form output**: support very long videos (up to ~11 hours) by breaking
  the workflow into smaller **scene blocks** rendered independently and
  chained (see Stage 3). Predict final MP4 duration + file size on the
  timeline before render.
- **Chunking**: use **chonkie** (free, already in stack requirements) for
  paragraph/script chunking — full script coverage, no truncation.
- **Blueprint**: a per-project blueprint file is created at intake and carried
  through every stage so later runs keep building on the same story.
  **Story-pollution guard**: every stage validates it is operating on the same
  story/project ID — no accidental mixing of stories.
- **Local-only**: Ollama for LLM calls, ComfyUI for images/video, Kokoro for
  TTS, ffmpeg for assembly.

## Stage 0 — Intake

- Input: `script.txt` (pasted or file).
- Create project folder + blueprint (story ID, FPS, style choice, contingency
  metadata).

## Stage 1 — World Bible

Reads **all** characters from the full script (chunked, no truncation):

- **Per-character profile extraction** — one LLM call per character.
- **World inference from evidence**: era/time period guessed from artifacts
  (smartphones → modern; advanced tech → futuristic; etc.), notable
  technology, magic vs non-magic system, government + class structure, how
  people live/eat/sleep, notable jobs/professions, economy.
- **World details**: setting locations, recurring elements/assets.
- **Character details**: physical description, clothing/outfits with
  **materials inferred from world details + character class**, outfit changes
  over time documented with pre-created references per outfit.
- **Relationship web**: list of characters + the relationship between each
  pair that interacts.
- **Contradiction detection** against the existing world bible +
  **deduplication**.
- **Creative expansion** of every character and world element.
- Output `world_bible.json`: every character/location has an `sd_prompt`
  appearance anchor.
- **Reference sheets**: 10+ reference images per character — full-body 360°
  turnarounds, all sides. Same rule for locations, settings, and assets.
- **Style lock**: pick the design style, generate 10+ style reference
  materials, train a **style-consistency LoRA** from them.
- **Voice ID logic**: assign a Kokoro voice per character (consistent for the
  whole project).
- Character identity resolution: full-script character stances, demeanor and
  mannerisms captured.

## Stage 2 — Screenplay

- **Prompt assembly**: character anchor + location anchor + composition →
  per-shot SD prompt.
- **Shot plan** (structure only).
- **Narration craft**: technique-rotated, rewrite-verified. If the story has
  an unexplained system (e.g. economy), the narrator briefly and concisely
  explains it as a narrative stop.
- **Dialogue craft**: character-voice-validated, deduplication-checked. A
  phrase a character says once in the story must not be overused.
- **Pacing**: spacing pauses between speeches that make sense (complex
  decisions → longer thinking pause before responding). Feed into LTX
  director settings.
- **Quality audit**: score all narrations, improve the 3 weakest.
- Output `screenplay.json`: every shot has `sd_prompt`, narration, dialogue.

## Stage 3 — Storyboard & Panels

- Scene-by-scene storyboard: character audio thoughts, facial movement
  changes, postures, lip-sync flags, character positioning + scene movement,
  recurring elements.
- **Block chaining for long videos**: generate the first part, then the
  ending, then everything in between; the **last frame of block N seeds
  block N+1** so scenes connect visually.
- **Panel organization**: individual and group analysis; reorganize one panel
  at a time; regenerate missing panels; review final flow piece by piece;
  panels can be **locked** for manual review/fixes.
- Scene + audio + dialogue reviews; characters reviewed on-model.

## Stage 3B — Image Generation (ComfyUI)

- One z-anime image per shot using the assembled SD prompt.
- Character appearance stays consistent because the **same world-bible
  sd_prompt anchor** is used every time (+ style LoRA).

## Stage 4 — Audio (Kokoro TTS)

- Narration lines + dialogue lines rendered per character voice assignment.
- Insert the Stage-2 pacing pauses.

## Stage 5 — Assembly (ffmpeg)

- Audio timed to image frames → preliminary panel video.
- Where video clips are generated, they replace panels after preliminary
  assembly; lip sync + character consistency checked.
- Start image and end image per clip, with dialogue.
- Clip chunking → stitch. Transitions subtle, never extreme.
- SFX only where needed. Background music: generated, non-copyrighted,
  quieter than the story.
- Timeline review → final MP4. Copyright check.
- Final timeline: **"keep info for next episode"** button; predicted MP4
  length + GB shown.

## Cross-cutting systems

- **Per-stage score checks, persistent** — every stage writes quality scores;
  structure-break detection reports if any step was skipped.
- **Prompt review & enhancer** + prompt adherence rules and checks.
- **Model & LoRA testing/training flow**: settings sweeps, model stress
  tests, generation speed comparison, contingency when a model fails (stop +
  report, fall back). Parts that pass checks against parameters are made into
  LoRAs.
- **Web UI** (Studio page): project organization — characters, assets, info
  storage, software models.

## Immediate next steps

1. Port v1 code from `E:\Projects\anime-pipeline-updated` into
   `olympus/engines/pipeline/` and make it runnable against the stack venv.
2. Implement Stage 1 world-bible extraction per this spec (chonkie chunking,
   per-character calls, era inference, relationship web, sd_prompt anchors).
3. Wire Stage 3B to ComfyUI's API with the `--novram` profile and the
   generate-safe restart pattern (VRAM fragmentation note in CLAUDE.md).
