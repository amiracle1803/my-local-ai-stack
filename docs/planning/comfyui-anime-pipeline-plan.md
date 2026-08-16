# ComfyUI Anime Pipeline — Status, What We Tried, and Forward Plan

> **Scope:** This document reviews everything that has been attempted to make
> ComfyUI drive the anime/video portion of the pipeline (`stage3b_images`
> static panels + `stage3c_animation` motion), catalogues what works and
> what doesn't, and lays out a concrete forward plan with milestones and
> gate criteria. It complements — and where it conflicts, supersedes — the
> earlier `anime-pipeline-v2-design.md` and `krea2-lab-report.md`.
>
> **Hardware:** Lenovo Legion, RTX 4070 Laptop 8 GB VRAM, 32 GB RAM, Nobara
> Linux (Fedora base), ComfyUI 0.27.1 with `torch==2.6.0+cu124` and
> `pydantic==2.12.3` held. `--novram --disable-cuda-malloc` flags, GGUF
> quants only.
>
> **Date:** 2026-08-09 (updated from 2026-08-04 with Phases 1-3 implementation).

---

## 1. Inventory — what's actually on disk

### Templates (`olympus/engines/pipeline/workflows/`)

| Template | Status | Used by | Notes |
|---|---|---|---|
| `image_krea2.json` | ✅ ready | Stage 3B, image_router | Krea-2-Turbo GGUF txt2img primary. Krea2 text encoder (Qwen3-VL 4B `fp8_scaled`) + Qwen-Image VAE + `EmptySD3LatentImage`. 8 steps, `cfg=1.0`, euler/simple, ConditioningZeroOut for negative. Smoke marker `.krea2_smoke_passed` exists. |
| `image_flux_fallback.json` | ✅ ready | Stage 3B fallback | Flux1-schnell Q4_K_S. Only permitted fallback per ban list §5.3b. 4 steps, `cfg=1.0`, real FluxGuidance 3.5. |
| `character_sheet.json` | ✅ ready | Stage 1R | GGUF-ported krea2 character reference sheet (832×1216 portrait). |
| `mouth_sheet.json` | ✅ ready | Stage 3C (flipbook lip-sync) | GGUF-ported krea2 inpaint for 9 viseme shapes (denoise 0.65). |
| `panel_txt2img_krea.json` | ✅ ready | alt panel template if needed | Same graph shape as `image_krea2.json` with a fixed save prefix. |
| `panel_img2img_plate_krea.json` | ✅ ready | **Stage 3B primary** | **UPDATED 2026-08-09:** Krea2 reference-first img2img from scene plate. 22 nodes: VAEEncode(plate) + ControlNet + Regional prompts + Style LoRA + Mask composite + ColorCorrect + KSampler(denoise=0.35) + ImageSharpen. Smoke marker `.krea2_smoke_passed` gates it. |
| `panel_img2img_plate_anima.json` | ✅ ready | Stage 3B alt (Anima) | **UPDATED 2026-08-09:** Same 22-node control surface as krea2 but Anima recipe (er_sde/30/cfg 4.0, real negative). Gated by `.anima_smoke_passed` + Anima weights on disk. |
| `ltx22b_i2v.json` | ✅ ready | **Stage 3C Tier-1** | LTX 2.3 22B Q4_K_M image-to-video. Single-guide `LTXVImgToVideo` + STG guider + tiled VAE decode. 768×448 × 81f @ 16fps. Validated ~55 s @ 5.8 GB peak. |
| `ltx23_i2v_8gb.json` | ⚠️ experimental | Stage 3C tier-2 path (wired 2026-08-04) | LTX 2.3 22B Q4_K_M image-to-video via `LTXVAddGuide` + `LTXVTiledSampler`. Multi-tile path for higher res / longer frames on 8 GB. Wired via `video_router.pick_ltx_template`; moves to `ready` only after a real tier-2 render (M-AP-2 DoD). |
| `wan_ti2v.json` | ✅ ready | not used in 3C yet | Wan2.2 5B GGUF Q4_K_M t2v (T2V mode only — 5B has no I2V weights). 480×320 × 81f @ 16fps. Block-swap 20. |
| `wan_ti2v_visual.json` | ✅ ready | visual only | ComfyUI browser UI version (no patchable API entry). |
| `lora_dataset_prep.json` | ✅ ready | Stage 3B.5 ref prep | WD14 captioning of ref images for LoRA datasets. |
| `scene_plate.json` | ❌ deprecated | — | SDXL-only, GGUF port pending per manifest note. Use `image_krea2.json`. |
| `panel_txt2img.json` | ❌ deprecated | — | Same — SDXL-only. |
| `panel_img2img_lastframe.json` | ❌ deprecated | — | Same — SDXL-only. |

### Custom nodes (`ComfyUI/custom_nodes/`)

All installed and present:

- `ComfyUI-GGUF` — GGUF unet/text-encoder loading (city96).
- `ComfyUI-KJNodes` — `VAELoaderKJ`, STG/guider presets, advanced samplers, LTX helpers.
- `ComfyUI-LTXDirector` — `LTXVAddGuide`, `LTXVImgToVideo`, `LTXVScheduler`, `RandomNoise`, `STGAdvancedPresets`, `STGGuiderAdvanced` (a.k.a. `Con conditioning`).
- `ComfyUI-LTXVideo` — `EmptyLTXVLatentVideo`, `LTXVPreprocess`, `LTXVSpatioTemporalTiledVAEDecode`, `LTXVTiledSampler`.
- `ComfyUI-VideoHelperSuite` — `VHS_VideoCombine` (the save node for every animation workflow).
- `ComfyUI-WanVideoWrapper` — Wan 2.x T2V / I2V (installed; only T2V usable on 5B today).
- `ComfyUI-WD14-Tagger` — WD14 captioning for LoRA dataset prep.

### Models on disk

Verified against `stack.toml` `[comfyui.models]`:

- `krea2_turbo-Q4_K_S.gguf` — 7.49 GB (`models/unet/`) — primary image.
- `krea2_turbo-Q4_K_M.gguf` — fallback image.
- `flux1-schnell-Q4_K_S.gguf` — floor image (`6 GB` of VRAM peak).
- `ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf` — animation primary.
- `qwen3vl_4b_fp8_scaled.safetensors` — krea2 text encoder (the 4B, not the 8B `qwen3-vl:8b` used by Ollama vision-judge).
- `ltx-2.3_text_projection_bf16.safetensors`, `ltx/LTX23_video_vae_bf16.safetensors`, `gemma-3-12b-it-qat-UD-Q3_K_XL.gguf` — LTX 2.3 dual-CLIP + VAE.
- `qwen_image_vae.safetensors` — krea2 VAE.

---

## 1b. Phases 1-3 Implementation (2026-08-09) — Background Consistency & Control Surface

> **Scope:** Three-phase implementation addressing the "background consistency showing change of scene," "single location not building out world space," "too few user control nodes," and "EN/JP text bleed" issues raised in the Aug 9 session.

### Phase 1: Config/Threshold Fixes

| Change | File | Before → After | Rationale |
|---|---|---|---|
| Panel denoise | `stack.toml`, `stack/config.py`, `pipeline/config.py` | `0.55` → `0.35` | Tighter plate lock for background consistency; lower denoise = harder background anchor |
| V-JEPA2 plate cosine gate | `stage3b_images.py` | `0.82` → `0.88` | Stricter deterministic background gate; same-scene panels score >0.90, cross-scene <0.70 |
| EN/JP text bleed fix | `stage3b_images.py` plate prompt | Negative "no X" phrasing → positive style tokens only | Qwen3-VL encoder activates concepts mentioned negatively; "no kanji" triggers kanji. Now uses "clean linework, pure visual storytelling, cel shading" |

### Phase 2: World Space / Multi-Angle Plates

**Problem:** One plate per `location__time_of_day` — all scenes sharing a location reused the exact same 512×512 plate. No establishing shots, no angle variation, no "room layout" persistence.

**Solution:** Plate key now includes `camera_angle` from storyboard shot data.

| Change | File | Description |
|---|---|---|
| `location_angles` in WorldBible | `schemas/worldbible.py` | Each location gets `angles: ["wide_establishing", "medium_shot", "closeup_counter", "over_shoulder"]` with `get_location_angles()` helper |
| Plate key includes angle | `stage3b_images.py` | `_plate_key_for_scene(scene, shot)` → `loc__tod__angle` (e.g., `loc-cafe__morning__wide_establishing`) |
| Storyboard assigns `camera_angle` | `stage2_screenplay.py`, `prompts/s2_shot_plan.md` | LLM outputs `camera_angle` per shot; `_ShotOut` schema updated |
| Plate generation per `(location, time, angle)` | `stage3b_images.py` | World space built out with consistent multi-angle coverage instead of single flat backdrop |

### Phase 3: Rich User Control Nodes

Both `panel_img2img_plate_krea.json` (13→22 nodes) and `panel_img2img_plate_anima.json` (12→22 nodes) expanded:

| New Node | Patch Keys | Purpose |
|---|---|---|
| `ControlNetLoader` + `ControlNetApply` | `CONTROLNET_NAME`, `CONTROLNET_STRENGTH`, `CONTROLNET_REF_IMG` | Pose/composition guidance from reference (OpenPose, Canny, Depth) |
| Regional `CLIPTextEncode` (A/B) | `REGIONAL_PROMPT_A_TEXT`, `REGIONAL_PROMPT_B_TEXT` | Different prompt per image region via `ConditioningCombine` |
| `LoraLoader` (style) | `STYLE_LORA_NAME`, `STYLE_LORA_STR_MODEL`, `STYLE_LORA_STR_CLIP` | Per-shot art style variation (watercolor, ink, cel shade variant) |
| `LoadImage` + `ImageCompositeMasked` | `CHARACTER_MASK_IMG` | Masked character insertion without affecting background |
| `ColorCorrect` | `COLOR_TEMP`, `SATURATION`, `CONTRAST`, `GAMMA`, `LIFT_*`, `GAIN_*` (10 params) | Per-shot color grading / lighting adjustment |

All new knobs exposed in `stack.toml [animation]` with sensible defaults (disabled by default, enabled via config).

### New Tests Added

`tests/test_stage3b_new_features.py` — 15 tests covering:
- WorldBible location angles helpers
- `_plate_key_for_scene` with 4 angles + defaults + normalization
- `_ShotOut.camera_angle` schema
- Patch key generation for all 5 new control surfaces
- Feature flags default correctly (all off except color_grade)
- Workflow JSON structure validation (both krea2 and anima)
- `manifest.json` patchable keys completeness

All 62 pipeline tests pass (47 original + 15 new).

---

## 2. What we tried — chronology

| Date | Attempt | Outcome |
|---|---|---|
| 2026-07-09 | **Windows→Linux reboot.** Repo was lost once on a Windows reinstall; rebuilt from a recovered spec under `E:\AI\Models\hermes\skills\local-agent-hub-ops\`. | Olympus / pipeline wiring restored. |
| 2026-07-10 | **ComfyUI 0.24 → 0.27.1 upgrade** under work order COMFY-UPDATE. Torch / pydantic pins held. 0/10 templates regressed. | Unblocked krea2 `CLIPLoader.type=krea2` enum. |
| 2026-07-10 | **krea2 lab proof render** at 1216×704, 8 steps. | 113.7 s, peak 7782 MiB, clean cel-shaded anime output. **Adopted as image_primary.** Smoke marker written. |
| 2026-07-28 | **GGUF port of character_sheet + mouth_sheet** (were SDXL-only). | Both marked `ready` in manifest. |
| 2026-08-03 | **krea2 smoke revalidated** after `qwen3vl_4b_fp8_scaled.safetensors` repack landed. | 49.1 s with the 4B text encoder. The prior 4B blocker resolved. |
| 2026-08-04 | **Full audit + bug fix pass** (this session). Found and fixed four real bugs blocking the animation pipeline. | See §3. |
| 2026-08-04 | **Structural tidy-ups** (this session): removed dead `olympus/shared/`; world-bible schema re-exports; `.gitignore` gained `tools-external/`; M-AP-2 `video_router` wired. | See §3.6. |
| ongoing | Attempted but never wired in: SDXL anime checkpoints (`z-anime-distill-4step-fp8`, `wai-illustrious-v110`, `NoobAI-XL-v1.1`, `animagine-xl-4.0`) and `FLUX.1-Krea-dev`. | **All banned** by Amir per the ban-list §5.3b. |
| ongoing | Attempted but never wired in: SDXL IPAdapter for character-ref + scene-plate conditioning. | **Doesn't work on krea2** (different architecture). Replaced concept-for-concept by the krea2-native `krea2-identity-edit`, `krea2-style-reference`, `krea-2-depth-controlnet` (none installed yet). |
| ongoing | Attempted but never wired in: SDXL Hyper-LoRA speed distillation. | **Not needed** — krea2-Turbo is step-distilled at 8 steps already. |
| ongoing | lip-sync: `lipsync_overlap_avg` was listed as the mandatory metric for `stage3c`, but stage3c always hardcoded it to `0.0`. The gate was vacuous. | **Fixed this session:** mandatory metric is now `ltx_rendered`. |

---

## 3. Bugs found and fixed this session (2026-08-04)

All fixes live in `olympus/engines/pipeline/` and `olympus/kernel/app.py` only.
ComfyUI's vendored code was not touched.

### 3.1 Critical: `comfy_client._collect` dropped video outputs

`VHS_VideoCombine` (used by every LTX/Wan animation workflow) emits its produced
file under the ComfyUI history key `gifs`, not `images`, and the file lands
under `ComfyUI/temp/<subfolder>/<filename>` when `save_output=false`. The
previous `_collect` only handled the `images` key and only looked under
`ComfyUI/output/`, so:

- Every LTX I2V job the engine queued emitted `ComfyError("job completed but
  produced no images")` even though the clip was successfully written.
- Stage 3C's `tier1`/`tier2` paths therefore all fell back to Tier-0 drift.

**Fix:** `_collect` now reads both `images` and `gifs` UI keys and honors the
per-entry `type` field (`"output"` vs `"temp"`) to pick the right source root.
Tests added: `test_collect_handles_vhs_video_output`,
`test_collect_handles_vhs_temp_output`, `test_collect_raises_when_image_missing`.

### 3.2 Critical: scorecard gate for `stage3c` was vacuous

`MANDATORY_METRICS["stage3c"] = ["lipsync_overlap_avg"]` in `scores.py`, but
`stage3c_animation.py` always records `lipsync_overlap_avg: 0.0` because
lip-sync is an unimplemented contingency (design Stage 3C.5; the
`lipsync_contingency` scorecard flag is set to 1.0). A presence-only check on
a value that's always 0.0 always passes — the gate was vacuous. Worse, it
guaranteed the next stage (`stage_vlm_review` then `stage5`) would proceed even
if 0 LTX shots actually rendered.

**Fix:** Mandatory metric is now `ltx_rendered`, which measures real
animation work (≥1LTX clip actually rendered). Tests added:
`test_stage3c_mandatory_metric_is_ltx_rendered`,
`test_stage4_runs_when_stage3c_proves_rendered`.

### 3.3 Critical: kernel `pipeline_run_stage` silently swallowed all errors

The background worker had:

```python
def worker():
    try:
        prun.run_stage(slug, stage, projects_dir=project_dir.parent)
    except Exception:
        pass                          # <-- silent eat
    finally:
        with _lock_map: _locks.pop(key, None)
```

Consequence: any stage failure (ban list trip, ContingencyStop, FileNotFoundError,
runtime exception) was eaten. The dashboard UI status would sit on
`"running"` forever, the user had no signal, and the lock entry was cleaned
up so a second attempt would silently overlap.

**Fix:** The worker now captures the exception, writes a `<stage>.error`
sidecar file under `<project>/logs/`, and updates the blueprint's `StageEntry`
to `failed` with a real timestamp. The lock is still released. Errors don't
disappear downstream anymore.

### 3.4 Medium: stale `qwen2.5vl:7b` comments in `stage3b_images.py`

The docstrings and module-header comments still cited `qwen2.5vl:7b` for the
vision-judge, but `stack.toml` already moved to `qwen3-vl:8b` (the original
`qwen2.5vl:7b` miscounted character counts on dense anime panels — the move
was the rationale documented in `stack.toml` line 18, but never propagated to
the stage code comments). Confusing for anyone reading the stage code.

**Fix:** Comments updated; the actual code already used `config.models.llm_vision`
which loads from `stack.toml` so behavior was correct — only the comments were
lying.

### 3.5 Medium: stale `NODES.md` references to deleted templates

`NODES.md` described four video templates: `ltx_ambient.json`,
`ltx_director.json`, `wan_ti2v.json`, `lora_dataset_prep.json`. Of those, the
two LTX files no longer exist — they were replaced by `ltx22b_i2v.json` and
`ltx23_i2v_8gb.json`. Anyone reading `NODES.md` for orientation would have
been misled into thinking the animation path was unshipped.

**Fix:** `NODES.md` §3 was rewritten to describe the actual four video
templates that exist on disk, including the ltx23_8gb "experimental / not wired
in" status. §4 stage graph row for `stage3c` updated to mention the new proof
metric `ltx_rendered`.

### 3.6 Structural tidy-ups (2026-08-04)

- **Dead `olympus/shared/` package removed.** The three files
  (`__init__.py`, `lib/__init__.py`, `lib/config.py`) had zero imports anywhere
  in the repo; `lib/config.py` was already deleted on disk leaving two empty
  `__init__` shims. Removed the empty shims and the package directory.
- **`schemas/__init__.py` now re-exports world-bible models.** The package
  head re-exported `Blueprint` + stage-0 contracts but not the `worldbible`
  classes (`WorldBible`, `Character`, `Appearance`, `SpeechStyle`,
  `Personality`, `ArcThisEpisode`, `Provenance`) that stages 1R/1/2/3B import
  from `.schemas.worldbible` directly. Consumers can now import the whole
  schema surface from one namespace.
- **`.gitignore` gained `tools-external/`.** The `tools-external/` dir
  (kohya `sd-scripts`, `skills-audit`, ~5.6 GB on disk) is external tooling,
  not source, and was flowing through untracked-file listings.
- **`comfy_client._collect` gifs branch** (see §3.1) confirmed as the only
  place LTX/Wan outputs are gathered — no second copy path exists to drift
  from.

---

## 4. What works end-to-end now

After this session's fixes, the verified-working matrix:

| Path | Status |
|---|---|
| Stage 0 → 2 (intake, world bible, references, screenplay) | ✅ fully working, all tests pass, fully local via qwen3:8b |
| Stage 3 (storyboard block/shot plan) | ✅ working |
| Stage 3B (krea2 panels + qwen3-vl:8b vision judge) | ✅ working when krea2 is reached; falls back to flux1-schnell automatically if krea2 weights are missing or smoke-gate not passed |
| Stage 4 (Kokoro TTS + alignment) | ✅ working |
| Stage 3C Tier-0 (CPU drift, no GPU) | ✅ working |
| **Stage 3C Tier-1/2 (LTX image-to-video via the real ltx22b_i2v workflow)** | ✅ **now actually executable** after the `_collect` fix. Previously silently fell back to Tier-0 drift even when ComfyUI had rendered the clip. |
| Stage 5 (ffmpeg assembly + chapters + srt) | ✅ working |
| Kernel dashboard `/api/pipeline/.../run/<stage>` (background stage run + status) | ✅ **now surface real failures** instead of silently hanging on "running" |

---

## 5. Forward plan — concrete milestones for the ComfyUI anime pipeline

This plan is intentionally small, milestone-gated, and uses the same
scorecard-discipline pattern the rest of the stack already uses. Each
milestone has a definition-of-done and the verification step the manager can
run.

### M-AP-1: Validate the ltx22b I2V end-to-end run (proves the §3.1 fix)

**Goal:** Run stage3c on a real project with at least one shot at Tier-1 and
prove the clip is actually collected into `projects/<slug>/clips/` and the
storyboard JSON records `motion_tier: 1` instead of `0`.

**Definition of done:**

- A `stage3c` run against a project with one Tier-1 shot returns
  `ltx_rendered >= 1` in its scorecard.
- `projects/<slug>/clips/sh-...mp4` exists on disk and is a valid MP4
  (`ffprobe` reports a video stream).
- `screenplay.json` has `motion_tier: 1` for that shot.
- No "produced no images" `ComfyError` in the stage log.

**Verify:** `run.py report <slug>` shows `stage3c DONE metrics={...ltx_rendered: 1.0...}`.

### M-AP-2: Wire the ltx23_i2v_8gb template into stage3c as a tier-2 / high-res path

**Goal:** `stage3c_animation.py` currently hardcodes
`_LTX_TEMPLATE = "ltx22b_i2v.json"`. The `ltx23_i2v_8gb.json` template uses a
different node graph (`LTXVAddGuide` + `LTXVTiledSampler` instead of
`LTXVImgToVideo` + `SamplerCustomAdvanced`) that tolerates longer frame
counts and tiled decoding better on 8 GB. There should be a small
`pick_ltx_template()` helper in `pipeline/image_router.py` (or a sibling
`video_router.py`) that picks the tile-friendly path when `motion_tier == 2`
or when the shot requests `FRAMES > 81`, and the ltx22b path otherwise.

**Status (2026-08-04):** ✅ **Implemented this session.** New
`pipeline/video_router.py` exposes `pick_ltx_template(tier, frames) -> str`;
`stage3c_animation.py` calls it once per shot (replacing the module-level
`_LTX_TEMPLATE` constant) and records the chosen template in the shot's
`ltx_template` field. Tests in `tests/test_video_router.py` cover
tier→template selection. The ltx22b path remains the default for Tier-1 /
≤81-frame shots; `ltx23_i2v_8gb.json` is now selected for Tier-2 / >81-frame
shots.

**Remaining (unchanged):** a real Tier-2 render must run through the new
route before `ltx23_i2v_8gb.json`'s manifest status moves from `experimental`
to `ready`.

**Definition of done:**

- New `pipeline/video_router.py` with `pick_ltx_template(tier, frames) -> str`.
- `stage3c_animation.py` calls it once per shot, replacing the module-level
  `_LTX_TEMPLATE` constant.
- The manifest's `ltx23_i2v_8gb.json` status moves from `experimental` to
  `ready` after a real render via the new path.
- New unit test `test_video_router.py` covering tier→template selection.

**Verify:** `run.py run <slug> stage3c` with one Tier-2 shot queues `ltx23_i2v_8gb.json`,
collects the clip (via the §3.1 fix to `_collect`), scorecard records
`ltx_rendered >= 1` and `tier2_director_shots >= 1`.

### M-AP-3: LTX dual-CLIP + VAE safety check (model_lab gate for animation)

**Goal:** Image work has `tools/model_smoke.py` + the `.krea2_smoke_passed`
marker gating `image_router.pick_template`. Video work has no equivalent —
`stage3c` will happily queue `ltx22b_i2v.json` even if
`ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf` is half-downloaded or the
`ltx-2.3_text_projection_bf16.safetensors` text encoder isn't on disk yet.
This will trip a `ComfyError` at queue time and burn a VRAM cycle.

**Definition of done:**

- New `tools/ltx_smoke.py` mirroring `model_smoke.py` — queues a smoke LTX
  render (small: 480×270 × 17f, 6 steps) and writes
  `.ltx_smoke_passed` on completion.
- New `video_router.pick_ltx_template` refuses to route to either LTX
  template unless `.ltx_smoke_passed` exists AND the three weights named in
  the ltx22b/ltx23 graphs are each >500 MB on disk.

**Verify:** With `.ltx_smoke_passed` absent, `stage3c` falls back to Tier-0
drift for every Tier-1/2 shot and records `ltx_contingency: 1.0`. After a
successful smoke, it routes normally.

### M-AP-4: GPU scheduling — `comfy.unload_ollama()` and `comfy.free()` in the right order

**Goal:** `Stage3b` calls `comfy.unload_ollama()` once at the top, then
`comfy.free()` between every panel (heavy but reliable per the in-code
comment). `Stage3c` calls `comfy.unload_ollama()` once before the LTX loop
and `comfy.free()` once after the whole loop. This is mostly correct but
LTX runs longer per shot — if the kernel's `conductor` agent fires a
*qwen3:8b planner* call mid-batch (e.g. next-stage TTS planning), Ollama will
load the model back into the same VRAM LTX is mid-sampling on, and they OOM
each other.

**Definition of done:**

- A small `gpu_lock.py` context manager in `pipeline/` (or extend
  `ComfyClient`) that:
  - On enter, calls `comfy.unload_ollama()`.
  - Holds a Python `threading.Lock` for the duration of one GPU-batch.
  - On exit, calls `comfy.free()`.
- Stages 3B and 3C use the context manager around their generation loops.
- The kernel's `pipeline_run_stage` worker acquires the same lock on its
  thread if it's about to call any LLM Ollama traffic during a stage that
  could be GPU-heavy.

**Verify:** A 3B run concurrent to a kernel `/api/tasks` POST that issues an
Ollama call cannot OOM each other — at least one waits. Scorecard gets a new
`gpu_lock_blocked_ollama` counter.

### M-AP-5: Stage 3C storybook motion-tier assignment provenance

**Goal:** `stage3_storyboard.run` assigns `motion_tier` per shot, and
`stage3c` currently *overwrites* `motion_tier` to 0 for Tier-1/2 shots while
the LTX render is in flight (preserving the original as `planned_tier`).
The overwriting is fine, but the audit trail is fragile: only `planned_tier`
and `motion_tier` are written, with no record of *why* a shot was Tier-1 vs
Tier-2 (composition cue? camera_movement field? motion-budget heuristics?).

**Definition of done:**

- `storyboard.json` per-shot entry gains a `motion_tier_reason` field set by
  `stage3_storyboard` (not stage3c) — the human-readable cue that pushed the
  shot to its tier.
- `stage3c` records `planned_tier`, `motion_tier`, and the LTX run outcome
  in a per-shot sidecar `clips/<sid>.json` (parallel to stage3b's
  per-panel sidecar).

**Verify:** `run.py report <slug>` surfaces motion-tier breakdown with
reason strings; missing reasons fail a new `tests/test_stage3_storyboard.py`
check.

### M-AP-6: lip-sync — actually wire up the `mouth_sheet.json` workflow

**Goal:** Tier-3 shots (lip-sync pending) and the `lipsync_contingency`
scorecard flag both currently read 1.0 because lip-sync is unimplemented.
`mouth_sheet.json` was GGUF-ported on 2026-07-28 but is never called. The
`align.py` whisperX alignment step in stage4 *does* produce a viseme
timeline that the flipbook would consume — there's a gap of zero stages
between the alignment data and the lip-sync rendering, just no code bridge.

**Definition of done:**

- New `pipeline/lipsync.py` function `render_mouth_flipbook(shot, panel,
  viseme_timeline, comfy) -> Path[mp4]` that:
  - Loads `mouth_sheet.json`.
  - For each viseme event in `alignment_coverage >= 0.6`, queues the
    inpaint with the appropriate `VISEME_PROMPT`.
  - Concatenates the per-frame viseme PNGs into a short MP4 via ffmpeg with
    the alignment's frame-rate.
- Stage 3C Tier-3 path drives this instead of skipping.
- The `lipsync_contingency` scorecard flag reflects whether lip-sync was
  actually performed, not whether it was planned.

**Verify:** One shot with `motion_tier=3` produces a `clips/<sid>.mp4` with
mouth shape animation matching the alignment's word boundaries. New
`tests/test_stage3c_lipsync.py` exercises the bridge with a mock `ComfyClient`
and a fixed alignment JSON fixture.

### M-AP-7: krea2 identity & style reference (replaces the deprecated SDXL IPAdapter)

**Goal:** Several image stages (3B in particular) currently rely on a
prompt-engineered `_count_clause` ("exactly one character in the frame: ...
single figure, no other people, no duplicate copies") because krea2 has no
character LoRAs wired in (design 3B.5 deviation) and SDXL IPAdapter doesn't
work on krea2. Amber-style identity reference would be a meaningful step up
in character consistency.

**Definition of done:**

- Install the `krea2-identity-edit` and `krea2-style-reference` custom-node
  helpers (or, if KJNodes already exposes the primitives, surface them in a
  new `panel_krea2_ref.json` workflow with a patchable `REF_IMAGE_CHAR` /
  `REF_IMAGE_STYLE` map).
- Stage 3B's generation path uses this template (per scene / per character)
  instead of, or in addition to, the `_count_clause` prompt trick.
- The first 5 panels run through vision-judge QC with the new template;
  record `prompt_adherence_avg` and `vision_fail_rate` deltas vs the
  current path in a side-by-side scorecard.

**Verify:** Without touching any code, mount the new template and re-run 3B
on a sample project; the post-fix `prompt_adherence_avg` should not regress
(vs the prompt-only baseline) and `vision_fail_rate` should drop by
≥ 25% on character-dense shots.

### M-AP-8: Music bed + SFX (the last "contingency" gap)

**Goal:** Stage 5 has SFX tags from stage 3 but no music bed; the design's
"copyright gate on music" is recorded as a TODO. With the rest of the
pipeline now executable end-to-end, the music bed is the last large
artistic gap.

**Definition of done:**

- Either a local CC0/library cue lookup (MusicCat.apk? royalty-free local DB?)
  OR a tiny local music model (e.g. MusicGen-small, on-device) spun up only
  when the GPU is free.
- Stage 5 `assembly` queues one of those per scene-emotion tag.
- `final.mp4` gains a soundtrack track + chapter sync.

**Verify:** Run `run.py run <slug> stage5`; `ffprobe` reports an audio stream
in `final.mp4`. The new `music_source` scorecard field records where it came
from (lib, model_generated, none).

---

## 6. Suggested execution order

1. **M-AP-1** (no code change — just run stage3c once and confirm). Right now,
   after the §3.1 fix in this session, this should "just work" but is
   unverified — it's the highest priority because it uncovers any further
   real-world LTX bugs the unit tests can't see.
2. **M-AP-3** (`ltx_smoke.py` gate) — short, prevents wasting GPU cycles
   on misconfigured weight dirs. **Now more urgent:** with `video_router`
   routing Tier-2 shots to an `experimental` template (M-AP-2), a broken
   ltx23 graph would burn VRAM cycles before falling back to drift — the
   smoke gate catches that before the first real render.
3. **M-AP-2** ✅ done (code + tests landed this session) — remaining work is
   the single real Tier-2 render to promote `ltx23_i2v_8gb.json` to `ready`.
4. **M-AP-5** (storyboard motion-tier provenance) — quality-of-life /
   audit-trail.
5. **M-AP-4** (GPU lock) — only matters once we start doing concurrent
   kernel agent work + 3B/3C generation; lower priority until then.
6. **M-AP-6** (lip-sync bridge) — closes a long-standing contingency with
   working parts on disk.
7. **M-AP-7** (krea2 identity ref) — quality jump on character consistency;
   needs the krea2-style ref helpers.
8. **M-AP-8** (music bed) — last for artistic completeness.

---

## 7. Open questions for Amir

1. **Quant ladder:** is `Q4_K_S` acceptable for production, or should we drop
   to `Q3_K_S` (6.01 GB) for more VRAM headroom with a LoRA loaded? Measurable
   once M-AP-7 starts stacking inferences.
2. **Krea-2 Community License content filter:** the license obligates
   deployer-side content filtering if outputs are published. For local-only
   recap videos this is low-friction. Flagging if you ever publish episode
   outputs.
3. **Wan 5B vs LTX 2.3 22B for the only animation path?** Wan 5B is t2v-only
   (no I2V cross-attn weights in the 5B), so on this 8 GB card it can't be
   the per-shot I2V model the way LTX 2.3 is. Wan 2.2 I2V-A14B does have I2V
   weights, but the 14B doesn't safely fit even with block-swap on 8 GB
   VRAM. Recommendation: keep LTX 2.3 as the only I2V path; keep Wan-T2V
   only for "establishing shot / abstract motion" tier-3 work where the
   start frame isn't a panel.
4. **Approval to update `docs/planning/anime-pipeline-v2-design.md`?** That
   design doc still describes the SDXL-era image path (Hyper LoRA,
   turnaround LoRA, dual IPAdapter) and is partially obsolete now that
   krea2 is the primary. The plan in this document supersedes its
   `§5.3b (image_stages)` wording; consider folding this doc into the
   design or marking the design as superseded/updated.
