# Anime Recap Pipeline v2 — Master Plan

Captured and structured from Amir's workflow notes (2026-07-08). This supersedes the
stage layout in PIPELINE_PLAN.md where they conflict. The manga-pipeline studio
(`olympus/engines/pipeline/mangapipeline try/`) is the implementation home; the
angelic harness provides scoring/verification patterns; ComfyUI is the render engine.

**Installed render assets (verified via ComfyUI API 2026-07-08):** RealVisXL V5
Lightning (SDXL), LTX-Video 2B v0.9.5, LoRAs: krea2_retroanime (style),
LTX ID/detailer/union-control. Kokoro TTS via voice studio. ffmpeg local.

---

## 1. Stage map

```
Stage 0  script.txt  (+ per-project settings: fps 24–60, style, episode id)
Stage 1  WORLD BIBLE — full-script character/world extraction (chunked, no truncation)
Stage 2  SCREENPLAY  — shots + assembled SD prompts + narration + dialogue + audits
Stage 3A REFERENCES  — character/location/asset sheets (10+ views, 360°) + style LoRA dataset
Stage 3B PANELS      — one image per shot (anchored prompts = consistency)
Stage 4  AUDIO       — Kokoro narration + per-character dialogue voices, pacing pauses
Stage 5  MOTION      — LTX image-to-video on key shots; lip-sync pass on speaking closeups
Stage 6  ASSEMBLY    — timeline → clips → transitions/music/SFX → MP4 + episode carry-over
```

Every stage: score check (0–1) persisted per stage per project; steps that get skipped
must be *reported* as skipped, never silent (harness doctrine: loud gaps).

## 2. Stage 1 — World bible (the foundation)

Input: full script, chunked with **Chonkie** (free, structure-aware) — ALL characters
read across ALL chunks; no truncation.

Extraction targets (each a typed section of `world_bible.json`):

- **World era & tech level** — inferred from artifacts: smartphones ⇒ modern; unnamed
  higher tech ⇒ futuristic; swords/candles ⇒ period. Record the *evidence* for the guess.
- **World systems** — magic vs non-magic, government + class structure, notable
  professions/hierarchies, how people live/eat/sleep, economy (if the story has an
  economic system that's unclear, queue a **concise narrator explainer** into Stage 2).
- **Locations** — setting list with visual anchors (sd_prompt each).
- **Characters** — per character (one extraction call each):
  - description + clothing/outfits, outfit *materials* derived from world era + class
  - demeanor & mannerisms; voice notes → **voice ID assignment** (Kokoro voice map)
  - `sd_prompt` appearance anchor (the consistency key used verbatim in every shot)
  - **outfit timeline**: clothing changes over story time, each variant pre-referenced
- **Relationship web** — edges between characters with type/strength/evidence.
- **Recurring elements/assets** — objects, motifs, props that must stay on-model.

Guards:
- **Contradiction detection** against the existing world bible before merge.
- **Deduplication** (same character under two names → identity resolution).
- **Project blueprint + contamination check**: every artifact stamped with project id;
  cross-project mixing is a hard error (stories must never pollute each other).

## 3. Stage 2 — Screenplay

- Shot plan (structure only) → per shot: scene, characters present, positioning,
  movement, composition.
- **SD prompt assembly** = character anchor(s) + location anchor + composition + style
  tag. Never free-written; always assembled from bible anchors.
- **Narration craft**: technique-rotated (vary rhetorical devices), rewrite-verified;
  quality audit improves the 3 weakest narrations per episode.
- **Dialogue craft**: character-voice-validated (matches demeanor/mannerisms),
  deduplication-checked — a signature phrase is used ONCE per story, not per scene.
- **Pacing**: explicit pause values between speeches — complex decisions get longer
  thinking pauses (feeds Stage 4 timing + Stage 5 direction).
- Output `screenplay.json`: every shot has sd_prompt, narration, dialogue, pause map.

## 4. Stage 3A — References & LoRA training lane

- Per character: **10+ reference images, full-body 360°** (front/back/sides/¾ views,
  plus outfit variants from the outfit timeline). Same rule for key locations/assets.
- **Style lane**: pick a design style; generate 10+ style-consistent assets → curated
  into a **LoRA training dataset** (with captions) → train style/character LoRA →
  qualification before use (harness training doctrine: eval-gated promotion).
- Model/LoRA test flow: settings sweeps, stress tests, generation-speed comparison,
  contingency when a model fails mid-run (fallback checkpoint), prompt review/enhancer
  with adherence checks.

## 5. Stage 3B–5 — Panels, audio, motion

- **Panels**: one image per shot via assembled prompt (+ character LoRA when trained).
  Panel org: individual + group analysis; reorganize one panel at a time; missing
  panels regenerated; final flow reviewed piece-by-piece with per-panel **lock** for
  manual review.
- **Audio**: Kokoro per voice map; narration + dialogue; pause map applied; dialogue
  flow test (scene read-through) before render.
- **Motion**: LTX-Video image-to-video on key shots. **Scene chaining**: generate the
  first block, then the ending, then in-betweens; the *last frame* of block N seeds
  block N+1 (start-image/end-image control via LTX ic/union-control LoRAs).
- **Lip sync**: speaking closeups get a lip-sync pass (LatentSync/Wav2Lip class tool —
  not yet installed; stage is built with a documented degraded mode = motion-only).
- **FPS & length**: project fps set at Stage 0 (24–60, ComfyUI-rule compliant). Long
  videos (up to ~11 h target) are produced by **chunked assembly** — the pipeline
  renders scene blocks independently and stitches; nothing ever holds a full video in
  memory/VRAM.

## 6. Stage 6 — Assembly & episode continuity

- Preliminary assembly uses panels; video clips *replace* panels as they render
  (clip-chunking), then: lip-sync/consistency checks against parameters.
- Transitions **subtle**, SFX only where needed, music = generated, non-copyright,
  quiet under narration.
- Timeline review → MP4; copyright check; predicted final length + GB shown before render.
- **Next-episode button**: carries forward world bible, voice map, LoRAs, style,
  unresolved threads.

## 7. One-click products (ComfyUI backend deliverables)

Each is a single command/button that runs to completion with sane defaults:

| Product | Engine | Notes |
|---|---|---|
| Text → Image | RealVisXL (+ retroanime LoRA opt.) | prompt or bible-assembled |
| Image → Image | RealVisXL i2i | restyle/fix panels |
| Image → Video (motion) | LTX-Video 2B | start/end-frame control, fps from project |
| Lip sync + audio | Kokoro + lipsync tool (degraded: motion-only) | speaking closeups |
| YouTube thumbnail | RealVisXL + text-overlay compositor | 1280×720, title text, face crop |
| LoRA dataset generator | RealVisXL batch + captioner | 360° character/style sheets |

Backend rules: query ComfyUI for available models (never hardcode), VRAM-safe
(sequential jobs, `--novram` conventions, restart-between-batches per CLAUDE.md),
every job logged + scored, notes/docs embedded in the system (`--help` + docs page).

## 8. Non-negotiables carried from the notes

1. Chunked, no-truncation script reading (Chonkie).
2. Character consistency via bible sd_prompt anchors used verbatim everywhere.
3. Score checks per stage, persisted; skipped steps loudly reported.
4. Contamination guard: one project = one story; blueprint enforced.
5. Panel-level manual lock; regeneration only for missing/failed panels.
6. Pauses proportional to cognitive weight of the reply.
7. Music quieter than story; subtle transitions; SFX sparingly.
8. Episode carry-over with size/length prediction.
