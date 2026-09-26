# Workflow & Pipeline Node Notes

Two graphs matter in this engine: the **ComfyUI workflow graphs** (image/video
generation) and the **pipeline stage graph** (the 9-stage production line).
This file explains every node in both. The authoritative patch map lives in
`manifest.json`; the flux workflow additionally carries per-node `_meta.note`
strings readable in place.

---

## 1. `image_flux_fallback.json` — the ACTIVE image workflow

Used today for **everything image**: character reference sheets (Stage 1R),
scene plates and shot panels (Stage 3B), style refs. Active because krea2
(the mandated primary) has no weights on disk and every local SDXL anime
checkpoint is on the MODEL BAN LIST — flux-2-klein is the design's only
permitted fallback (§5.3b; swapped from flux1-schnell 2026-08).

| Node | Class | What it does | Why it's configured this way |
|---|---|---|---|
| 1 UNET | `UnetLoaderGGUF` | Loads flux-2-klein-4b from a Q4_K_M GGUF quant | ~2.6 GB quant is what fits alongside everything else in 8 GB VRAM; ComfyClient's ban-check reads `unet_name` here |
| 2 CLIP | `CLIPLoader` | Loads the qwen_3_4b text encoder (type `flux2`) | FLUX.2 klein's official recipe — a single Qwen3-4B encoder, NOT the flux1 clip_l/t5xxl pair |
| 3 VAE | `VAELoader` | Loads `flux2-vae.safetensors` | FLUX.2's own autoencoder (128-channel latent); decodes the finished latent at node 20 |
| 11 PROMPT_POS | `CLIPTextEncode` | Encodes the shot's assembled sd_prompt | Patched per generation by ComfyClient |
| 12 PROMPT_NEG | `CLIPTextEncode` | Real negative conditioning | klein runs cfg 5.0 (unlike schnell's cfg 1.0) so the negative is honored |
| 13 LATENT | `EmptyFlux2LatentImage` | Blank 128-channel FLUX.2 latent canvas | FLUX.2 latent layout (plain `EmptyLatentImage` is 4-channel and would crash); patched to 1216×704 landscape (panels) or 832×1216 portrait (refs) |
| 14 NOISE | `RandomNoise` | Per-shot seed | seed derives from `hash(scene_id, shot_id, retry)` so any panel can be regenerated bit-identically from its sidecar |
| 15 SCHED | `Flux2Scheduler` | 20-step resolution-aware sigma schedule | WIDTH/HEIGHT patch here too so the schedule matches the latent canvas |
| 16 SAVE | `SaveImage` | PNG into ComfyUI/output/`SAVE_PREFIX` | ComfyClient copies the file into the project tree and renames deterministically |
| 17 SAMPLER | `KSamplerSelect` | euler sampler | official klein recipe |
| 18 GUIDER | `CFGGuider` | CFG 5.0 | official klein recipe |
| 19 SAMPLER_ADV | `SamplerCustomAdvanced` | noise + guider + sampler + sigmas + latent | klein's recommended sampling graph |
| 20 DECODE | `VAEDecode` | Latent → pixels | — |

## 2. SDXL templates (dormant until a permitted SDXL-family primary exists)

`scene_plate.json`, `panel_txt2img.json`, `panel_img2img_lastframe.json`,
`character_sheet.json`, `mouth_sheet.json` share one node skeleton, richer
than flux because SDXL has LoRA + IPAdapter ecosystems:

| Node | Role | Notes |
|---|---|---|
| 1 CKPT | `CheckpointLoaderSimple` | Ships as a `PATCH_*` placeholder on purpose — the ban list forbids the local SDXL checkpoints, so a real name must be patched in (and survives ComfyClient's ban check) before these graphs run |
| 2 LORA_SPEED | LoRA loader | `Hyper-SDXL-8steps-CFG` — distills 30-step sampling down to 4–8 steps |
| 3 LORA_STYLE / LORA_TURNAROUND | LoRA loader | Style-lock LoRA (trained in 1R §3), or `il_anime_model_turn` in character_sheet.json — the engine of the 360° turnarounds |
| 4/5 LORA_CHAR_1/2 | LoRA loaders | Per-character identity LoRAs (max 2, matching the 2-character prompt rule); disabled by patching strength to 0 |
| 7/8 IPA_CHAR | IPAdapter | Front reference sheet as image-prompt, weight ≈0.5 — identity glue on top of the LoRA |
| 9/10 IPA_PLATE | IPAdapter | The scene's master plate as image-prompt, weight ≈0.45 — background consistency |
| 11/12 PROMPT_POS/NEG | `CLIPTextEncode` | SDXL uses a real negative prompt (unlike flux) |
| 13/14/15/16 | latent/sampler/decode/save | As in flux; `panel_img2img_lastframe.json` adds node 17 `INIT_IMAGE` + patched `DENOISE` 0.55 for block-chaining continuity |
| mouth_sheet 3/4 | image + mask loaders | Front ref + white-bbox mouth mask; inpaints one of 9 viseme shapes per run (lip-sync flipbook fuel) |

## 3. Video templates (dormant — contingency-stopped)

| Template | Engine | Blocker today |
|---|---|---|
| `ltx_ambient.json` | LTX i2v, Tier-1 ambient motion | ComfyUI-LTXVideo nodes not installed on the Linux box yet |
| `ltx_director.json` | LTX first+last-frame conditioning, Tier 2 | same |
| `wan_ti2v.json` | Wan2.2-TI2V-5B fp8, 20 steps unipc, 81f@16fps | wrapper installed, but 4–8 GPU-min/shot — gated behind the motion budget |
| `lora_dataset_prep.json` | WD14 auto-captioning for LoRA datasets | kohya training itself is the blocker (Windows venv) |

Stage 3C records these as **contingency stops** in the scorecard and degrades
every shot to Tier-0 oscillating drift (a clean linear pan applied by ffmpeg
in Stage 5 — never a zoom; Ken Burns is banned by spec).

---

## 4. The pipeline stage graph (what `run.py all` executes)

```
stage0 ──► stage1 ──► stage1r ──► stage2 ──► stage3 ──► stage3b ──► stage4 ──► stage3c ──► stage5
intake     world      refs        screen-    story-     panels      voice       motion      assembly
           bible      +voices     play       board      (GPU)       (CPU)       plan        (ffmpeg)
```

Every arrow is a **structural gate** (`scores.require_stage`): a stage runs
only if its predecessor wrote `stage.done` AND its mandatory proof metric.

| Stage node | Module | Produces | Proof metric |
|---|---|---|---|
| stage0 | `stage0_intake` | `input/script.txt` from a creative brief (3-pass: blueprint → per-scene prose with critique/revise loop → integration) | `structure_completeness` |
| stage1 | `stage1_worldbible` (M2a) + `stage1_world` (M2b) | `world_bible.json`: characters w/ 40–60-word sd_prompt anchors, world (era w/ evidence, magic, economy…), locations, relationship web, `contradictions.json`, `voices.json` | `bible_coverage` |
| stage1r | `stage1r_references` | 30 ref frames per main / 10 per minor, location angles, style refs, voice auditions | `refs_per_character` |
| stage2 | `stage2_screenplay` | `screenplay.json`: scenes → shots w/ assembled 120-word sd_prompt, technique-rotated narration (banned-pattern filtered, audited, 3 weakest rewritten), style-carded dialogue w/ pacing pauses | `narration_avg_score` |
| stage3 | `stage3_storyboard` | `storyboard.json`: ≤90 s blocks ordered first→ending→infill, motion tiers + prompts, SFX tags, panel state machine | `block_count` |
| stage3b | `stage3b_images` | scene plates + one PNG per shot + reproducibility sidecars, qwen2.5vl vision-judge QC (wrong cast/background ⇒ retry ⇒ flag) | `prompt_adherence_avg` |
| stage4 | `stage4_audio` | narration + dialogue WAVs per VoiceSpec, pauses baked as leading silence, real durations written back, whisper word/viseme alignment | `alignment_coverage` |
| stage3c | `stage3c_animation` | Tier-0 drift plan (alternating direction per consecutive shot); honest contingency metrics for LTX/lip-sync | `lipsync_overlap_avg` |
| stage5 | `stage5_assembly` | per-shot segments (panel + drift + audio) → block clips → `video/final.mp4` w/ chapters + `final.srt` + `timeline.json`; copyright gate on music | `av_sync_error_ms` |

Cross-cutting: `PipelineLLM` (all Ollama traffic, JSON-repair loop),
`ComfyClient` (all ComfyUI traffic, ban enforcement, 3-failure contingency),
`Scores` (sqlite scorecards, the gates), blueprint pollution guard (title_hash
recheck every stage).
