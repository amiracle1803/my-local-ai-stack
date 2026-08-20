# ComfyUI Workflow Agent Guide — RTX 4070 Laptop (8GB VRAM)

> **Who this is for:** AI agents (Claude/OpenCode/any builder) and human users who need to
> pick, adapt, or *create* ComfyUI workflows that actually run on this specific machine —
> instead of blindly importing cloud-targeted workflows and watching them OOM or crawl.
>
> **Companion docs:** `README.md` (the workflow library + matrix) and `_analysis/*.md`
> (per-workflow breakdown). Read this first, then those.

---

## 1. The hardware reality (read this before ANY workflow choice)

This is a **single mid-range laptop GPU with a hard VRAM ceiling**. Everything else in
this guide is downstream of this fact.

| Property | Value | Why it matters |
|---|---|---|
| GPU | NVIDIA GeForce RTX 4070 **Laptop** | Not desktop — lower power/thermal budget |
| VRAM | **8.2 GB** (`vram_total` 8,188,788,736 B) | The hard ceiling. Models >8GB must be offloaded |
| RAM | 33 GB (10 GB free at runtime) | Offload target — CPU/System RAM absorbs overflow |
| ComfyUI | 0.33.0 | Uses **subgraph** templates; model format support |
| torch | **2.13.0+cu130**, CUDA 13.0 | Defines what prebuilt extension wheels exist |
| Runtime flags | `--lowvram --cache-lru 4 --preview-method none` | Aggressive VRAM offload already on |

### The three golden rules for 8GB

1. **Model size class decides everything.**
   - 🟢 **≤ ~6GB total model set** → runs comfortably.
   - 🟡 **~6–12GB** → needs GGUF quantization + `--lowvram`/`--novram` offload; slow but works.
   - 🔴 **>12GB** (e.g. 20B+ fp8 video) → effectively **won't fit / impractical**. Don't bother.
2. **Bundled text encoders + VAE count against VRAM too.** A 7B diffusion model isn't 7GB —
   add the text encoder (Qwen 7B fp8 ≈ 7GB) + VAE + ControlNets + LoRAs. **Total footprint**
   is what matters, not the single checkpoint number.
3. **GPU scheduling (AGENTS.md):** Ollama and ComfyUI must **never** run GPU work at the same
   time — they OOM each other. Video/LLM work are mutually exclusive on this box.

---

## 2. Which RunComfy workflows RUN on this system

Summary of what the library actually verified. Green = works, yellow = needs modification,
red = skip.

### 🟢 Run as-is (verified or trivial)

| Workflow | Why it works | Verified? |
|---|---|---|
| **Anima Base v1** (1438) | 2B anime model + 0.6B text encoder + small VAE ≈ **~5GB total**. | ✅ Smoke-tested, generated 512×512 on GPU |
| **Krea 2 Turbo** (T2I/I2I/style) | Small turbo model, low steps | ✅ Already your primary panel engine |
| **APISR** (1082) | Tiny anime upscaler (6MB model) | ✅ Installed + model |
| **See-through** (1389) | SDXL-based; use NF4 quant + lower res | ✅ Installed (7 nodes) |
| **PMRF** (1234) | Low-VRAM by design | ❌ Blocked by NATTEN (see §5) |
| **VNCCS** (1398, **Anima engine**) | Character consistency on Anima Base | ✅ Installed; use Anima path not Qwen path |

### 🟡 Run with modification (the "needs work" tier)

| Workflow | What blocks it | The modification |
|---|---|---|
| **FLUX.2 Klein 4B** (1337) | 9B variant too big | Use the **4B** model, not 9B |
| **Qwen-Image 2512** (1330) | bf16 model ~15GB | Use **Q5 GGUF** + `--lowvram` |
| **Wan 2.2 Animate** (1300/1307) | 14B video + SAM2 + ControlNet | Needs 14B **Q4/Q5 GGUF**, drop to 480p, few frames |
| **LTX 2.x** video | 19–22B | Use small `ltxv-2b-0.9.8` distilled OR heavy offload |
| **TTS suites** (F5/IndexTTS/ChatterBox) | none GPU-heavy | Install node; models auto-download |

### 🔴 Skip (cloud-scale, won't fit)

**MiniMax H3**, **LTX 2.3 22B Director**, **SkyReels V3**, **SCAIL-2**, **SeedVR2**,
**Qwen-Image-Edit-2511** full path, and any 20B+ fp8 video stack. These are designed for
A10G/H100-class cloud GPUs. Rebuilding them for 8GB is not worth it when lighter
alternatives exist.

---

## 3. The "modification playbook" — turning a cloud workflow into an 8GB workflow

When you encounter a workflow that won't fit, apply these in order. **Stop as soon as it fits.**

1. **Quantize the diffusion model → GGUF.**
   - Swap `UNETLoader`/`CheckpointLoaderSimple` for the **GGUF** version (via `ComfyUI-GGUF`).
   - Start at **Q4_K_M**, go to Q5/Q3 only if needed. Q4 is the sweet spot for 8GB.
   - Example: Wan 14B `fp8` (~14GB) → `wan2.1-i2v-14b-480p-Q4_K_M.gguf` (already on disk, ~9GB) → offloads.

2. **Shrink the text encoder.**
   - Qwen 7B fp8 (~7GB) → **Qwen 0.6B** or a **4B GGUF**. Anima Base proves 0.6B is enough for clean anime.
   - Clip models: prefer `t5xxl_fp8` over `fp16`.

3. **Lower resolution & frame count.**
   - Images: 512×512 baseline, upscale *after* with APISR (don't generate big).
   - Video: 480p, fewer frames, shorter clips. 24fps×2–3s ≈ 50–72 frames is the practical ceiling.

4. **Reduce steps / use a turbo/Lightning LoRA.**
   - Krea 2 Turbo = 8 steps. DMD2/Lightning LoRAs cut SDXL to 4 steps.
   - Fewer steps = less VRAM per pass and faster iteration.

5. **Cut non-essential nodes.** Drop the SeedVR2/SUPIR upscaler stage, face-restore detailer,
   or extra ControlNets from the graph. Add them back *only if* there's VRAM headroom.

6. **Raise `--novram`** (CPU offload) for consecutive generations, or restart ComfyUI between
   heavy jobs (AGENTS.md: fragmented VRAM persists across restarts on some setups).

> **Rule of thumb:** a workflow "fits" if `sum(model footprints) + activation ≈ < 8GB`.
> If the text encoder alone is 7GB, the diffusion model must be ≤4GB → that means GGUF Q4.

---

## 4. Important nodes you'll hit across the library (and what they need)

These are the recurring custom nodes / patterns in the downloaded workflows. Knowing them
tells you what a workflow *really* requires before you import it.

### Model loaders (check the filename — that's the VRAM signal)
- `UNETLoader` — load a diffusion/DiT UNet. Filename = the big model.
- `CLIPLoader` (`type: qwen_image` / `t5xxl` / etc.) — text encoder. **Often the silent VRAM killer.**
- `VAELoader` — VAE. Qwen VAE is small (~243MB); fine.
- `CheckpointLoaderSimple` — combined checkpoint (SD/SDXL). Prefer splitting into UNET+CLIP+VAE for control.
- **GGUF loaders** (`ComfyUI-GGUF`) — load quantized `*.gguf`. **Your best friend on 8GB.**

### Control / conditioning (ControlNet aux)
- `DWPreprocessor`, `OpenPose`, `ViTPose` (`comfyui_controlnet_aux`) — pose/edge/depth hints.
  - These add CPU/GPU overhead but are usually small. Useful for **pose-driven character motion** (Wan Animate).
- `ControlNetLoader` + `ControlNetApplyAdvanced` — actual control models (e.g. `IllustriousXL_openpose` for anime).

### Character consistency (your #1 pipeline need)
- **VNCCS suite** (`ComfyUI_VNCCS`) — 43 nodes: `CharacterCreator`, `CharacterSheetCropper`,
  `SpriteGenerator`, `EmotionGenerator`, `VNCCSChromaKey`, `VNCCS_Pipe`. Best-in-class consistent
  characters. **Two engines:** Anima Base (light, 8GB-friendly) vs Qwen-Image-Edit (heavy, skip).
- `CharacterCreator` selects engine + downloads models via the **VNCCS Control Center** node.
- **See-through** (`SeeThrough_GenerateLayers` / `_GenerateDepth` / `_SavePSD`) — anime art →
  layered PSD for compositing/parallax. Use **NF4** model variants for VRAM.

### Image editing / inpainting
- `Qwen-Image-Edit` nodes — instruction-based editing. Heavy (20B family); use GGUF or skip.
- `FLUX.2 Klein` unified edit — use 4B not 9B.
- Krea 2 edit nodes (`comfyui-krea2edit`) — fast local edits, already installed.

### Video
- `ComfyUI-WanVideoWrapper` nodes (`WanVideoModelLoader`, `WanVideoSampler`, `WanVideoVAELoader`,
  `WanVideoBlockSwap`) — Wan video. **Block-swap + GGUF + 480p** = the only way it fits 8GB.
- `ComfyUI-LTXVideo` / `LTXDirector` — LTX video. 22B won't fit; use `ltxv-2b-0.9.8` distilled.
- `ComfyUI-VideoHelperSuite` (`VHS_VideoCombine`, `VHS_LoadVideo`) — load/assemble video. Essential glue.

### Upscaling / restoration
- **APISR** (`APISR_Zho`, `APISR_Lterative_Zho`) — anime upscaler. **Use iterative mode on 8GB.**
- **PMRF** — low-VRAM face restore, but **needs NATTEN** (see §5) → not viable on this torch.
- `UpscaleModelLoader` + `ImageUpscaleWithModel` with `4x-AnimeSharp` / `4x-UltraSharp` — classic anime upscale.

### TTS / audio (for the narration track)
- `ComfyUI-F5-TTS`, `IndexTTS2`, `ChatterBox`, `MOSS TTS`, `Fish S2` — all TTS, CPU/light-GPU, all fit.

### Utility / organization (appear everywhere)
- `rgthree-comfy` — Seed, Context, Reroute, Lora Loader Stack. UI glue, not model-heavy.
- `ComfyUI-KJNodes`, `ComfyUI-Easy-Use`, `comfy_mtb`, `ComfyUI-Custom-Scripts` — QoL + node helpers.
- `ComfyUI-Impact-Pack`, `ComfyUI-LayerStyle` — detailers / PS-style layers (adds install burden).

---

## 5. Known blockers on THIS machine (don't fight these)

| Blocker | Cause | Workaround |
|---|---|---|
| **NATTEN / PMRF** | PMRF imports `natten` (neighborhood attention); no prebuilt wheel for **torch 2.13.0+cu130**; building needs CUDA toolkit | **Don't use PMRF.** Use APISR or `4x-AnimeSharp`. PMRF is disabled as `ComfyUI-PMRF.disabled` |
| **20B+ video (MiniMax H3, LTX 22B, SkyReels, SCAIL-2, SeedVR2)** | Model set > VRAM + system RAM budget | Skip; use Wan/LTX small-quant or stick to image-first pipeline |
| **Qwen-Image-Edit-2511 full pipeline** | 20B family + 7B text encoder | Only as GGUF Q4 + 4B encoder, or use Anima Base instead |
| **`llama-cpp-python` / `transparent-background`** (VNCCS extras) | Heavy, lazy-loaded | Only needed for Qwen cloner / matting — leave uninstalled unless used |
| **SD 1.5 checkpoints** | VNCCS requires SDXL/Illustrious architecture | Use Illustrious-based or Anima for VNCCS |

---

## 6. How to BUILD workflows that make sense on this system

An agent creating a NEW workflow for this box should follow this template:

1. **Pick a light engine per task** (your installed, proven set):
   - **Anime T2I / panels:** Anima Base v1 (verified) or Krea 2 Turbo.
   - **Character consistency:** VNCCS on the **Anima engine**.
   - **Upscale:** APISR (iterative) or `4x-AnimeSharp` (not PMRF).
   - **Layer/PSD compositing:** See-through (NF4).
   - **TTS narration:** F5 / IndexTTS / ChatterBox.
2. **Keep total VRAM footprint < 8GB.** Verify each model's size; prefer GGUF/NF4/small variants.
3. **Never chain two heavy stages in one queue** (e.g. big diffusion + big upscaler + big VAE all at once).
   Stage them: generate → save → upscale in a second pass → save.
4. **Verify by running, not by guessing.** Use the `/prompt` API to smoke-test (like the Anima
   smoke test) and check it actually completes. Don't claim a workflow "works" until it produced output.
5. **Prefer the shipped ComfyUI templates / blueprints** over RunComfy cloud stubs. Several RunComfy
   JSONs (`1438`, `1450`) are **cloud launchers** (3–8 nodes, UUID subgraph types), **not** full local
   graphs. The official Comfy-Org template is the real graph.
6. **Document assumptions.** When you adapt a workflow, record: models used + sizes, resolution,
   steps, and whether `--lowvram`/GGUF is needed — so the next agent doesn't re-derive it.

### A sane end-to-end anime-recap pipeline (all verified pieces)
```
script/panels → [Anima Base 1 T2I] → raw panels (512×512)
              → [VNCCS Anima] → consistent character sheets
              → [APISR iterative] → upscale panels to 1024–2048
              → [See-through NF4] → layered PSD for compositing
narration     → [F5/IndexTTS/ChatterBox] → audio track
assembly      → ffmpeg (olympus engine) → final MP4
```
Keep each stage a separate queue job so VRAM frees between stages.

---

## 7. Checklist for any workflow before you import it

- [ ] List every **custom node** it needs → are they installed? (`ComfyUI-Manager` → Install Missing)
- [ ] List every **model filename** → are they on disk? What size? Does the *total* fit 8GB?
- [ ] Is the **text encoder** reasonable? (A 7B encoder + 7B UNet won't fit — one must shrink.)
- [ ] Is it a **cloud stub** (few nodes, UUID `type` fields) or a real graph?
- [ ] Is **`--lowvram`** on, and do I need `--novram` / block-swap / GGUF?
- [ ] After running, did it **actually produce output** (not just "no error at load")?
- [ ] Update this guide + `README.md` matrix with the verified result.
