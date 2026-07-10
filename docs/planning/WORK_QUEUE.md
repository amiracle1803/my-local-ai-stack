# Builder Work Queue (state as of 2026-07-09 ~19:35)

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

## AFTER THOSE: M1 work order (Stage 0B Generate, needs qwen3:8b present)
