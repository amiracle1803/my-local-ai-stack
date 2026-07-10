# ComfyUI Node Additions — Complete Plan (final, 2026-07-09)

> Scope contract for the builder: **only what is listed here gets installed
> or created.** Anything else is scope creep and must come back to Amir.

## A. Installed & verified (do NOT reinstall)

| Piece | State | Role |
|---|---|---|
| ComfyUI core **0.27.1** @ `C:\AI\ComfyUI` (E: = weekly mirror) | running, service-managed :8188 | everything (updated 0.24.0 → 0.27.1 on 2026-07-10 for krea2 support; git v0.24.0-60 `822aca19` → tag v0.27.1 `c2638ce6`; torch/pydantic pins held; 10/10 templates revalidated) |
| Core LTX nodes (LTXVImgToVideo/Conditioning/Scheduler/AddGuide…) | **installed** — in core, verified in /object_info (ltx_ambient/ltx_director templates PASS on 0.27.1) | Tier 1/2 motion |
| ComfyUI_IPAdapter_plus + `ip-adapter-plus_sdxl_vit-h` + CLIP-ViT-H | installed | char ref + scene plate conditioning |
| ComfyUI-WanVideoWrapper + KJNodes | installed | Wan2.2 Tier-2 alternate |
| ComfyUI-GGUF | installed | flux1-schnell fallback quants |
| ComfyUI-Manager | installed | node pack management UI |
| **ComfyUI-WD14-Tagger** (`WD14Tagger\|pysssss`) | **installed 2026-07-09, CUDA ORT verified** | LoRA dataset captioning |
| RES4LYF / rgthree / Easy-Use / ControlAltAI | installed | samplers/QoL, no dependency |

## B. Remaining additions (in order, each gated)

1. **krea2 checkpoint** — **INSTALLED & PROVEN 2026-07-10.** Krea-2-Turbo GGUF
   Q4_K_S (`krea2_turbo-Q4_K_S.gguf` unet + `qwen3vl_4b_fp8_scaled.safetensors`
   text encoder + `qwen_image_vae.safetensors` VAE) on disk. Proof render on
   0.27.1: 1216×704, 8 steps, 113.7 s, peak 7782 MiB VRAM, clean on-prompt
   anime output (see docs/planning/krea2-lab-report.md). Adopted as
   image_primary. Banned alternates never substituted (design §5.3b BAN LIST).
2. **krea2-compatible LoRA re-ecosystem** (training artifacts, not nodes):
   turnaround LoRA + anime-style LoRA + all character LoRAs must target
   krea2's architecture (the on-disk SDXL LoRAs won't load on it). Trained
   via kohya_ss CLI (item 4).
3. **ControlNet `xinsir/controlnet-union-sdxl` model file** — CONDITIONAL,
   only if M4 shows turnaround quality is insufficient without pose control
   AND krea2's architecture supports it (else find its ControlNet equiv).
   Default: skip.
4. **kohya_ss (sd-scripts)** — external CLI, own venv at `E:\AI\kohya_ss`
   (NOT inside ComfyUI). LoRA training for style/character/asset.
5. **RIFE (rife-ncnn-vulkan)** — external CLI at `C:\Users\amire\Tools\rife\`.
   FPS interpolation. Never a Comfy node (VRAM discipline).
6. **RealESRGAN-anime (realesrgan-ncnn-vulkan)** — external CLI at
   `C:\Users\amire\Tools\realesrgan\`. Optional 1080p upscale.
7. **whisperX** — pip into the STACK venv (not ComfyUI's). Forced alignment
   for lip sync.
8. **anime-face-detector** (or equivalent) — pip into stack venv. Mouth bbox
   for viseme compositing.

## C. Custom node development: NONE

Zero custom ComfyUI nodes will be written. All pipeline logic lives in
Python (`olympus/engines/pipeline/`) driving the 8 workflow templates via
the API (patch-by-title contract in `workflows/manifest.json`). The
oscillating-drift stills, mouth compositing, audio mixing, and assembly are
ffmpeg/PIL work in the pipeline, not Comfy graphs.

## D. Install discipline (every item above)

- One at a time; pinned commit/version recorded in this file when installed.
- pip deps go into the CORRECT venv (ComfyUI's for node packs, stack venv
  for pipeline libs); NEVER upgrade `torch==2.6.0+cu124` / pydantic pins.
- After any ComfyUI-side change: restart via the services API, then verify
  `/object_info` still parses and expected classes exist, then run
  `model_lab test-workflows` (once it exists).
- Update this table + commit via `scripts\backup-code.ps1`.
