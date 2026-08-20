# Pipeline Build Status — Working Pieces (2026-08-20)

> This note records the state of the anime-recap pipeline so it can be **wired into the
> `olympus/engines/pipeline/` panel-generation flow later**. Do not re-derive this — read this
> first, then continue integration.

## Working end-to-end pieces (all verified on this machine)

```
script/panels → [Anima Base 1 T2I] → raw panels (512×512)
              → [VNCCS Anima]     → consistent character sheets
              → [APISR iterative] → upscale panels to 1024–2048
              → [See-through NF4] → layered PSD for compositing
narration     → [F5 / IndexTTS / ChatterBox] → audio track
assembly      → ffmpeg (olympus engine)       → final MP4
```

| Stage | Tool | Status | Verification |
|---|---|---|---|
| Anime T2I / panels | **Anima Base v1** (ComfyUI template) | ✅ Working | Smoke-tested via API: generated 512×512 PNG on RTX 4070, no OOM |
| Consistent characters | **VNCCS** (Anima engine) | ✅ Installed | Node loads (43 nodes, 0 import failures); Anima models + turbo LoRA present |
| Anime upscale | **APISR** (iterative) | ✅ Installed | Node loads; `4x_APISR_GRL_GAN_generator.pth` in `models/apisr/` |
| Layer/PSD compositing | **See-through** (NF4) | ✅ Installed | Node loads (7 nodes); models auto-download on first use |
| TTS narration | F5 / IndexTTS / ChatterBox | ✅ Nodes available | Custom nodes load; models auto-download |

## Where things live

- **Workflow library + decision guide:** `workflows/runcomfy/`
  - `README.md` — master matrix (what runs / needs modification / skip)
  - `AGENT-GUIDE.md` — how to build/adapt workflows for 8GB VRAM (read before any workflow work)
  - `_analysis/` — per-workflow breakdown (nodes + models + status)
  - `_raw/` — the downloaded workflow JSONs
- **Custom nodes installed:** `ComfyUI/custom_nodes/` → `ComfyUI-APISR`, `ComfyUI-See-through`,
  `ComfyUI_VNCCS` (PMRF disabled as `ComfyUI-PMRF.disabled`)
- **Models added:** `ComfyUI/models/apisr/4x_APISR_GRL_GAN_generator.pth`,
  `ComfyUI/models/loras/Anima/anima-turbo-lora-v0.1.safetensors`

## Known limitations / blockers (do not fight these)

- **PMRF** is disabled — needs NATTEN, no wheel for torch 2.13.0+cu130. Use APISR / `4x-AnimeSharp`.
- **Heavy/cloud-only** (skip): MiniMax H3, LTX 2.3 22B, SkyReels V3, SCAIL-2, SeedVR2,
  Qwen-Image-Edit-2511 full path.
- **Video gen (Wan/LTX)** is possible only with GGUF Q4 + `--lowvram` + 480p + few frames, and
  must not run concurrently with Ollama (GPU scheduling rule in AGENTS.md).
- Several RunComfy JSONs (`1438`, `1450`) are **cloud stubs**, not full local graphs — use the
  shipped ComfyUI templates / official Comfy-Org graphs instead.

## Next step (when wiring into olympus/engines/pipeline/)

Integrate the verified stages into `olympus/engines/pipeline/` panel generation, reusing the
working ComfyUI graphs above. Keep each stage as a **separate queue job** so VRAM frees
between stages. See `AGENT-GUIDE.md` §6 for the build template and §7 for the pre-import
checklist.
