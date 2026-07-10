# Builder Work Queue

## STATE 2026-07-10 ~00:30 (session limit hit again; resets 04:50 ET)

Fable's disk inventory (verified, trust this over dead builders' silence):
- **INSTALL-1: effectively COMPLETE, unreported.** qwen3:8b + qwen2.5vl:7b
  pulled; ltx-video-2b-v0.9.5 (5.91 GB) + t5xxl_fp8 encoder staged; BOTH LTX
  templates + manifest updated with T5_ENCODER node (verified good); **LTX
  proof render exists** (C:\AI\ComfyUI\output\ltx_install1_proof_00001_.webp);
  RIFE + RealESRGAN in C:\Users\amire\Tools; whisperx 3.8.6 in stack venv;
  kohya at E:\AI\kohya_ss with venv python present (dep completeness
  unverified). Outstanding: node-additions-plan.md §B updates,
  anime-face-detector decision, kohya --help sanity check.
- **M1: PARTIAL.** pipeline/llm.py (12 KB) + chunking.py written, quality
  unreviewed; stage0_intake.py, schemas/stage0.py, prompts/*, run.py wiring,
  tests NOT done. Redispatch must REVIEW the two existing files first.

## REDISPATCH AFTER 04:50 ET (in this order)
1. M1-finish (Sonnet) — review llm.py/chunking.py then complete M1 scope
2. STUDIO-API (Sonnet) — order text in Fable's ledger below
3. WF-2 (Haiku) — workflow cosmetic cleanup (see below)
4. COMFY-UPDATE (Sonnet) — 0.25 update + krea2 proof (see below)
5. INSTALL-1-closeout (Haiku) — kohya sanity, node-additions-plan.md update

# (original ledger follows)

> Fable's dispatch ledger. Builders died mid-flight when the plan's session
> limit was hit (resets 23:50 America/New_York). Redispatch both orders
> after reset. **Redispatched builders must FIRST inventory what the dead
> run already completed** (check `ollama list`, C:\AI\ComfyUI\models\*,
> C:\Users\amire\Tools\*, E:\AI\kohya_ss, pip show whisperx) and skip
> finished steps — the dead agents may have partially downloaded things.

## ACCEPTED (done, verified by Fable)
- M0 — pipeline skeleton (36 tests green, commit a0755e1)
- WF-1 — ComfyUI workflow build-out (9/9 validate, commit 4e7b3e8)

## PENDING REDISPATCH

### INSTALL-1 (approved by Amir)
Original order: docs/planning/BUILDER_HANDOFF.md protocol; scope =
1. `ollama pull qwen3:8b` + `qwen2.5vl:7b`
2. Official Lightricks LTX 2B-class checkpoint into C:\AI\ComfyUI\models\
   checkpoints (+ T5 text encoder IF core LTX nodes need it; fix
   ltx_ambient/ltx_director templates + manifest if so)
3. One real minimal LTX render via API as proof (/history evidence)
4. RIFE + RealESRGAN-anime CLIs into C:\Users\amire\Tools\
5. whisperX (CPU torch first) + anime face detect into STACK venv
6. kohya sd-scripts + CUDA venv at E:\AI\kohya_ss (C:\AI\kohya_ss if E: down)
7. Update node-additions-plan.md §B with versions/sizes
No git; Fable commits.

### KREA-1 (UPDATED per Amir 2026-07-09 evening)
**krea2 = huggingface.co/krea/Krea-2-Turbo** (mirror ref:
civitai.com/models/2738703). **FLUX.1-Krea-dev is BANNED — do not fall back
to it.** Scope =
1. Fetch the Krea-2-Turbo model card; determine architecture, file list,
   license, VRAM needs; pick the file/quant that fits 8 GB (--novram).
   If the HF repo is gated: report — Amir's HF account is 'amiracle1803'.
2. Download into C:\AI\ComfyUI\models\<correct dir for its architecture>
   (+ any required encoders/VAE not already on disk).
3. Loader template panel_txt2img_krea.json matching its REAL architecture
   (read /object_info; don't assume FLUX-style or SDXL-style graphs) +
   manifest entry.
4. One real 1216x704 anime-style render via API; VRAM peak + sec/image.
5. docs/planning/krea2-lab-report.md with primary-model verdict + what M4
   must add (style LoRA path, turnaround equivalent, reference conditioning).
If Krea-2-Turbo cannot run on 8 GB in any offered form: STOP and report.
No git; Fable commits.

## DISPATCHED 2026-07-10 (Sonnet, per builder model policy)
- **M1** — Stage 0B Generate (3-pass) + PipelineLLM + chunking. Parallel-safe
  (pipeline package files only).
- **STUDIO-API** — kernel /api/pipeline endpoints + Studio page stage-ledger
  wiring. Parallel-safe (kernel + web files only).

## BLOCKED ON INSTALL-1 COMPLETION (dispatch when it reports)
- **WF-2 (Haiku)** — workflow cosmetic cleanup: placeholder PNGs into
  C:\AI\ComfyUI\input\; set real on-disk model defaults in every template
  where a legal file exists (LTX ckpt+T5, Wan, krea2 trio, WD14); regenerate
  UI sidebar graphs via tools/api2ui.py; run validate_workflows.py.
- **COMFY-UPDATE (Sonnet)** — ComfyUI 0.24.0 -> >=0.25 in place on C:
  (git pull to a tagged release; hold torch/pydantic pins; E:\AI\ComfyUI
  mirror = rollback). Gates: 9/9 template regression via validator, THEN the
  krea2 proof render (1216x704, VRAM peak, sec/image) + finish
  krea2-lab-report.md sections 2/4. Roll back from mirror on any breakage.

## KREA-1 — ACCEPTED 2026-07-10 (commit bef70d1); proof render pending COMFY-UPDATE
