# [OLD] Olympus — Local AI Stack  (superseded 2026-08-21)

> This is the previous full README, preserved verbatim from the 2026-08-21
> rewrite of `README.md` at repo root. **Nothing in this file is active** —
> the current README is the single source of truth. Kept only so engineering
> notes, plans, and tuning history are not lost.

---

A private, **100% free** local AI hub on your Windows PC (also runs on Linux).
No subscriptions, no cloud, no per-token bills. The stack runs on Ollama and
serves a multi-agent operating system through a unified web dashboard, plus a
production-grade anime recap-video pipeline.

Originally built for Windows; also runs on Linux (Fedora, since 2026-07-10).
The `.sh` launchers mirror the `.bat` launchers 1:1; both are kept up to date.

---

## One Command to Start

**On Windows:** double-click `start.bat`
**On Linux:** run `./start.sh`

| Service | Port | Description |
|---|---|---|
| **Ollama** | 11434 | Local LLM runner (must be installed separately) |
| **Olympus** | 4600 | Agent hub — dashboard, API, task routing, scheduler |
| **OpenCode MCP** | 4720 | Intelligence layer — web fetch, search, code tools |
| **Obsidian** | 27123 | Note vault with Local REST API plugin |
| **Voice Studio** | 5050 | TTS engine (Kokoro / F5-TTS) |
| **ComfyUI** | 8188 | Image/video generation |
| **Langfuse** | 3030 | Optional LLM call tracing |

Visit `http://127.0.0.1:4600` after startup.

---

## Repo Layout (old, pre-rewrite)

```
my-local-ai-stack/
+-- start.bat / start.sh           # Daily boot (one button)
+-- setup.bat / setup.sh           # One-time install
+-- olympus.toml                   # Hub config (models, paths, API keys)
+-- config.json                    # Shared settings
+-- olympus/
|   +-- kernel/                    # FastAPI app, agents, scheduler, brain
|   +-- agents/                    # Individual agent crafts (.md files)
|   +-- web/                       # Dashboard frontend
+-- opencode/
|   +-- mcp_server.py              # MCP server (web fetch, search, code tools)
|   +-- crafts/                    # TDD, debugging, verification guides
+-- shared/lib/                    # config, llm, notes, passes, state, webfetch
+-- docs/
|   +-- GUIDE.md                   # Full user guide
|   +-- TROUBLESHOOTING.md
+-- foundation/                    # Optional Docker layer (n8n etc.; podman on Linux)
+-- voice-studio/                  # TTS engine (Kokoro + F5-TTS) — port 5050
+-- llm-wiki-workflow/             # LLM-managed knowledge base
+-- ComfyUI/                       # Image/video gen, port 8188
|                                   extra_model_paths.yaml points bulk model storage
+-- olympus/engines/pipeline/      # Anime recap-video pipeline (run.py)
|   +-- pipeline/                  # Core pipeline modules
|   |   +-- stage0_intake.py       # Script intake from brief
|   |   +-- stage1_worldbible.py   # M2a: character scan + profiles
|   |   +-- stage1_world.py        # M2b: world enrichment + location graph
|   |   +-- stage1r_references.py  # Character/location/style refs + voice auditions
|   |   +-- stage3_storyboard.py   # Storyboard + shot planning (uses refs)
|   |   +-- stage2_screenplay.py   # Narration + dialogue (uses refs)
|   |   +-- stage3b_images.py      # Panels: krea2 img2img + LTX VAE + IPAdapters
|   |   +-- stage3c_animation.py   # LTX I2V animation (krea2 base)
|   |   +-- stage4_audio.py        # TTS + alignment
|   |   +-- stage5_assembly.py     # Final MP4 + chapters + SRT
|   |   +-- stage_vlm_review.py    # VLM review (audio + visual)
|   |   +-- video_router.py        # LTX template selection + smoke gate
|   |   +-- gpu_lock.py            # Cross-process GPU lease + GpuBatch
|   |   +-- video_metrics.py       # dHash, align-ratio, location diversity
|   |   +-- vjepa.py               # V-JEPA2 perceptual similarity gate
|   |   +-- lipsync.py             # Lip-sync bridge (mouth_sheet.json)
|   |   +-- realisrgan_upscale.py  # Real-ESRGAN anime 2x
|   |   +-- align.py               # Frame alignment
|   |   +-- agi_brain_v3.py        # AGI script scorer
|   |   +-- agi_scorer.py          # Script quality scoring
|   |   +-- model_lab.py           # Model smoke tests
|   |   +-- config.py              # PipelineConfig bridge to stack.toml
|   |   +-- blueprint.py           # Project identity + stage gates
|   |   +-- scores.py              # SQLite scorecards + stage gates
|   |   +-- comfy_client.py        # ComfyUI client + ban enforcement
|   |   +-- image_router.py        # Workflow routing + M-AP-3/M-AP-7 gates
|   |   +-- _util.py, chunking.py, llm.py, scores.py, blueprint.py
|   +-- workflows/                 # ComfyUI workflow JSONs
|   |   +-- panel_img2img_plate_krea.json     # krea2 img2img (LTX VAE, 768x448)
|   |   +-- panel_img2img_plate_anima.json    # Anima img2img (LTX VAE)
|   |   +-- panel_krea2_ref.json              # M-AP-7: IPAdapter identity/style
|   |   +-- ltx2b_i2v.json, ltx23_i2v_8gb.json, wan_ti2v.json
|   |   +-- character_sheet.json, mouth_sheet.json, image_krea2.json
|   +-- manifest.json            # Patchable keys + status per workflow
|   +-- NODES.md                 # Workflow node documentation
|   +-- prompts/                 # LLM prompts per stage
|   +-- tests/                   # Unit tests
|   +-- tools/                   # Smoke tests, model_smoke, ltx_smoke, validation
|   +-- run.py                   # CLI entry: new-project, run, report, all
+-- olympus/engines/pipeline/projects/  # Project data (auto-created)
```

---

## [OLD] Anime Recap-Video Pipeline — stage order & key fixes

```
stage0 → stage1 → stage1_world → stage1r → stage3 → stage2 → stage3b → stage4 → stage3c → stage_vlm_review → stage5
```

### Key Technical Fixes (M-AP-1/3/6/7) — full history

| Issue | Fix |
|---|---|
| **Latent mismatch** (krea2 Qwen VAE → LTX VAE) | Plates + panels at **768×448** with **LTX VAE** natively — no double-encode |
| **Background drift** | `panel_denoise=0.2` (tighter plate lock), V-JEPA2 gate (cosine ≥ 0.88) |
| **Guide strength too high** | `LTXVAddGuide strength=0.55` (was 0.9) |
| **img_compression artifacts** | `img_compression=0` (lossless) in LTXVPreprocess |
| **Character consistency** | M-AP-7: `panel_krea2_ref.json` with dual IPAdapters (identity + style) |
| **GPU contention** | `GpuBatch` context manager: file lease + `comfy.unload_ollama()` + `comfy.free()` |
| **End-of-clip blur** (director) | `last_frame_fix = true` on `LTXVSpatioTemporalTiledVAEDecode` in `ltx_director_23.json`. A separate img2img END-keyframe was trialed 2026-08-21 then reverted (doubled GPU cost per shot + broke the 1-render/shot test contract). |
| **Short clips** (director) | `_DIRECTOR_FRAMES` 33 → **97** (4.0s @24fps, LTX `8n+1` latent rule); smoke-revalidated 2026-08-21 (168s wall, motion gate passes). |

### [OLD] stage3c engine notes / superseded trials

- **LTX 2B I2V (pre-2026-08-20):** old stage3c engine (`ltx2b_i2v.json`), 33-frame
  (~1.4s @24fps) clips, face/character distortion mitigated via Real-ESRGAN
  enhance + `ltx_strength` tuning, no end-of-clip stabilization.
- **First director trial (2026-08-20):** LTXDirector V2V adopted as primary
  with `_DIRECTOR_FRAMES = 33` (1.375s), `last_frame_fix = false`. Smoke gate
  passed (41-frame clip, ~44s wall). See
  `docs/planning/ltx-director-v2v-2026-08-20.md`.
- **Reverted img2img END-keyframe (2026-08-21):** tried generating a separate
  Flux-2-Klein img2img END frame injected as a second timeline image segment
  with `isEndFrame=true`. REVERTED — doubled GPU renders/shot, broke the
  stage3c test contract (exactly 1 `generate` per shot), and `last_frame_fix`
  solves the same problem for free. `_render_end_frame` is STILL USED by the
  Wan 2.2 two-keyframe engine (`wan22_2f` / `wan_ti2v_2f.json`).
- **Labeling trial (2026-08-21):** burning captions onto panel PNGs and
  renaming files to readable names were both considered and rejected — the
  companion-index approach was chosen as the standard.

---

## [OLD] Agents (Olympus Kernel)

| Agent | Domain | Role |
|---|---|---|
| **Jarvis** | chat | Conversational front-end |
| **Conductor** | system | Morning briefs, evening wraps, life triage |
| **Forge** | pipeline | Anime pipeline plans, prompts, shot lists |
| **Archivist** | research | Knowledge base scanning, research |
| **Scribe** | content | Writing and editing |
| **Plutus** | commerce | eBay, finance |
| **Calliope** | creative | YouTube scripts, Aether Echoes |
| **Athena** | strategy | Planner, verifier, task oversight |
| **Sovereign** | pipeline | Software development with TDD discipline |

---

## [OLD] Configuration notes

`stack.toml` (unified config source) is loaded via `stack.config.cfg`
(Pydantic v2). `[ollama] num_ctx` default 16384; pipeline bridges it into
`PipelineConfig.num_ctx` and clamps `num_predict` per call. Model roles:

```toml
[ollama.models]
default = "qwen3:8b"   # general fallback (was llama3.1:8b)
script  = "qwen3:8b"
vision  = "qwen3:8b"   # was qwen2.5vl:7b (miscounted dense panels)
review  = "qwen2.5vl:7b"
```

`[animation] engine = "ltx_director"` (PRIMARY; fallbacks: ltx2b | svd_xt |
wan22 | wan22_2f | ltx23), `ltx_director_workflow = "ltx_director_23.json"`.

---

## [OLD] MCP Mesh

Olympus, OpenCode, LifeOS, and LLM Wiki speak the **Model Context Protocol**
for cross-tool delegation:
- Olympus MCP (port 4720) — web fetch, search, code tools
- OpenCode MCP — code tools, file ops
- LLM Wiki MCP — knowledge base queries

---

## [OLD] Design Philosophy

- **Ollama-native** — works with any model; upgrade by editing `stack.toml`
- **One Python venv** — everything shares `.venv`, no venv-per-project overhead
- **MCP mesh** — Olympus, OpenCode, LifeOS, and LLM Wiki speak MCP
- **Lean by default** — Docker/n8n, ComfyUI, Langfuse are optional add-ons
- **Your data stays local** — only outbound traffic is web pages/RSS you configure

---

## [OLD] GPU Scheduling (AGENTS.md Rule)

**Ollama and ComfyUI must NEVER run GPU work simultaneously** on the RTX 4070
8GB VRAM.

- **LLM work**: ComfyUI must be idle (unload models via `/free`)
- **Image/video work**: Unload all Ollama models (`comfy.unload_ollama()`) before queuing ComfyUI
- **Kernel agents** use `qwen3:8b` by default; heavy pipeline stages also use `qwen3:8b` when ComfyUI is idle
- **GpuBatch** context manager enforces: file lease → `unload_ollama()` → GPU work → `comfy.free()` → release

---

## [OLD] Image Models (GGUF)

| Model | Time | Steps | VRAM | Status |
|---|---|---|---|---|
| `krea2_turbo-Q4_K_S` | 32s | 8 | ~5GB | Primary (panels) |
| `krea2_turbo-Q4_K_M` | 28s | 8 | ~5GB | Primary fallback |
| `flux-2-klein-4b-Q4_K_M` | ~41s | 20 | ~3GB | Design fallback (swapped from flux1-schnell 2026-08) |
| `ltx-2.3-22b-distilled-1.1-Q4_K_M` | 55s (8 steps) / ~168s (97f/4s director) | 8 | ~5.8GB | Animation primary — LTX Director V2V |
| `ltxv-2b-0.9.8-distilled-fp8-i2v` | 29s | 8 | ~5GB | Animation fallback (LTX 2B) |

Banned checkpoints enforced at runtime: `z-anime-distill-4step-fp8`,
`wai-illustrious-v110`, `NoobAI-XL-v1.1`, `animagine-xl-4.0`, `FLUX.1-Krea-dev`.

---

## [OLD] Documentation index

- `docs/GUIDE.md` — Full user guide (services, GPU rules, pipeline, Linux)
- `docs/TROUBLESHOOTING.md` — Common issues + fixes
- `olympus/engines/pipeline/workflows/NODES.md` — Workflow node docs
- `olympus/engines/pipeline/docs/` — Pipeline design docs

---

## [OLD] License

Personal use only. Not for redistribution. All models subject to their
respective licenses (GGUF quantizations, Ollama terms).
