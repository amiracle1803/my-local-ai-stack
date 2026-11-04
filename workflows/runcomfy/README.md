# RunComfy Workflow Library — Local Adaptation

> **Goal:** a human-readable library of curated RunComfy.com workflows downloaded for your
> local ComfyUI (`:8188`), cross-referenced against what you already have installed, so we can
> see which ones can run on your **RTX 4070 Laptop (8GB VRAM)** and what changes each needs.

> 🧭 **AI agents: read [`AGENT-GUIDE.md`](./AGENT-GUIDE.md) FIRST.** It distills the hardware
> rules, which workflows run vs. need modification vs. skip, the important nodes, known
> blockers, and a playbook for building workflows that fit 8GB VRAM. This matrix below is the
> reference data; the guide is the decision framework.

## Folder layout
```
workflows/runcomfy/
├── _raw/        # original RunComfy workflow JSON (as-downloaded)
├── _analysis/  # one human-readable .md per workflow (nodes + models + status)
├── _assets/    # (empty) place for downloaded models/loRA later
└── README.md   # this master matrix + modification guide
```

## How this was built
- Workflows downloaded from RunComfy's public JSON endpoint (`/api/workflow-json/{id}`).
- Each workflow parsed to extract: required **custom nodes**, referenced **model filenames**.
- Cross-referenced against `ComfyUI/models/` (108 files) and `ComfyUI/custom_nodes/` (24 pkgs).
- **Note:** `runcomfly.com` in your request = actual site **runcomfy.com**.

## Hardware reality check (8GB VRAM)
- ✅ **Runs great:** Anima Base (2B), Krea 2 Turbo, FLUX.2 Klein **4B**, Qwen-Image GGUF, all TTS, upscalers.
- ⚠️ **Borderline (needs GGUF quant + `--novram` offload):** Wan 2.1/2.2 14B video, LTX 2.x video.
- ❌ **Cloud-only (won't fit / impractical):** LTX 2.3 22B, MiniMax H3, SkyReels multi-model stacks, SeedVR2.
- 🔴 **GPU scheduling (per AGENTS.md):** video-gen and LLM work OOM each other — never run both at once.

## Master Compatibility Matrix

Legend: **🟢 Ready** = runs now / trivial · **🟡 Easy** = install 1 custom node + few models ·
**🟠 Moderate** = several nodes/models + GGUF/offload tuning · **🔴 Heavy** = cloud-scale, needs heavy rework

| ID | Workflow | Custom nodes to add | Models to download | Grade |
|----|----------|--------------------|--------------------|-------|
| **Setup status (2026-08-20):** `ComfyUI-APISR` ✅ installed · `ComfyUI-See-through` ✅ installed · PMRF ⛔ disabled (NATTEN needs CUDA build for torch 2.7.1) | | | |
| 1082 | APISR | Anime Image/Video Super-Resolution | ComfyUI-APISR | 4x_APISR_GRL_GAN_generator.pth | 🟡 Easy |
| 1234 | PMRF Ultra Fast Upscaler | LOW VRAM | ComfyUI-PMRF | — | 🟢 Ready |
| 1300 | Wan 2.2 Animate V2 | Pose-Driven Video | ComfyUI-SAM2 | WanAnimate_relight_lora_fp16.safetensors, lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank256_bf16.safetensors, sam2.1_hiera_base_plus.safetensors, umt5_xxl_fp16.safetensors, vitpose-l-wholebody.onnx, Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors, Wan2_1_VAE_fp32.safetensors, yolov10m.onnx | 🟠 Heavy |
| 1307 | Wan 2.2 Animate | Character Swap & Lip-Sync | ComfyUI-SAM2 | Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors, WanAnimate_relight_lora_fp16.safetensors, lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors, sam2.1_hiera_base_plus.safetensors, vitpose-l-wholebody.onnx, yolov10m.onnx | 🟠 Heavy |
| 1321 | One to All Animation | OpenPose Motion | ComfyUI-OneToAll | Wan2.1-Fun-14B-InP-MPS.safetensors, detailz-wan.safetensors, lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank256_bf16.safetensors, Wan21-OneToAllAnimation_fp8_e4m3fn_scaled_KJ.safetensors, vitpose-l-wholebody.onnx, Wan21-OneToAllAnimation_fp8_e4m3fn_scaled_KJ.safetensors, yolov10m.onnx | 🟠 Heavy |
| 1322 | Controllable Animation | Motion Control Video | ComfyUI-SAM2 | lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors, sam3.pt, qwen/Qwen-Image-Edit-2509-Lightning-4steps-V1.0-fp32.safetensors, qwen/Qwen-Image-Edit-2509-Q5_1.gguf, qwen_2.5_vl_7b_fp8_scaled.safetensors, sam2_hiera_base_plus.safetensors, Wan2_2-I2V-A14B-HIGH_fp8_e4m3fn_scaled_KJ.safetensors, Wan2_2-I2V-A14B-LOW_fp8_e4m3fn_scaled_KJ.safetensors | 🟠 Heavy |
| 1330 | Qwen Image 2512 | T2I | — | Qwen-Image-2512-Lightning-4steps-V1.0-fp32.safetensors, qwen_2.5_vl_7b_fp8_scaled.safetensors, qwen_image_2512_bf16.safetensors | 🟡 Easy |
| 1334 | LTX-2 First & Last Frame | Key Frames Video | — | ltx-2-19b-distilled-lora-384.safetensors, ltx-2-19b-lora-camera-control-dolly-in.safetensors, ltx-2-19b-lora-camera-control-dolly-left.safetensors, ltx-2-19b-lora-camera-control-dolly-out.safetensors, ltx-2-19b-lora-camera-control-dolly-right.safetensors, ltx-2-19b-lora-camera-control-jib-down.safetensors, ltx-2-19b-lora-camera-control-jib-up.safetensors, ltx-2-19b-lora-camera-control-static.safetensors, gemma_3_12B_it.safetensors, ltx-2-19b-dev.safetensors, ltx-2-spatial-upscaler-x2-1.0.safetensors | 🟠 Heavy |
| 1335 | F5 TTS | Voice Cloning | ComfyUI-Whisper, ComfyUI-F5-TTS | — | 🟡 Easy |
| 1337 | FLUX.2 Klein 4B/9B | Ultra-Fast Image Gen | — | flux-2-klein-4b.safetensors, flux-2-klein-9b-fp8.safetensors, flux-2-klein-base-4b-fp8.safetensors, flux-2-klein-base-9b-fp8.safetensors | 🟡 Easy |
| 1339 | FLUX.2 Klein Unified Edit | Inpaint/Outpaint | ComfyUI-Impact-Pack, ComfyUI-LayerStyle | flux-2-klein-9b-fp8.safetensors | 🟡 Easy |
| 1356 | Flux Klein Face Swap | ComfyUI-SeedVR2 | dw-ll_ucoco_384_bs5.torchscript.pt, ema_vae_fp16.safetensors, flux-2-klein-9b-fp8.safetensors, seedvr2_ema_7b-Q4_K_M.gguf, yolox_l.torchscript.pt | 🟠 Moderate |
| 1369 | SkyReels V3 | I2V + Lip Sync + Audio | ComfyUI-MultiTalk, ComfyUI-MelBandRoformer, ComfyUI-MiniCPM | SkyreelsV3/Wan21-SkyReelsV3-A2V_fp8_scaled_mixed.safetensors, SkyreelsV3/Wan21-SkyReelsV3-V2V_fp8_scaled_mixed.safetensors, SkyreelsV3/Wan21-SkyReelsV3-V2V_shot_fp8_scaled_mixed.safetensors, lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank256_bf16.safetensors, Wan21_SkyReelsV3-R2V_fp8_scaled_mixed.safetensors, umt5_xxl_fp16.safetensors, wav2vec2-chinese-base_fp16.safetensors | 🔴 Heavy |
| 1374 | Fish Audio S2 TTS | ComfyUI-OtherNodes, ComfyUI-FishS2-TTS | — | 🟡 Easy |
| 1384 | Consistent Character Creator 3.8 | ComfyUI-Florence2, ComfyUI-UltralyticsDetector, ComfyUI-Impact-Pack | Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors, face_yolov8m.pt, flux1-dev-fp8.safetensors, qwen-image-edit-2511-Q5_1.gguf, qwen_2.5_vl_7b_fp8_scaled.safetensors, sigclip_vision_patch14_384.safetensors, uso-flux1-dit-lora-v1.safetensors, uso-flux1-projector-v1.safetensors | 🟠 Moderate |
| 1389 | See-through | Anime Layer Split PSD | ComfyUI-See-through | — | 🟡 Easy |
| 1398 | VNCCS Clone | Consistent Character | ComfyUI-VNCCS | — | 🟡 Easy |
| 1401 | MOSS TTS | Zero-Shot Voice Clone | ComfyUI-MossTTS | — | 🟡 Easy |
| 1410 | ChatterBox TTS | Multilingual Dialog | ComfyUI-ChatterBox | — | 🟡 Easy |
| 1414 | Wan2.2 Animate Action Transfer V7 | ComfyUI-OtherNodes, ComfyUI-Impact-Pack, ComfyUI_essentials, ComfyUI-LayerStyle, ComfyUI-UltralyticsDetector | FastWan_T2V_14B_480p_lora_rank_128_bf16.safetensors, SESELAORUYAO.safetensors, Wan2.2-Fun-A14B-InP-low-noise-HPS2.1.safetensors, Wan2.2-Lightning_T2V-A14B-4steps-lora_LOW_fp16.safetensors, Wan21_PusaV1_LoRA_14B_rank512_bf16.safetensors, Wan21_Uni3C_controlnet_fp16.safetensors, Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors, WanAnimate_relight_lora_fp16.safetensors, real_person_detection_v0_l_yv11.pt, sdpose_wholebody_fp16.safetensors, umt5-xxl-enc-fp8_e4m3fn.safetensors, vitpose-l-wholebody.onnx, yolo11x-pose.pt, yolov10m.onnx | 🟠 Heavy |
| 1421 | Char & Pose & BG Replacement V3 | Wan2.2 | ComfyUI-Impact-Pack, ComfyUI-LayerStyle, ComfyUI-SAM2, ComfyUI-UltralyticsDetector, ComfyUI-OtherNodes, ComfyUI-Inspire-Pack | Wan2.1-Fun-14B-InP-HPS2.1_reward_lora_comfy.safetensors, Wan21_PusaV1_LoRA_14B_rank512_bf16.safetensors, Wan21_Uni3C_controlnet_fp16.safetensors, Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors, WanAnimate_relight_lora_fp16.safetensors, lightx2v_I2V_14B_480p_cfg_step_distill_rank256_bf16.safetensors, rt_detr_v4-x-hgnet_fp16.safetensors, sam3.1_multiplex_fp16.safetensors, sdpose_wholebody_fp16.safetensors, umt5-xxl-enc-fp8_e4m3fn.safetensors, vitpose-l-wholebody.onnx, yolov10m.onnx | 🔴 Heavy |
| 1425 | LTX 2.3 Director | Timeline Filmmaking | — | ltx-2.3-22b-distilled-lora-fro90_ceil72.safetensors, ltx2.3-ic-subtitles-remove-general.safetensors, taeltx2_3.safetensors | 🔴 Heavy |
| 1438 | Anima Base v1 | Anime Cyberpunk T2I | — | — | 🟢 Ready |
| 1444 | SCAIL-2 Motion Transfer | Ref Image to Video | ComfyUI-SCAIL, ComfyUI-Impact-Pack, ComfyUI-SAM2 | WanAnimate_relight_lora_fp16-new.safetensors, clip_vision_vit_h.safetensors, lightx2v_I2V_14B_480p_cfg_step_distill_rank128_bf16.safetensors, sam3.1_multiplex_fp16.safetensors, wan2.1_14B_SCAIL_2_fp8_scaled.safetensors, wan_2.1_vae_Comfy-Org.safetensors | 🔴 Heavy |
| 1447 | IndexTTS2 | Emotional Voice Clone | ComfyUI-IndexTTS | — | 🟡 Easy |
| 1450 | Krea 2 Turbo T2I | — | — | 🟢 Ready |
| 1451 | Krea 2 Turbo I2I | Style Switch | ComfyUI-llama-cpp | Qwen3.5-9B-Q8_0.gguf, Qwen3.5-9B-mmproj-BF16.gguf | 🟢 Ready |
| 1456 | Krea 2 Style Transfer | ComfyUI-OtherNodes | — | 🟢 Ready |
| 1460 | Krea 2 Muse | Portrait/Concept | ComfyUI-Binyuan | krea2MuseByStable_v15TurboFp8.safetensors | 🟡 Easy |
| 1462 | Consistent Character Creator 4.0 | FLUX.2 | ComfyUI-Impact-Pack | Flux2-Klein-9B-consistency-V2.safetensors, flux-2-klein-9b-fp8.safetensors | 🟡 Easy |

## Recommended for YOUR anime-recap pipeline

**✅ Installed & verified (2026-08-20) — drag the workflow into ComfyUI :8188 and run:**
1. **1082 APISR** — anime upscaler. Node installed + `4x_APISR_GRL_GAN_generator.pth` in `models/apisr/`.
2. **1389 See-through** — anime layer split → PSD. 7 nodes installed; models auto-download on first use (use NF4 for 8GB VRAM).

**⛔ Tried but not viable:** **1234 PMRF** — needs NATTEN (no wheel for torch 2.7.1). Disabled. Use APISR or 4x-AnimeSharp instead.

**Tier 1 — use now (models already on disk or 1 small download):**
1. **1438 Anima Base v1** — anime T2I. All 3 models already installed. Import + run.
2. **1450/1451/1456 Krea 2 Turbo** (T2I/I2I/style) — your existing panel generator.
3. **1335 F5 TTS / 1447 IndexTTS2 / 1410 ChatterBox** — TTS alternatives to Kokoro.
4. **1337 FLUX.2 Klein 4B** — fast image gen (use the 4B, not 9B, for VRAM).

**Tier 2 — good but needs node/model installs:**
- **1398 VNCCS Clone / 1462 Consistent Character 4.0** — character consistency (your #1 need).
- **1307/1300 Wan 2.2 Animate** — character motion; needs 14B GGUF + SAM2 + controlnet_aux.

**Tier 3 — heavy / cloud-oriented (skip unless willing to rework):**
- LTX 2.3 22B Director, SkyReels V3, SCAIL-2, SeedVR2 — 20B+ models, multi-GPU workflows.

---
## ⚠️ Accuracy note on model detection
The automated extractor reads model filenames from node **widget values** (loader/VAE/CLIP/sampler
nodes). Some workflows store model paths in **node inputs** or in `MarkdownNote` guide text instead —
those won't appear in the "Models to download" column. Before running any workflow, open it in
ComfyUI and click **missing-node / missing-model** detection (or the "Try to load" prompt) to get the
definitive list. The column is a strong *signal*, not a guarantee.

## ⚠️ Importable vs. cloud-stub JSON
RunComfy exports fall into two kinds:
- **Full graph** (most): a complete, importable ComfyUI graph — drag into `:8188` and it works.
- **Cloud stub** (a few): only 3–8 nodes, some with UUID `type` fields — this is a *launcher* for their
  cloud, **not** a complete local graph. Affected: **1438 Anima Base**, **1450 Krea 2 Turbo T2I** (and
  a few UUID stubs inside 1337/1398/1462). For these, use the **official template** instead:
  - Anima Base → Comfy-Org "Anima Base v1" template (you already have all 3 models).
  - Krea 2 Turbo → your existing local krea2 workflow.

## Per-workflow files
Each `_analysis/<id>.md` has the same detail for one workflow: custom nodes (with install status),
models (missing vs. on-disk), and the 8GB VRAM grade.
