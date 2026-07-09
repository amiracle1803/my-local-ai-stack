# Anime Pipeline v2 — Detailed Design (Build Contract)

> **Status: PLANNING — do not execute yet.**
> This document is the build contract. It is written so that any capable
> model/developer can implement it without asking questions. Companion
> overview: `anime-pipeline-v2-plan.md`. Hardware target: RTX 4070 Laptop
> 8 GB VRAM, 32 GB RAM, Windows 11, fully local.
>
> **Builder handoff rules (read first):**
> 1. Implement milestone by milestone (M0→M8, bottom of doc). Never skip a gate.
> 2. Every stage writes its scorecard before the next stage may start.
> 3. All LLM calls go through `PipelineLLM` (retry + JSON-repair wrapper).
> 4. All ComfyUI calls go through `ComfyClient` (VRAM-safe, auto-restart).
> 5. Follow the repo's CLAUDE.md rules: minimal diffs, Pydantic models,
>    no cloud calls, run `scripts\backup-code.ps1` after each milestone.

---

## 1. Architecture

```
olympus/engines/pipeline/
├── pipeline/                    # python package
│   ├── __init__.py
│   ├── config.py                # PipelineConfig (pydantic-settings, reads pipeline.toml)
│   ├── llm.py                   # PipelineLLM: Ollama chat + JSON schema enforcement
│   ├── chunking.py              # chonkie wrappers (script + paragraph chunkers)
│   ├── blueprint.py             # Blueprint model + story-pollution guard
│   ├── scores.py                # persistent per-stage scorecards (sqlite)
│   ├── stage0_intake.py
│   ├── stage1_worldbible.py
│   ├── stage1r_references.py
│   ├── stage2_screenplay.py
│   ├── stage3_storyboard.py
│   ├── stage3b_images.py
│   ├── stage4_audio.py
│   ├── stage5_assembly.py
│   ├── comfy_client.py          # ComfyUI HTTP/WS client + workflow templates
│   ├── voice_client.py          # Voice Studio (:5050) client
│   ├── model_lab.py             # model/LoRA testing + training harness
│   └── schemas/                 # pydantic models == JSON contracts (section 3)
├── workflows/                   # ComfyUI workflow JSON templates
│   ├── character_sheet.json     # 360 turnaround grid
│   ├── panel_txt2img.json
│   ├── panel_img2img_lastframe.json
│   └── lora_dataset_prep.json
├── prompts/                     # every LLM prompt as a .md file, versioned
│   ├── s1_character_discovery.md
│   ├── s1_character_profile.md
│   ├── s1_world_inference.md
│   ├── s1_relationship_web.md
│   ├── s1_contradictions.md
│   ├── s1_creative_expansion.md
│   ├── s2_shot_plan.md
│   ├── s2_narration.md
│   ├── s2_narration_rewrite.md
│   ├── s2_dialogue.md
│   ├── s2_dialogue_validate.md
│   └── s2_quality_audit.md
├── projects/<story-slug>/       # all per-project artifacts (section 2)
├── pipeline.toml                # engine config
├── run.py                       # CLI: python run.py <project> <stage|all> [--resume]
└── tests/                       # pytest per stage (golden-file based)
```

**Process model**: single Python process per stage run. Stages are resumable
and idempotent — each writes artifacts + a `stage.done` marker; `--resume`
skips completed units (per character / per shot / per block, not just per
stage). The kernel's Tasks API can trigger stage runs later (out of scope
for first build).

**GPU scheduling rule**: never run Ollama generation and ComfyUI generation
simultaneously. Stages are sequenced so LLM-heavy stages (1, 2, 3) fully
finish before image stages (1R, 3B). Kokoro runs on CPU so Stage 4 may
overlap with 3B. `ComfyClient` checks `nvidia-smi` free VRAM before queueing
and asks Ollama to unload (`keep_alive: 0` on last call) when transitioning.

## 2. Project directory layout (per story)

```
projects/<slug>/
├── blueprint.json               # section 3.1 — identity + settings + stage ledger
├── input/script.txt
├── worldbible/
│   ├── world_bible.json         # 3.2
│   ├── contradictions.json      # unresolved flags for user review
│   └── refs/<char-or-asset>/    # 10+ PNGs each + manifest.json
├── screenplay/screenplay.json   # 3.3
├── storyboard/storyboard.json   # 3.4 (scene blocks, panel status/locks)
├── panels/<block>/<shot-id>.png # + <shot-id>.json sidecar (seed, prompt, score)
├── audio/
│   ├── narration/<shot-id>.wav
│   └── dialogue/<shot-id>_<line>.wav
├── video/
│   ├── clips/<block>.mp4        # per-block renders
│   └── final.mp4
├── timeline.json                # 3.5
├── scores.sqlite                # persistent scorecards, all stages
└── logs/<stage>_<ts>.log
```

## 3. Data contracts (Pydantic models, serialized as JSON)

### 3.1 `blueprint.json` — project identity + pollution guard
```jsonc
{
  "story_id": "uuid4",                  // NEVER changes after intake
  "slug": "my-first-story",
  "title_hash": "sha256 of normalized first 2k chars of script",
  "created": "iso8601",
  "fps": 24,                            // 24–60, fixed at intake
  "style": {"name": "z-anime", "lora": null, "negative": "..."},
  "target": {"resolution": [1280, 720], "max_block_seconds": 90},
  "stages": {                           // ledger — structure-break detection
    "stage0": {"status": "done", "ts": "...", "score": 100},
    "stage1": {"status": "pending"}, ...
  }
}
```
**Pollution guard**: every stage recomputes `title_hash` from
`input/script.txt` and aborts with a clear error if it differs from the
blueprint — the script was swapped mid-project. Every artifact embeds
`story_id`; loaders verify it.

### 3.2 `world_bible.json`
```jsonc
{
  "story_id": "...",
  "world": {
    "era": {"value": "modern|historical|fantasy-medieval|futuristic|...",
             "evidence": ["smartphone in ch.1", ...], "confidence": 0.0-1.0},
    "technology": ["..."], "magic_system": {"exists": true, "rules": "..."},
    "government": "...", "class_structure": ["..."],
    "daily_life": {"food": "...", "sleep": "...", "professions": ["..."]},
    "economy": {"system": "...", "explained_in_story": false},  // false → Stage 2 narrator stop
    "locations": [{"id": "loc-academy", "name": "...", "description": "...",
                   "sd_prompt": "...", "recurring": true}],
    "recurring_assets": [{"id": "asset-...", "name": "...", "sd_prompt": "..."}]
  },
  "characters": [{
    "id": "char-rin", "name": "Rin", "aliases": ["the red witch"],
    "role": "protagonist|support|minor",
    "profile": {"age": "...", "personality": "...", "demeanor": "...",
                 "mannerisms": ["..."], "stances": "full-script summary"},
    "appearance": {"base": "...", "sd_prompt": "1girl, red hair, ...",  // THE anchor
                    "outfits": [{"id": "outfit-1", "desc": "...", "material": "wool (peasant class)",
                                 "sd_prompt": "...", "active_from_scene": 1}]},
    "voice": {"engine": "kokoro", "voice_id": "af_bella", "speed": 1.0},
    "first_scene": 1, "last_scene": 42
  }],
  "relationships": [{"a": "char-rin", "b": "char-kai",
                      "type": "rivals-to-allies", "notes": "...",
                      "evolves": [{"scene": 12, "becomes": "allies"}]}]
}
```

### 3.3 `screenplay.json`
```jsonc
{
  "story_id": "...",
  "scenes": [{
    "id": "sc-001", "location": "loc-academy", "characters": ["char-rin"],
    "summary": "...", "positioning": "...", "movement": "...",
    "shots": [{
      "id": "sh-001-01",
      "sd_prompt": "<char anchor> + <outfit> + <location anchor> + <composition>",
      "composition": "wide shot, low angle",
      "narration": {"text": "...", "technique": "foreshadow|sensory|...", "score": 87},
      "dialogue": [{"char": "char-rin", "text": "...",
                     "pause_before_ms": 1400,      // thinking pauses
                     "emotion": "hesitant", "audio_thought": false}],
      "facial": "...", "posture": "...", "lipsync": true,
      "duration_s": 6.5                             // estimated from audio at assembly
    }]
  }]
}
```

### 3.4 `storyboard.json` — blocks + panel state machine
```jsonc
{
  "story_id": "...", "fps": 24,
  "blocks": [{                       // long-video unit; ≤ max_block_seconds
    "id": "blk-001", "shots": ["sh-001-01", ...],
    "order": "first|ending|infill",  // generation order: first part → ending → in-betweens
    "seed_frame": null | "panels/blk-000/sh-000-09.png",  // last frame of previous block
    "status": "pending|generated|reviewed|locked"
  }],
  "panels": {"sh-001-01": {"status": "pending|generated|flagged|regenerating|locked",
                            "locked_by": null, "issues": []}}
}
```

### 3.5 `timeline.json`
```jsonc
{
  "story_id": "...",
  "entries": [{"shot": "sh-001-01", "start": 0.0, "end": 6.5,
                "panel": "panels/blk-001/sh-001-01.png",
                "clip": null,                       // replaces panel when video generated
                "audio": ["audio/narration/sh-001-01.wav"],
                "transition": "cut|fade-200ms"}],
  "music": {"file": "audio/music/bg-01.wav", "gain_db": -18},  // always quieter than speech
  "sfx": [{"file": "...", "at": 12.3}],
  "predicted": {"duration_s": 5400, "size_gb": 3.2},
  "next_episode": {"carry": true, "notes": "..."}   // the carryover button writes this
}
```

## 4. Stage designs

### Stage 0 — Intake (`stage0_intake.py`)
1. CLI/UI accepts script text + choices: `fps` (24–60), style preset,
   resolution. Validate fps against ComfyUI/LTX constraints (integer, and
   video models are trained at fixed rates — snap to nearest of 24/30/60
   with a warning).
2. Create project dir, write `blueprint.json`, copy `script.txt`.
3. Chunk sanity pass: run chonkie `SentenceChunker` (target 1200 tokens,
   overlap 120) and store chunk count/offsets in blueprint for reproducible
   chunking downstream. **No truncation ever** — if a chunk API fails, split
   recursively.
4. Scorecard: script length, chunk count, encoding issues found.

### Stage 1 — World bible (`stage1_worldbible.py`)
Order of operations (all via `PipelineLLM`, model role `worker`):
1. **Character discovery**: map over ALL chunks → per-chunk character
   mentions (name, aliases, evidence quote). Reduce: merge by
   fuzzy-name match (rapidfuzz ratio ≥ 88 → same character; log merges).
2. **Identity resolution**: for each merged character, collect all evidence
   quotes; one call resolves aliases, demeanor, mannerisms, full-script stance.
3. **Per-character profile**: ONE call per character with its evidence pack →
   3.2 character object (minus sd_prompt).
4. **World inference**: dedicated calls for era (evidence-based: artifacts
   like smartphones ⇒ modern; spaceships ⇒ futuristic; swords+no-tech ⇒
   medieval — prompt lists the heuristic table), technology, magic system,
   government/class, daily life, economy (+`explained_in_story` flag),
   locations, recurring assets.
5. **Relationship web**: pairwise only for characters that co-occur in ≥1
   chunk (avoid N² blowup). Output edges + evolution points.
6. **Contradiction detection**: compare new extraction against existing
   `world_bible.json` if re-running; also self-consistency (same character,
   conflicting hair color across chunks). Write `contradictions.json`;
   blocking contradictions (appearance conflicts) must be auto-resolved by a
   tie-break call (majority evidence wins) or flagged for the user.
7. **Deduplication**: characters, locations, assets — fuzzy-merge, keep ids stable.
8. **Creative expansion**: one call per character + one per world element to
   enrich thin entries (marked `expanded: true` so canon vs invented is
   traceable).
9. **sd_prompt synthesis**: per character/outfit/location — deterministic
   template: `[quality tags], [subject tags from profile], [outfit tags],
   [style tokens]`. Validated: ≤ 60 tokens, no conflicting tags (tag
   conflict table in `prompts/`).
10. Scorecard: characters found, profiles complete %, contradictions open,
    avg confidence.

### Stage 1R — References (`stage1r_references.py`) [GPU]
1. For each character×outfit: generate **10+ reference images** via
   `workflows/character_sheet.json` — 8-view 360° turnaround grid (front,
   3/4L, side L, back-3/4L, back, back-3/4R, side R, 3/4R) + 2 expression
   sheets. Fixed seed per character (stored) for reproducibility.
2. Same for each recurring location + asset (4+ angles).
3. **Style lock**: generate 10+ style reference images from style preset;
   prepare LoRA dataset (`lora_dataset_prep.json` — captions via WD14 tagger
   node); train style LoRA with kohya_ss CLI (checkpoint in
   `E:\AI\Models\loras\<slug>-style.safetensors`). Training config:
   rank 16, ~1500 steps, batch 1, fp16 — fits 8 GB.
4. **Voice assignment**: rule-based first (gender/age/personality → Kokoro
   voice table), then one LLM call to sanity-check distinct voices for
   frequently co-speaking characters (no two mains share a voice).
5. VRAM discipline: `ComfyClient` restarts ComfyUI every N=5 generations
   (CLAUDE.md fragmentation note); Ollama unloaded during this stage.
6. Scorecard: refs per character (target ≥10), failed generations, LoRA loss.

### Stage 2 — Screenplay (`stage2_screenplay.py`)
1. **Scene segmentation**: reuse v1 `script_parser.py` logic (port from
   E:\Projects\anime-pipeline-updated) upgraded to chunked full coverage.
   Scene = location/time/cast change.
2. **Shot plan**: per scene, structure-only call → list of shots with
   composition + who is on screen + positioning/movement.
3. **Prompt assembly** (no LLM): `sd_prompt = char_anchor(s) + outfit(scene)
   + location_anchor + composition + style tokens`. Outfit selected by
   `active_from_scene`. Deterministic, unit-tested.
4. **Narration craft**: per shot, technique-rotated (cycle: sensory detail →
   character interiority → foreshadow → plain action → world texture; no
   technique twice in a row). Then **rewrite-verify** call: rewrite if the
   first draft fails checks (length 15–45 words, no passive-voice openers,
   no repeated opener from previous 3 shots).
   Economy/world exposition: if `explained_in_story == false` and scene
   first touches money/system, insert one concise narrator stop (≤ 25 words).
5. **Dialogue craft**: per shot from script lines; **voice validation** call
   scores each line against the character's demeanor/mannerisms (regenerate
   if score < 70); **dedup check**: signature phrases (extracted in Stage 1)
   may appear at most once in the whole screenplay — later hits are rewritten.
6. **Pacing pauses**: rule table → `pause_before_ms` (complex decision 1200–
   2000 ms, casual reply 200–400 ms, interruption 0). Flag lipsync shots.
7. **Quality audit**: score every narration 0–100 (rubric prompt);
   rewrite the 3 lowest-scoring; re-score; persist both scores.
8. Scorecard: shots, avg narration score before/after audit, dialogue
   regen count, dedup hits fixed.

### Stage 3 — Storyboard & blocks (`stage3_storyboard.py`)
1. Partition shots into **blocks** ≤ `max_block_seconds` (estimated from
   text length at ~150 wpm until real audio exists; re-partitioned after
   Stage 4 if a block overflows 20%).
2. Set generation order: `first` block, then `ending` block, then `infill`
   blocks — matching Amir's spec (start + destination anchor the middle).
3. Each block records `seed_frame` = last panel of the previous block
   (once generated) for img2img continuity in 3B.
4. Storyboard detail per shot: facial change notes, posture, character
   audio-thoughts (rendered as inner-voice narration), movement.
5. **Panel state machine**: pending → generated → (flagged → regenerating →
   generated) → reviewed → locked. Locked panels are never touched by
   automation. Missing panels (file lost/corrupt) auto-detected → regenerated.
6. Scorecard: blocks, shots/block distribution, estimated total duration
   (validates the 11-hour ceiling: blocks × block_seconds; warn > 11 h).

### Stage 3B — Images (`stage3b_images.py`) [GPU]
1. Per shot (skip locked): txt2img via `panel_txt2img.json`, or
   img2img via `panel_img2img_lastframe.json` when the shot opens a block
   with a `seed_frame` (denoise 0.55 — keeps composition continuity without
   copying content).
2. Inputs: assembled sd_prompt + style LoRA + fixed per-character seeds
   blended by hashing shot id (reproducible; stored in the sidecar json).
3. **Prompt adherence check**: CLIP-score panel vs prompt (comfy node or
   local open_clip); score < threshold → one auto-retry with enhanced prompt
   (prompt-enhancer call), else flag in storyboard.
4. Consistency check: character embedding similarity vs reference sheet
   (insightface/ArcFace on anime faces is weak — use CLIP image-image
   similarity vs the character's front reference; < threshold → flag).
5. VRAM discipline as Stage 1R. Progress persisted every panel (resume-safe).
6. Scorecard: panels generated, retry rate, adherence avg, consistency avg.

### Stage 4 — Audio (`stage4_audio.py`) [CPU]
1. Narration per shot → Voice Studio `/api/tts` (narrator voice from
   blueprint). Dialogue per line → character's assigned voice, speed from
   voice config.
2. Insert `pause_before_ms` as leading silence in the line's WAV (ffmpeg
   `adelay`), so assembly stays dumb.
3. Loudness-normalize all speech to −16 LUFS (`ffmpeg loudnorm`).
4. Write real durations back into `screenplay.json` shots → re-balance
   blocks if needed (Stage 3 re-partition hook).
5. Scorecard: lines rendered, total speech seconds, failures.

### Stage 5 — Assembly (`stage5_assembly.py`)
1. **Per-block render**: panel (or clip) + its audio → segment via ffmpeg:
   still panels use `-loop 1 -t <dur>` at project fps; subtle transitions
   only (`xfade=fade:d=0.25` or hard cut — never wipes/zooms).
2. Clip replacement: if `clip` exists for a shot (video model output),
   it replaces the panel segment; lipsync + consistency checked (flag-only
   in v2.0; auto-fix later).
3. **Music**: generated non-copyright bed (placeholder: silence or local
   musicgen later — v2.0 accepts a user-provided wav), mixed at −18 dB under
   speech (sidechain-duck −6 dB when speech present).
4. SFX only where `timeline.sfx` entries exist.
5. **Concat**: blocks → `final.mp4` (h264, crf 18, yuv420p). For 11-hour
   projects this is a concat of ~440 block files — streaming concat demuxer,
   never loads all in RAM.
6. **Predictions**: duration = Σ shot durations; size = bitrate × duration
   (shown on timeline before render).
7. **Copyright check**: verify music/SFX files carry `generated: true`
   or user-approved license flag in manifest; refuse render otherwise.
8. **Next-episode carryover**: button writes `next_episode` in timeline +
   copies world bible + character refs + style LoRA pointer into a new
   project pre-seeded (new story_id, guarded lineage link `parent_story_id`).
9. Scorecard: render time, segments, final duration/size vs prediction.

## 5. Cross-cutting systems

### 5.1 `PipelineLLM` (llm.py)
- Ollama `/api/chat`, model roles from `pipeline.toml` (default all
  `llama3.1:8b`; upgradable per-role).
- `complete_json(prompt_file, context, schema)`: renders prompt template,
  calls with `format: json` when schema given, validates with Pydantic;
  on failure → repair pass (feed error back, max 2 retries) → hard fail
  logged with the raw output saved for debugging.
- Deterministic-ish: temperature 0.3 extraction / 0.9 creative (per prompt
  frontmatter), fixed seed option for tests.
- Token budget guard: context assembled to ≤ 6k tokens (llama3.1:8b has 8k
  as configured); evidence packs trimmed by relevance, never the instruction.

### 5.2 Scorecards (`scores.py`)
- `scores.sqlite`: table `scores(stage, unit, metric, value, ts, run_id)`.
- Stage gate: `run.py` refuses to start stage N+1 unless stage N wrote its
  `stage.done` AND mandatory metrics exist → **skipped-step reporting** is
  structural, not honor-system. `run.py report` prints the full ledger.

### 5.3 `ComfyClient` (comfy_client.py)
- HTTP `/prompt` + websocket progress; loads workflow template JSON, patches
  node inputs by title.
- Health/VRAM check before each queue; restart-ComfyUI-between-batches
  pattern from `scripts/generate_safe.py` (CLAUDE.md); auto-start via
  kernel services API if down.
- Failure contingency: 3 consecutive failures → stop stage, write scorecard
  `contingency_stop`, report which model/checkpoint failed.

### 5.4 `model_lab.py` — model & LoRA testing/training flow
- `lab test-model <ckpt>`: fixed 12-prompt suite → grid, CLIP adherence
  scores, seconds/image → `lab_results.sqlite`.
- `lab stress <ckpt>`: 20 consecutive gens, watch VRAM creep + failures.
- `lab compare`: table of speed/quality across tested checkpoints.
- `lab train-lora <dataset>`: kohya_ss wrapper (style or character LoRA);
  post-train auto-test vs baseline.
- Assets that pass parameter checks get promoted into `pipeline.toml`.

### 5.5 Prompt review & enhancer
- `prompts/enhancer.md`: takes a failing sd_prompt + failure reason
  (adherence low / consistency low) → returns enhanced prompt within the
  same anchor constraints (may not alter character anchor tags — enforced by
  diff check).

### 5.6 Studio Web UI build-out (kernel additions, after core pipeline works)
- `GET /api/pipeline/projects`, `POST /api/pipeline/projects` (intake form:
  script paste, fps slider 24–60, style pick).
- `GET /api/pipeline/<slug>/status` (stage ledger + scorecards → stage cards
  light up on the Studio page).
- `POST /api/pipeline/<slug>/run/<stage>`; panel browser with lock buttons;
  world-bible viewer (characters, relationship web graph — reuse cortex
  renderer); timeline view with duration/GB prediction + next-episode button.

## 6. Milestones & acceptance gates (build order)

| M | Deliverable | Gate (must demo) |
|---|---|---|
| M0 | Package skeleton, config, blueprint, scores, run.py, tests scaffold | `run.py new-project` creates valid blueprint; pollution guard trips on swapped script |
| M1 | Stage 0 + chunking | 50k-word script chunks with zero loss (reassembly test) |
| M2 | Stage 1 world bible | On sample script: all named characters found; world era inferred with evidence; relationship web non-empty; contradictions file written; every character has valid sd_prompt |
| M3 | Stage 2 screenplay | Every shot has sd_prompt/narration/dialogue; audit improves 3 weakest (scores prove it); dedup test passes |
| M4 | ComfyClient + Stage 1R refs | 10+ turnaround refs for 2 characters, VRAM-safe across 30 gens unattended |
| M5 | Stage 3 + 3B | Blocks ordered first/ending/infill; panels for a 3-scene story; locks respected on re-run; seed-frame continuity visible |
| M6 | Stage 4 audio | All lines voiced with correct per-character voices + pauses; durations written back |
| M7 | Stage 5 assembly | Watchable MP4 with narration+dialogue+quiet music; prediction within 10% of actual |
| M8 | model_lab + Studio UI endpoints | lab compare table on 2 checkpoints; Studio page shows live stage ledger |

## 7. Risks & contingencies

- **8 GB VRAM**: SDXL + LoRA fits only with --novram; never co-resident with
  llama3.1:8b → hard stage sequencing (section 1). If OOM: drop to 896×1280.
- **llama3.1:8b JSON reliability**: repair-loop + `format: json`; if a prompt
  consistently fails, split it into smaller calls (design already per-unit).
- **11-hour ceiling**: 11 h ≈ 440 blocks ≈ 6,600 shots ≈ weeks of GPU time on
  this laptop. The architecture supports it (resume, blocks, streaming
  concat); the plan documents the reality so expectations are set.
- **E: drive instability**: projects/ lives on C: (repo); only model
  checkpoints on E:. Assembly re-verifies file existence before render.
- **Anime face-consistency scoring** is approximate (CLIP): thresholds are
  flag-only, human review via panel locks is the backstop.

## 8. Open questions for Amir (refinement backlog)

1. Narrator voice: fixed (e.g. `am_michael`) or per-project choice at intake?
2. Default resolution: 1280×720 (fits VRAM comfortably) or 1080p (slower)?
3. Music: acceptable to start with "bring your own wav" until a local
   musicgen is added?
4. Video clips (LTX/CogVideoX): v2.0 ships panels-only with clip slots, or
   block on video generation from day one? (Recommend panels first.)
5. Which SDXL checkpoint is the current z-anime default in your ComfyUI?
6. Sample script to use as the golden test story?
