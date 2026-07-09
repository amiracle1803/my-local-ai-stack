# Anime Pipeline v2 — Detailed Design (Build Contract)

> **Status: PLANNING — do not execute yet.**
> This document is the build contract. It is written so that any capable
> model/developer can implement it without asking questions. Companion docs:
> `anime-pipeline-v2-plan.md` (overview) and
> **`aether-studio-original-spec-stages0-2.md` (RECOVERED ORIGINAL spec —
> normative for Stages 0–2: exact schemas, prompts, temperatures, banned
> patterns, human touchpoints. Where this doc says "per original spec",
> implement exactly what that file says.)** Hardware target: RTX 4070 Laptop
> 8 GB VRAM, 32 GB RAM, Windows 11, fully local.
>
> **v2 changes vs the original spec (Amir, 2026-07-09):**
> 1. **Primary image model → krea2** (see section 0 model table + risk note).
> 2. **Automation-first**: every stage auto-advances by default; the
>    original's human touchpoints become optional pause-gates (section 0.2).

## 0. Models & temperatures

| Task | Model | Parameters | Notes |
|---|---|---|---|
| All script/screenplay LLM work | qwen3:8b | think:false, keep_alive=300, ctx 16384 | pull required (`ollama pull qwen3:8b`) |
| Panel vision analysis | qwen2.5vl:7b | think:false, keep_alive=0, ctx 4096 | pull required |
| **Image generation (primary)** | **krea2** (checkpoint slot `image_primary` in pipeline.toml) | steps/sampler per model card; 832×1216 | **v2 change** — see risk note below |
| Image gen (fallback 1) | z-anime-distill-4step-fp8 | 4 steps, euler, fp8 | auto-switch after 5 consecutive primary failures (original spec pattern) |
| Image gen (fallback 2) | flux1-schnell-Q4_K_S.gguf | disabled by default | last resort |
| Animation | Wan2.2-TI2V-5B fp8 KJ build | 20 steps, unipc, block-swap=20, cfg 5.0, 81 frames @16fps | clip slots in Stage 5 |
| TTS | Kokoro in-process | CUDA/CPU, loaded once, reused all shots | already running as Voice Studio :5050 |

Temperature guide (all LLM calls — from original spec): 0.1 extraction ·
0.2 conservative synthesis · 0.3 structured creative · 0.4 dialogue ·
0.5 creative expansion · 0.6 narration rewrites.

**krea2 risk note (builder must handle):** the model slot is config, not
code. Before making krea2 the default, run it through `model_lab` (section
5.4): verify open weights exist in a quant that fits 8 GB VRAM (GGUF/fp8),
measure sec/image, and test anime-style adherence — Krea models are tuned
for photorealistic aesthetics, so the z-anime style tail + style LoRA must
be validated against it. If krea2 fails the lab gates, keep z-anime-distill
as primary and file the lab report; the fallback chain already covers this.

### 0.2 Automation-first policy (v2 change)

- `pipeline.toml` gets an `[automation]` table:
  `auto_approve_blueprint / auto_approve_transform_map /
  auto_approve_identity / auto_resolve_contradictions / auto_advance_stages`
  (all default **true**; the original's human touchpoints only pause the run
  when their flag is false, or when a **hard gate** trips: legal score < 50,
  blocking appearance contradiction, or >20% panel vision failures).
- Auto-resolution defaults: contradictions → majority-evidence tie-break
  (logged in `contradictions.json` with `auto_resolved: true`); uncertain
  character groupings → treat-as-same (original's provisional rule);
  blueprint/transform map → accepted as generated.
- Everything a touchpoint would show is still written to disk + scorecard,
  so the user can review after the fact and re-run a single unit.
- `run.py all` runs Stage 0→5 unattended; the kernel Tasks API and n8n can
  schedule it (nightly episode builds) once M8 lands.
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
│   ├── stage3c_animation.py     # motion tiers + LTX/Wan (runs after stage 4)
│   ├── stage4_audio.py          # voice system (VoiceSpec registry, delivery)
│   ├── stage5_assembly.py
│   ├── align.py                 # whisperX forced alignment → viseme timeline
│   ├── lipsync.py               # LipSyncEngine: flipbook | wav2lip | latentsync
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

## 3.9 The script quality ladder (why each stage exists)

Each stage takes the story up one rung, and each rung has a **proof metric**
in the scorecard — a stage that can't prove its improvement didn't happen:

| Rung | Transformation | Proof metric |
|---|---|---|
| Stage 0 | idea/source/panels → **structured story** (act structure committed before prose; scenes hit word targets; every scene opens on action/dialogue) | structure_completeness = all blueprint fields non-empty; scene checks passed % |
| Stage 1 | prose → **canonical knowledge** (every character/location has one true appearance anchor; contradictions resolved; world logic explicit) | bible_coverage = 100% of scanned names present; open contradictions = 0 |
| Stage 1R | knowledge → **visual + vocal identity** (refs, style LoRA, voice per character) | refs/character ≥ 10; voice distinctness violations = 0 |
| Stage 2 | knowledge → **filmable screenplay** (every shot: locked 120-word prompt, technique-rotated narration that survived the banned-pattern filter, voice-validated dialogue) | narration avg score; banned-pattern hits after rewrite = 0; style violations |
| Stage 3 | screenplay → **continuity plan** (blocks ordered first→ending→infill; motion tier + motion prompt per shot) | block balance; motion budget within cap |
| Stage 3B | plan → **consistent stills** | prompt adherence avg; character consistency avg |
| Stage 4 | text → **performed voice** (per-character voices, emotional delivery, phoneme timeline) | alignment coverage % ; loudness within ±1 LUFS |
| Stage 3C | stills + voice → **living motion with lips in sync** (runs AFTER Stage 4 — clip length and mouth timing derive from real audio) | mouth/voiced-segment overlap ≥ 85%; face consistency ≥ threshold |
| Stage 5 | pieces → **watchable episode** | A/V sync error < 50 ms; prediction within 10% |

**Execution order is therefore: 0 → 1 → 1R → 2 → 3 → 3B → 4 → 3C → 5.**

## 4. Stage designs

### Stage 0 — Script (`stage0_intake.py`) — THREE MODES per original spec
All modes end with `script.txt` + blueprint + scorecard. Common intake
settings: `fps` (24–60, snapped to 24/30/60 with warning for video-model
compatibility), style preset, resolution.

- **0B GENERATE** (original from brief): 3-pass — Story Blueprint (temp 0.3,
  full JSON schema in original spec) → Scene-by-Scene Prose (one call per
  scene, temp 0.5, word-target enforcement ±30%, automated per-scene quality
  checks) → Integration (no LLM; scene markers + name/location/word-count
  validation). Blueprint Review touchpoint = pause-gate (auto-approve by
  default per §0.2). **v2 prose-quality loop (improvement #5)**: each scene
  runs draft → self-critique (temp 0.2: "list the 3 weakest sentences and
  why") → targeted revise (temp 0.5) — two extra cheap calls per scene; the
  prose prompt carries 1–2 short style exemplar passages (per-project,
  editable) to anchor tone.
- **0A TRANSFORM** (source → original): 4-pass — Mechanics Extraction (temp
  0.1, first 4000 chars, mechanics-only) → Originality Design (temp 0.5,
  transformation map) + **legal proximity score** (scoring table in original
  spec; <75 warn, **<50 hard gate always pauses**, even in full-auto) →
  Blueprint → Prose (as 0B).
- **0I IMPORT** (existing panels → story): 4-pass — Panel Inventory (no LLM;
  natural sort, blank/splash detection) → Per-Panel Vision (qwen2.5vl:7b,
  sequential, 3-tier failure handling) → **Character Identity Resolution**
  (fingerprint clustering, uncertain groupings; auto=treat-as-same) →
  Screenplay Synthesis. **v2 (improvement #7): the 60-panel cap is removed**
  via hierarchical synthesis — panels are grouped into scenes first (setting
  similarity), synthesis runs per scene (≤10 panels per call), scene
  screenplays merged; no single call ever nears context limits. Coverage
  check, banned-pattern filter, and fair-use score unchanged.
- Chunking (all modes): chonkie, 8000-char chunks / 400-char overlap (the
  original's numbers), offsets stored in blueprint for reproducibility.
  **No truncation ever.**
- Scorecard: mode, script length, chunk count, validation results, legal /
  fair-use score where applicable.

### Stage 1 — World bible (`stage1_worldbible.py`)
**Implement per original spec Steps 1–5** (full-script character scan with
8000/400 chunking · per-character profile extraction from assembled mention
context · world/lore extraction · contradiction detection + dedup with exact
merge rules · creative expansion), using qwen3:8b at the original's
temperatures, with these **v2 deltas** layered on:
- era/tech inference with evidence heuristics (below, item 4)
- relationship web with evolution points (below, item 5)
- outfit materials derived from world details + class; outfit changes over
  time each get their own sd_prompt + pre-created references
- contradiction auto-resolution default per §0.2 (majority evidence), hard
  gate on blocking appearance conflicts
- voice assignment uses the original's full Kokoro voice table + rules
- **fact provenance (improvement #9)**: every extracted fact/claim carries
  `{episode, chunk_index}` provenance; contradiction reports cite both
  sources ("ep1 ch.3 says X, ep3 ch.11 says Y")
- **pronunciation lexicon (improvement #6)**: one call generates phoneme
  spellings for every character/location/term name → `lexicon.json`;
  applied at every TTS call (misaki phoneme overrides) so invented names are
  pronounced consistently; user-editable in the world bible UI

Order of operations (all via `PipelineLLM`):
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
1. **Role-scaled reference sets (HARD REQUIREMENT per Amir)**:
   - Every character: **minimum 10 frames**, full-body 360° turnaround
     (8 views: front, 3/4L, side L, back-3/4L, back, back-3/4R, side R,
     3/4R) + 2 expression sheets — via `workflows/character_sheet.json`,
     fixed per-character seed.
   - **Main characters (role = protagonist/antagonist/major-recurring):
     30–40 frames** — the 360° set plus expression range (joy, anger, fear,
     grief, resolve, smirk), 3 poses (standing, action, seated), and one
     set per owned outfit. Counts enforced by the stage gate; a main
     character with <30 frames fails the scorecard.
2. Same for each recurring location + asset (4+ angles).
2b. **Per-character LoRA — MANDATORY for every character (v2 hard
   requirement)**: after refs pass QC, `model_lab train-lora --character`
   runs for each character. Dataset = that character's full ref set,
   captioned with outfit tokens (so identity and clothing stay separable).
   Config: rank 8, ~800 steps for 10-frame minors, rank 16, ~1500 steps for
   30-40-frame mains. Checkpoints:
   `E:\AI\Models\loras\<slug>\char-<id>.safetensors`. Stage 3B will not run
   until every character appearing in the screenplay has a trained LoRA
   (structural gate); IPAdapter remains as *additional* conditioning, not a
   substitute.
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
**Implement per original spec Steps 1–5**: shot plan (temp 0.15 + automated
shot-count rules: no two consecutive same shot_type, climax scene has most
shots, warn <20 or >60 total) · **SD prompt assembly with the 120-word
budget** (char anchors ~50 / location ~30 / composition ~30 / style ~10;
style tail "anime 2d illustration, manga panel style, high quality linework,
cel shading"; trim composition → location, never anchors; max 2 characters;
no names, no camera words) · narration craft (6-technique rotation +
exception rules + **banned-pattern regex filter** + rewrite queue at 0.6,
silence over bad narration) · dialogue craft (speech-style validation:
clipped >20 words flagged, verbose <6 flagged; first-60-chars dedup) ·
quality audit (3 weakest improved, technique conflicts fixed, >2-sentence
trims — all auto-applied through the filter).

**v2 deltas** on top of the original steps:
0a. **Per-scene dialogue calls (improvement #4)** replace the original's
   single all-episode dialogue call: one call per scene with compact "speech
   style cards" for present characters only — prevents voice bleed on the 8B
   model at long context. Global first-60-chars dedup still runs across the
   whole episode afterward.
0b. **Evolving banned-pattern list**: audit findings append new clichés to a
   per-project (and opt-in global) banned list that the regex filter loads —
   the filter gets stricter every episode.
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
4b. **SFX tagging (improvement #8)**: shot descriptions are scanned for
   foley-worthy events against a keyword→sound map (door, blade clash,
   explosion, rain, footsteps, glass…); matches above a confidence threshold
   become `timeline.sfx` entries pointing into a local CC0 sound library
   (`assets/sfx/`, manifest with license flags). Conservative by design —
   silence beats wrong foley.
5. **Panel state machine**: pending → generated → (flagged → regenerating →
   generated) → reviewed → locked. Locked panels are never touched by
   automation. Missing panels (file lost/corrupt) auto-detected → regenerated.
6. Scorecard: blocks, shots/block distribution, estimated total duration
   (validates the 11-hour ceiling: blocks × block_seconds; warn > 11 h).

### Stage 3B — Images (`stage3b_images.py`) [GPU]

**Aspect ratio (v2 fix)**: the original spec's 832×1216 is portrait manga —
wrong for video. Default generation is **landscape 1216×704** (SDXL-native),
letter-perfect into a 1280×720 timeline; optional 1344×768; portrait kept
only for a future "manga mode". Final 1080p delivery via free upscaler
(RealESRGAN-anime) at assembly if requested.

**Scene environment lock (v2 addition — background consistency):**
- Per scene, before any shot renders: generate ONE **location master plate**
  (the scene's location sd_prompt + scene lighting/time-of-day, no
  characters). Stored `panels/<block>/_plates/<scene-id>.png`.
- Every shot in the scene conditions on that plate: IPAdapter (image prompt,
  weight ~0.45) + the scene's fixed **environment token block** (lighting,
  palette, time of day — composed once per scene, appended verbatim to every
  shot prompt in that scene).
- Scene-level base seed: `hash(scene_id)` — shot seeds derive from it, so
  the whole scene samples from a nearby latent neighborhood.

Per-shot generation:
1. Per shot (skip locked): txt2img via `panel_txt2img.json`, or img2img via
   `panel_img2img_lastframe.json` when the shot opens a block with a
   `seed_frame` (denoise 0.55).
2. Inputs: assembled sd_prompt + style LoRA + **per-character LoRA when
   trained (v2 improvement #1)** + **IPAdapter character reference** (front
   ref sheet as image prompt, weight ~0.5) + scene plate conditioning +
   per-character seeds blended with the scene base seed (all reproducible,
   stored in the sidecar json).
3. **Vision-judge QC (v2 improvement — replaces CLIP-only checks):**
   qwen2.5vl:7b receives the rendered panel + a structured checklist:
   - "Which characters are visible?" → must equal the shot's
     `characters_in_frame` (**right characters in frame — hard check**;
     wrong cast → auto-retry, twice → flag)
   - outfit correct per world bible? · background matches the scene plate
     description? · character count correct? · composition roughly as
     described?
   Each answer scored; CLIP image-image similarity vs character refs and vs
   the scene plate kept as cheap secondary signals.
4. Retry ladder: enhanced prompt (enhancer call, anchors immutable) →
   re-seed → flag in storyboard for lock/manual.
5. **Per-character LoRAs are mandatory** (trained in Stage 1R §2b — Stage 3B
   refuses to start without them). Generation stacks: character LoRA(s) for
   the shot's cast (max 2, matching the 2-character prompt rule) + style
   LoRA + IPAdapter reference as extra glue. A/B against the vision-judge
   consistency score is still logged per episode to catch LoRA regressions.
6. VRAM discipline as Stage 1R. Progress persisted every panel (resume-safe).
7. Scorecard: panels generated, retry rate, vision-judge pass %, wrong-cast
   incidents (must trend to 0), background-consistency avg, character
   consistency avg.

### Stage 4 — Voice system (`stage4_audio.py`, `pipeline/align.py`) [CPU/light GPU]

**Design goal: every character owns a unique, deterministic voice for the
life of the series, with emotional delivery and a phoneme timeline that
Stage 3C's lip sync consumes.**

#### 4.3.9 Wardrobe & asset registry (v2 hard requirement — clothing consistency)

**Storage** (per project, carried across episodes via next-episode
carryover):
```
worldbible/
├── wardrobe/<char-id>/<outfit-id>/
│   ├── manifest.json      # outfit sd_prompt, material (from world/class),
│   │                      # first_scene, evidence quote, implied: true|false
│   └── ref_*.png          # ≥6 refs of the character IN this outfit
│                          # (front/back/side + detail crops of distinctive
│                          # elements: emblem, trim, armor plates)
└── assets/<asset-id>/
    ├── manifest.json      # sd_prompt, category (weapon/prop/vehicle/emblem),
    │                      # owner char (optional), recurring: bool
    └── ref_*.png          # 4+ angles; hero props (protagonist's weapon
                           # etc.) get 10+ and their own asset LoRA
```
- Outfit refs are part of the character's LoRA dataset, captioned with a
  unique outfit token (`outfit_rin_academy`, `outfit_rin_battle`) — the LoRA
  learns identity and clothing separably, so prompting the outfit token
  reproduces exact clothing.

**Outfit switching — story-driven (per Amir: switch when the story states it
or heavily implies it):**
1. Stage 1 extracts **outfit-change events** while profiling:
   - *explicit*: "changed into", "put on", "wearing her ceremonial robes"
   - *heavily implied* (each with an evidence quote, flagged
     `implied: true`): time skip/new day, bathing/waking scenes, battle
     damage, weather shift (rain/snow → cloak), formal event, disguise,
     captivity, promotion/class change
2. The screenplay carries a resolved **`outfit_map`** per scene:
   `{char_id: outfit_id}` — computed by walking scenes in order and applying
   change events; every entry stores its evidence + provenance.
3. Stage 2 prompt assembly reads the scene's outfit_map and uses **that
   outfit's sd_prompt + LoRA token** — never `clothing_primary` blindly.
4. Vision-judge QC checks the *scene's mapped outfit*, not the default one;
   wrong-outfit panels are treated like wrong-cast (retry → flag).
5. Implied switches surface in the Studio wardrobe UI (evidence quote +
   accept/override); in full-auto they apply but stay marked for later
   review. New outfits discovered mid-story trigger an incremental Stage 1R
   run (refs + LoRA dataset update) before their scenes render.

#### 4.4.1 Voice identity registry
Every character's voice is a **VoiceSpec**, stored in the world bible and in
`projects/<slug>/voices.json`:
```jsonc
{
  "char-rin": {
    "base": "af_heart",                 // Kokoro voice id (original spec table)
    "blend": {"with": "af_sky", "ratio": 0.65},   // null if pure base voice
    "speed": 1.04,                      // 0.85–1.15, per character
    "pitch_semitones": +1.0,            // post-process, −3..+3, per character
    "assigned_by": "auto|user",
    "audition": "worldbible/refs/char-rin/voice_audition.wav"
  },
  "_narrator": {"base": "af_bella", "blend": null, "speed": 1.0, "pitch_semitones": 0}
}
```
- **Assignment algorithm** (runs at end of Stage 1, deterministic):
  1. Rank characters by dialogue line count (protagonist first — they get
     the best-fitting pure voices).
  2. Walk the original spec's rule table (gender/age/personality →
     candidate list); take the first **unused** candidate.
  3. Candidates exhausted → synthesize a **blend**: nearest-personality base
     + second base, ratio derived from `hash(char_id) % 30 / 100 + 0.55`
     (deterministic, reproducible across re-runs). Kokoro supports voice
     embedding mixing — this yields unlimited distinct voices.
  4. **Distinctness gate**: no two characters who share ≥1 scene may have
     (same base+blend AND |Δspeed| < 0.05 AND |Δpitch| < 1.0). Auto-adjust
     speed/pitch until the gate passes; violations = scorecard metric.
  5. `_narrator` is reserved — never assigned to a character. Chosen at
     intake (default `af_bella`, the original spec's narrator-style pick).
- **Audition sheet**: Stage 1R renders a 5-second audition per character
  (their most characteristic script line). Studio UI shows a play button +
  voice dropdown + "re-audition" per character; user overrides set
  `assigned_by: user` and are never auto-changed again.
- **Series persistence**: next-episode carryover copies `voices.json`;
  a recurring character's VoiceSpec is immutable across episodes unless the
  user overrides.

#### 4.4.2 Emotional delivery (Kokoro has no emotion knob — synthesize one)
Per-line rendering pipeline: text → Kokoro (base/blend voice, character
speed) → post chain driven by `delivery_note` + `emotion`:
| delivery | transform |
|---|---|
| whispered | speed ×0.92, gain −6 dB, lowpass 6 kHz |
| shouted | speed ×1.05, gain +3 dB, mild compression |
| trailing off | 400 ms fade-out on final word |
| cutting in | trim leading silence; timeline overlaps previous line by 150 ms |
| inner thought (audio_thought) | reverb small-room 12% wet, gain −3 dB |
- Long lines split at sentence punctuation with 120–250 ms micro-pauses for
  natural rhythm (prevents Kokoro run-on flatness).
- **Pause model** (feeds both audio and LTX director): interruption 0 ms ·
  casual reply 200–400 · considered 600–900 · complex decision 1200–2000 ·
  dramatic reveal 2000–2800 · **reaction beat**: +400 ms before the reply to
  a shocking line (Stage 2 marks these).
- Pitch shift applied last (librosa or ffmpeg `rubberband`), preserving
  formants where the tool allows.

#### 4.4.3 Rendering + QC
1. Narration per shot → narrator VoiceSpec. Dialogue per line → character
   VoiceSpec. All via Voice Studio API (extended to accept VoiceSpec fields:
   blend, pitch — small additions to `olympus/engines/voice/app.py`).
2. `pause_before_ms` baked as leading silence (`adelay`) so Stage 5 stays dumb.
3. Loudness: speech normalized to −16 LUFS (`loudnorm`), music bed later at
   −26 with −6 dB sidechain duck under speech.
4. **Per-line QC** (automated): duration sanity (≈ words × 350 ms ± 50%),
   no internal silence > 1.5 s, no clipping, loudness within ±1 LUFS.
   Failures re-render once, then flag.
5. Real durations written back into `screenplay.json` → Stage 3 re-partition
   hook if a block overflows 20%.

#### 4.4.4 Forced alignment → phoneme timeline (lip-sync fuel)
For every dialogue/narration WAV:
- Run **whisperX** (faster-whisper small + alignment head, local, light)
  against the *known transcript* → word- and phoneme-level timestamps →
  `audio/dialogue/<shot>_<line>.align.json`.
- Map phonemes → **viseme classes** (Preston Blair 9, reduced for anime):
  `A` (open: a/ah), `E` (e/eh), `I` (ee), `O` (oh), `U` (oo/w),
  `M` (m/b/p closed), `F` (f/v), `L` (l/th/d/t), `REST` (silence).
- Anime mouth-swap schedule derives from this at 8–12 mouth-fps (limited
  animation style — intentionally NOT per-frame realistic).
- Scorecard: alignment coverage % (lines successfully aligned), avg
  confidence; < 90% coverage flags the stage.

### Stage 3C — Animation & lip sync (`stage3c_animation.py`, `pipeline/lipsync.py`) [GPU, runs AFTER Stage 4]

**Design goal: panels come alive — motion where it earns its GPU cost, and
every speaking close-up has lips synced to the actual audio.** Runs after
Stage 4 because clip duration = real audio span and lip sync consumes the
alignment timeline.

#### 3C.1 Motion tiers (budget-driven — not every shot animates)
| Tier | What | Engine | Cost | Default for |
|---|---|---|---|---|
| 0 | **Oscillating drift** (per Amir): the still slowly translates 0→350 px in one direction over the shot; the NEXT still drifts the opposite direction — alternating oscillation across consecutive stills. Linear translate only, constant speed, no zoom (Ken Burns stays banned). Axis vertical by default, `[animation] drift_axis` configurable; 350 px scaled proportionally at other resolutions (render on an oversized canvas, crop-translate via ffmpeg) | ffmpeg | free | budget-exhausted or user-locked shots |
| 1 | Ambient motion 3–4 s (hair drift, cloth, particles, rain, breathing idle) | LTX i2v short | ~1–3 min/shot | **the default floor for ALL shots** — wide, detail, mood |
| 2 | Action motion, start-frame = panel, optional **end-frame = next panel** (LTX first+last-frame conditioning → seamless shot-to-shot flow) | LTX Director / Wan2.2-TI2V-5B | ~4–8 min/shot | shot_type=action |
| 3 | Dialogue close-up with **full lip sync** | Tier 1/2 base + mouth compositing (below) | + seconds/shot | close_up with dialogue, lipsync=true |
- **Every shot gets real generated motion by default** (Tier 1 floor).
  Tier 0 exists only as the degradation path: motion budget exhausted, LTX
  contingency-stopped, or a user lock — and it is a clean hold, never a
  synthetic zoompan.
- Auto-assignment from shot_type + dialogue presence; per-shot override
  (`motion_tier`, `motion_prompt`) in storyboard; **motion budget**:
  `[animation] max_animated_seconds_per_block` caps Tier 1–2 spend, predictor
  shows estimated GPU-hours before the stage runs (Tier-1-everything on a
  20-min episode ≈ 200 shots ≈ 5–10 GPU-hours — surfaced up front).
- Models per original spec: Wan2.2-TI2V-5B fp8 KJ (20 steps, unipc,
  block-swap 20, cfg 5.0, 81 frames @ 16 fps — these exact params fit 8 GB).
  LTX checkpoint already on disk: `E:\AI\Models\ltx23AllInOneSFWNSFWLTXDirectorID_v40`.
  Requires re-enabling `ComfyUI-WanVideoWrapper_disabled` (CLAUDE.md) only
  while this stage runs.

#### 3C.2 Motion prompts (LTX "director" grammar)
Stage 3 emits a `motion_prompt` per Tier 1–2 shot (LLM call, temp 0.3)
constrained to a documented vocabulary the Director checkpoint understands:
`[camera: static|slow push-in|slow pull-back|pan-left|pan-right|handheld-subtle]
[motion: <2-3 physical elements that move>] [character: <one clear action>]`
Speech timing feeds `[character: speaks]` segments from the Stage 4 pause
model, so gestures land between lines, not over them.

#### 3C.3 FPS reconciliation
Video models generate at native rates (Wan 16 fps, LTX 24/25). Project fps
is 24–60 (blueprint). Chain: native → **RIFE interpolation** (rife-ncnn-
vulkan, free, fast, tiny VRAM) ×2/×3 → exact project fps conform via ffmpeg
(`minterpolate` only as fallback). Static holds (Tier 0) render directly at
project fps. The chain used is recorded in the clip sidecar.

#### 3C.4 Full lip sync — anime-native design
**Key decision: the default engine is a viseme flipbook, not a photoreal
lip-sync net.** Photoreal engines (Wav2Lip/LatentSync) degrade on anime
faces; anime itself uses limited mouth animation (3–5 shapes at 8–12 fps) —
so we do what the medium does, deterministically:
1. **Mouth-shape sheets (one-time, Stage 1R add-on)**: for every character,
   inpaint the mouth region of their front reference into the 9 viseme
   shapes (A E I O U M F L REST) → 9 PNGs + mouth-region bbox stored in
   `worldbible/refs/<char>/mouths/`. Generated once, reused all episodes.
2. **Compositing pass (per Tier-3 shot)**: face + mouth bbox located on the
   shot panel (anime-face-detector; manual bbox override in Studio UI);
   the Stage 4 viseme schedule (8–12 mouth-fps) drives frame-by-frame mouth
   swaps composited over the base clip/still — includes idle REST during
   pauses and other characters' lines.
   - On moving bases (Tier 1/2 clips): mouth anchor tracked across frames
     via optical flow of the face crop; tracking-confidence drop → fall back
     to still base for that shot (flagged).
3. **Optional photoreal engines** behind the same interface
   (`LipSyncEngine`: flipbook | wav2lip | latentsync in pipeline.toml),
   gated by `model_lab` exactly like krea2 — if a net beats the flipbook on
   the QC metrics for this art style, it can be promoted per-project.
4. **QC per shot**: mouth-open frames overlap voiced segments ≥ 85%
   (schedule vs alignment JSON); zero mouth motion during silence > 300 ms;
   face-crop CLIP similarity vs character reference ≥ threshold (identity
   held). Failures → auto-retry with still base → flag for panel lock/manual.

#### 3C.5 Artifacts & continuity
- `video/shots/<shot-id>.mp4` + sidecar: tier, engine, seed, motion_prompt,
  fps chain, lipsync engine + QC scores.
- Block chaining now includes clips: last *frame of the final clip* of block
  N (extracted via ffmpeg) becomes block N+1's seed_frame.
- VRAM sequencing: Ollama unloaded; ComfyUI restarted every N clips
  (generate-safe pattern); Wan and LTX never co-loaded.
- Scorecard: shots per tier, avg lip-sync overlap, retries, GPU-minutes
  actual vs predicted.

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
9. **Chapter markers**: scene boundaries become MP4 chapter marks (ffmpeg
   metadata) — free navigation for long videos.
10. **Farm mode (improvement #10)**: `run.py render --farm` processes blocks
   strictly in story order and publishes rolling partials
   (`video/partial_0001-0040.mp4`) — on multi-hour projects you watch act
   one while act three still renders; n8n can drive this nightly.
11. Scorecard: render time, segments, final duration/size vs prediction.

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

### 5.3b ComfyUI node & workflow plan (grounded against the real install, 2026-07-09)

**Already installed at `E:\AI\ComfyUI` (verified):**
| Piece | Role in pipeline |
|---|---|
| ComfyUI_IPAdapter_plus + `ip-adapter-plus_sdxl_vit-h` + CLIP-ViT-H | character reference conditioning + scene plate conditioning (dual IPAdapter) |
| ComfyUI-WanVideoWrapper + ComfyUI-KJNodes | Wan2.2-TI2V Tier-2 motion |
| ComfyUI-GGUF | flux1-schnell fallback, GGUF quants generally |
| RES4LYF / rgthree / Easy-Use / ControlAltAI / Manager | samplers + QoL, no hard dependency |
| Checkpoints: `NoobAI-XL-v1.1`, `wai-illustrious-v110` | the real anime bases on disk (**z-anime-distill from the original spec is NOT present** — see mapping below) |
| LoRA: `Hyper-SDXL-8steps-CFG` | speed distillation — this is how "4–8 step" generation is achieved on any SDXL base |
| LoRA: `il_anime_model_turn` | **character turnaround LoRA — the engine of the 360° reference sheets** (likely no ControlNet needed) |

**Checkpoint reality mapping:** `image_primary` currently resolves to
`wai-illustrious-v110 + Hyper-SDXL-8steps` (8 steps, cfg ~1.5–2) with
`NoobAI-XL` as the style alternate — until the krea2 lab verdict. The
original spec's "z-anime-distill-4step-fp8" is treated as this combo's
predecessor.

**To install (pinned commits, one at a time, import-test after each — the
comfy_api_nodes pydantic crash in CLAUDE.md is the cautionary tale; pip deps
go into ComfyUI's venv WITHOUT touching torch==2.6.0+cu124 / pydantic pins):**
1. `ComfyUI-LTXVideo` (Lightricks official) — LTX Director checkpoint
   support incl. first+last-frame conditioning. Checkpoint already on disk
   at `E:\AI\Models\ltx23AllInOneSFWNSFWLTXDirectorID_v40` → symlink/copy
   into `models/checkpoints`.
2. `comfyui-wd14-tagger` — auto-captioning for LoRA datasets (Stage 1R).
3. ControlNet `xinsir/controlnet-union-sdxl` (~2.5 GB) — **deferred**: only
   if turnaround quality via `il_anime_model_turn` proves insufficient
   (M4 decides; pose template PNGs ship in `workflows/poses/` either way).
4. RealESRGAN-anime model file — final upscale (runs as external
   ncnn-vulkan CLI, NOT a Comfy node, to keep VRAM free; same for RIFE).

**Workflow templates** (`workflows/*.json`, exported in API format; every
patchable node carries a stable title — the manifest lists them and
`ComfyClient` validates on load, failing fast if a title is missing):
| Template | Graph essentials | Patched titles |
|---|---|---|
| `character_sheet.json` | ckpt → Hyper-8step LoRA → `il_anime_model_turn` LoRA → (char LoRA on outfit re-runs) → KSampler fixed seed | `CKPT`, `PROMPT_POS/NEG`, `SEED`, `VIEW_TAG`, `LORA_CHAR` |
| `mouth_sheet.json` | load front ref → mask from mouth bbox → inpaint (viseme prompt) ×9 | `REF_IMAGE`, `MASK_BBOX`, `VISEME_PROMPT` |
| `scene_plate.json` | location prompt only, style LoRA, no char LoRAs | `PROMPT_POS`, `SEED_SCENE` |
| `panel_txt2img.json` | ckpt → Hyper LoRA → style LoRA → **char LoRA ×≤2 (chained)** → IPAdapter#1 (char ref, w≈0.5) → IPAdapter#2 (scene plate, w≈0.45) → KSampler 1216×704 | `LORA_CHAR_1/2`, `IPA_CHAR_IMG`, `IPA_PLATE_IMG`, `PROMPT_POS/NEG`, `SEED` |
| `panel_img2img_lastframe.json` | same + seed_frame latent @ denoise 0.55 | + `INIT_IMAGE`, `DENOISE` |
| `ltx_ambient.json` / `ltx_director.json` | LTX i2v; director variant adds motion-grammar prompt + first+last frame inputs | `START_FRAME`, `END_FRAME`, `MOTION_PROMPT`, `FRAMES`, `FPS` |
| `wan_ti2v.json` | Wan2.2-TI2V-5B fp8, 20 steps unipc, block-swap 20, cfg 5.0, 81f@16fps (original spec params) | `START_FRAME`, `MOTION_PROMPT`, `SEED` |
| `lora_dataset_prep.json` | WD14 tagger over ref folder → caption txt sidecars (+ outfit token injection done by pipeline code) | `INPUT_DIR` |

**VRAM budget per workflow (8 GB, --novram):** panel_txt2img with 2 char
LoRAs + dual IPAdapter ≈ 6.8 GB peak → fits; OOM fallback ladder: drop
IPAdapter#2 → 896×512 → single char LoRA (logged). Wan fp8 block-swap and
LTX (~5 GB) fit per spec; **never co-loaded**, ComfyUI restarted between
model families (generate-safe pattern).

**Smoke suite:** `model_lab test-workflows` queues every template once with
tiny params after any node install/update — a broken node pack is caught in
minutes, not mid-episode.

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
| M0 | Package skeleton, config (incl. `[automation]` + model slots), blueprint, scores, run.py, tests scaffold | `run.py new-project` creates valid blueprint; pollution guard trips on swapped script; `run.py all` sequences stages unattended |
| M1 | Stage 0B Generate (3-pass) + chunking | 50k-word script chunks with zero loss; blueprint→prose→integration passes validations on a sample brief |
| M2 | Stage 1 world bible (original Steps 1–5 + v2 deltas) | On sample script: all named characters found (incl. late-script); era inferred with evidence; relationship web non-empty; contradiction auto-resolution logged; every character has valid 40-60-word sd_prompt + voice id |
| M3 | Stage 2 screenplay (original Steps 1–5) | 120-word SD prompt budget enforced (unit tests); banned-pattern filter catches seeded bad narrations; audit improves 3 weakest (scores prove it); speech-style + dedup flags work |
| M4 | ComfyClient + model_lab + Stage 1R refs + wardrobe | **krea2 lab report (test/stress/speed) decides primary model**; 10+ turnaround refs for a minor + 30-40 for a main character; **character LoRAs trained for both (mandatory gate)**; an outfit-change event produces a second outfit with its own refs + token; VRAM-safe across 30 gens unattended; fallback chain triggers after 5 seeded failures |
| M5 | Stage 3 + 3B | Blocks ordered first/ending/infill; panels for a 3-scene story; locks respected on re-run; seed-frame continuity visible |
| M6 | Stage 4 voice system | Every character has a distinct VoiceSpec (distinctness gate passes); blends render; delivery transforms audible; whisperX alignment ≥ 90% coverage; durations written back |
| M6.5 | Stage 3C animation + lip sync | Mouth sheets generated for 2 characters; a Tier-3 dialogue shot plays with ≥85% viseme/voice overlap; a Tier-2 LTX shot uses start+end frame conditioning; RIFE conforms to project fps |
| M7 | Stage 5 assembly | Watchable MP4 with narration+dialogue+quiet music; clips replace panels where they exist; A/V sync < 50 ms; prediction within 10%; subtitle track generated |
| M8 | Stage 0A Transform + 0I Import + Studio UI endpoints | Legal score gates work (<50 blocks even in auto); 42-panel import → screenplay with identity resolution; Studio page shows live stage ledger |

Original spec priority order (respect within milestones): SD prompt assembly
first (biggest visual gain) → narration rewrite-not-drop → audit pass →
full-script scan → per-character extraction → contradiction/dedup → import
identity resolution → 0B restructure → 0A legal score → motion-effect UI →
world-bible portrait button → subtitles → comfyui path from config.

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

1. ~~Narrator voice~~ → RESOLVED: per-project choice at intake, default
   `af_bella` (§4.4.1).
2. ~~Default resolution~~ → RESOLVED: generation at landscape 1216×704
   (SDXL-native) into a 1280×720 timeline; optional 1080p final upscale via
   RealESRGAN-anime at assembly (§Stage 3B).
3. Music: acceptable to start with "bring your own wav" until a local
   musicgen is added?
4. ~~Video from day one?~~ → RESOLVED: Stage 3C designed in full with motion
   tiers; **Tier 1 LTX ambient motion is the floor for every shot** (Ken
   Burns rejected by Amir — Tier 0 is a clean static hold used only as the
   degradation path).
5. ~~Which checkpoint?~~ → RESOLVED by inventory (§5.3b): z-anime-distill is
   NOT on disk; actual bases are `wai-illustrious-v110` (primary) and
   `NoobAI-XL-v1.1`, made fast via the `Hyper-SDXL-8steps` LoRA. krea2
   still pending its lab verdict as a possible replacement.
6. Sample script to use as the golden test story?
7. Voice: any characters whose voice you already know you want pinned
   (e.g. protagonist = specific Kokoro id)? Pins go in voices.json as
   `assigned_by: user` before the auto-assigner runs.
8. Models to re-pull for this pipeline (~10 GB): `qwen3:8b`,
   `qwen2.5vl:7b` — confirm before M2 begins.
