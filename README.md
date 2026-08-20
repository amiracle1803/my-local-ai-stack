# Olympus — Local AI Stack

A private, **100% free** local AI hub on your Windows PC (also runs on Linux). No subscriptions, no cloud, no per-token bills. The stack runs on Ollama and serves a multi-agent operating system through a unified web dashboard, plus a production-grade anime recap-video pipeline.

Originally built for Windows; also runs on Linux (Fedora, since 2026-07-10). The `.sh` launchers mirror the `.bat` launchers 1:1; both are kept up to date.

---

## One Command to Start

**On Windows:** double-click `start.bat`  
**On Linux:** run `./start.sh`

Either way, it brings up:

| Service | Port | Description |
|---|---|---|
| **Ollama** | 11434 | Local LLM runner (must be installed separately) |
| **Olympus** | 4600 | Agent hub — dashboard, API, task routing, scheduler |
| **OpenCode MCP** | 4720 | Intelligence layer — web fetch, search, code tools |
| **Obsidian** | 27123 | Note vault with Local REST API plugin |
| **Voice Studio** | 5050 | TTS engine (Kokoro / F5-TTS) |
| **ComfyUI** | 8188 | Image/video generation |
| **Langfuse** | 3030 | Optional LLM call tracing |

Optional (check status only, start manually): Voice Studio, ComfyUI, LM Studio, AnythingLLM, n8n, MCP Gateway, Langfuse.

Visit `http://127.0.0.1:4600` after startup.

---

## Install (Once)

### Windows
1. **Ollama** — https://ollama.com/download → launch it once
2. **Python 3.11+** — https://www.python.org/downloads/ → tick *"Add python.exe to PATH"*
3. **Run `setup.bat`** — builds `.venv`, installs packages, pulls models
4. **Edit `config.json`** — set `vault_path` to your Obsidian vault

### Linux (Fedora/Nobara)
1. **Ollama** — https://ollama.com/download (native Linux install) → launch once (`ollama serve`)
2. **Python 3.11+** — `sudo dnf install python3` or use `uv`
3. **Run `./setup.sh`** — builds `.venv`, installs packages, pulls models
3. **Edit `config.json`** — set `vault_path` to your Obsidian vault
4. Run `./start.sh`

On Linux, Ollama runs as a systemd user unit; n8n/Langfuse run under podman. See `docs/GUIDE.md` §11.

---

## Repo Layout

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
|   |   +-- panel_img2img_plate_krea.json     # krea2 img2img (LTX VAE)
|   |   +-- ltx2b_i2v.json, ltx23_i2v_8gb.json, wan_ti2v.json
|   |   +-- character_sheet.json, mouth_sheet.json, image_krea2.json
|   +-- manifest.json            # Patchable keys + status per workflow
|   +-- NODES.md                 # Workflow node documentation
|   +-- prompts/                 # LLM prompts per stage
|   +-- tests/                   # Unit tests (192 passing)
|   +-- tools/                   # Smoke tests, model_smoke, ltx_smoke, validation
|   +-- run.py                   # CLI entry: new-project, run, report, all
+-- olympus/engines/pipeline/projects/  # Project data (auto-created)
+-- start.sh / setup.sh          # Linux equivalents
```

---

## Anime Recap-Video Pipeline (olympus/engines/pipeline)

A production-grade 9-stage pipeline that turns a script into a finished anime recap video.

### Stage Order

```
stage0 → stage1 → stage1_world → stage1r → stage3 → stage2 → stage3b → stage4 → stage3c → stage_vlm_review → stage5
```

| Stage | Name | Input | Output | Key Features |
|---|---|---|---|---|
| **stage0** | Intake | Brief (word_target + style_exemplars) | `input/script.txt` + blueprint | 3-pass LLM: blueprint → per-scene prose → integration |
| **stage1** (M2a) | Character Scan | Script | `worldbible/world_bible.json` (characters only) | Scan → profiles (40-60 word sd_prompt, voice_id, contradictions) |
| **stage1_world** (M2b) | World Enrichment | Partial bible + script | Full `world_bible.json` | Locations (angles + connections), era, magic, economy, relationships, contradictions, voice registry |
| **stage1r** | References | World bible | `references/` (char sheets, location angles, style refs, voice auditions) | 30 frames/char (turnarounds), 4 angles/location, 10 style refs, 9 visemes/char |
| **stage3** | Storyboard | World bible + refs + script | `storyboard/storyboard.json` (scenes, shots, blocks) | Scene segmentation, shot planning, SD prompts using refs |
| **stage2** | Screenplay | Storyboard + refs | `screenplay/screenplay.json` (narration + dialogue + SFX) | Technique rotation, style cards, banned patterns, 3 weakest rewritten |
| **stage3b** | Panels | Screenplay + refs | `panels/` (PNGs + sidecars) | krea2 img2img from plates (LTX VAE, 768×448), denoise=0.2, V-JEPA2 gate (0.88), M-AP-7 IPAdapter identity/style |
| **stage4** | Audio | Screenplay + refs | `audio/` (WAV + alignments) | Kokoro TTS, whisperX alignment, viseme timelines |
| **stage3c** | Animation | Panels + audio | `clips/` (MP4) | LTX 2B I2V (ltx2b_i2v.json), motion tiers, cache, Real-ESRGAN 2x |
| **stage_vlm_review** | VLM Review | Clips + audio | `reviews/vlm_review.json` | qwen2.5vl:7b, 10-dim physics/logic gate, audio+visual review |
| **stage5** | Assembly | All | `video/final.mp4` + chapters + SRT + timeline | ffmpeg concat, A/V sync, chapters, repeat detection |

### Key Technical Fixes (M-AP-1/3/6/7)

| Issue | Fix |
|---|---|
| **Latent mismatch** (krea2 Qwen VAE → LTX VAE) | Plates + panels at **768×448** with **LTX VAE** natively — no double-encode |
| **Background drift** | `panel_denoise=0.2` (tighter plate lock), V-JEPA2 gate (cosine ≥ 0.88) |
| **Guide strength too high** | `LTXVAddGuide strength=0.55` (was 0.9) |
| **img_compression artifacts** | `img_compression=0` (lossless) in LTXVPreprocess |
| **Character consistency** | M-AP-7: `panel_krea2_ref.json` with dual IPAdapters (identity + style) |
| **GPU contention** | `GpuBatch` context manager: file lease + `comfy.unload_ollama()` + `comfy.free()` |

### Running the Pipeline

```bash
cd olympus/engines/pipeline

# Create a project from a brief
python run.py new-project my-story --brief brief.md

# Run all stages (or individual stages)
python run.py all my-story
# or step by step:
python run.py run my-story stage0
python run.py run my-story stage1
python run.py run my-story stage1_world
python run.py run my-story stage1r
python run.py run my-story stage3
python run.py run my-story stage2
python run.py run my-story stage3b
python run.py run my-story stage4
python run.py run my-story stage3c
python run.py run my-story stage_vlm_review
python run.py run my-story stage5

# Report progress
python run.py report my-story
```

---

## Agents (Olympus Kernel)

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

Agents defined in `olympus/agents/` as `.md` craft files. They communicate via the kernel's task queue and MCP mesh.

---

## Configuration

### `config.json` (Shared)
```json
{
  "vault_path": "/path/to/obsidian/vault",
  "ollama_url": "http://127.0.0.1:11434",
  "comfyui_url": "http://127.0.0.1:8188",
  "voice_studio_url": "http://127.0.0.1:5050"
}
```

### `stack.toml` (Unified Config Source)
Single source of truth for all services. Loaded via `stack.config.cfg` (Pydantic v2).
The `[ollama]` section sets `num_ctx` (default 16384) for the whole stack; the
pipeline bridges it into `PipelineConfig.num_ctx` and clamps `num_predict` per
call so prompts never overflow the context window. Model roles live under
`[ollama.models]`:

```toml
[ollama]
num_ctx = 16384

[ollama.models]
default = "qwen3:8b"   # general fallback (was llama3.1:8b — not pulled on this box)
script  = "qwen3:8b"   # stage0/stage1 script+world parsing
vision  = "qwen3:8b"   # panel vision analysis (was qwen2.5vl:7b — miscounted dense panels)
review  = "qwen2.5vl:7b" # stage_vlm_review physics/logic gate (non-reasoning, fast structured output)
```

---

## MCP Mesh

Olympus, OpenCode, LifeOS, and LLM Wiki speak the **Model Context Protocol** for cross-tool delegation:
- Olympus MCP (port 4720) — web fetch, search, code tools
- OpenCode MCP — code tools, file ops
- LLM Wiki MCP — knowledge base queries

---

## Design Philosophy

- **Ollama-native** — works with any model; upgrade by editing `stack.toml`
- **One Python venv** — everything shares `.venv`, no venv-per-project overhead
- **MCP mesh** — Olympus, OpenCode, LifeOS, and LLM Wiki speak MCP for cross-tool delegation
- **Lean by default** — Docker/n8n, ComfyUI, Langfuse are optional add-ons
- **Your data stays local** — only outbound traffic is web pages/RSS you configure

---

## GPU Scheduling (AGENTS.md Rule)

**Ollama and ComfyUI must NEVER run GPU work simultaneously** on the RTX 4070 8GB VRAM.

- **LLM work**: ComfyUI must be idle (unload models via `/free`)
- **Image/video work**: Unload all Ollama models (`comfy.unload_ollama()`) before queuing ComfyUI
- **Kernel agents** use `qwen3:8b` by default to coexist with ComfyUI; heavy pipeline stages also use `qwen3:8b` when ComfyUI is idle
- **GpuBatch** context manager enforces: file lease → `unload_ollama()` → GPU work → `comfy.free()` → release

---

## Image Models (GGUF, 512×512 / 768×448)

| Model | Time | Steps | VRAM | Status |
|---|---|---|---|---|
| `krea2_turbo-Q4_K_S` | 32s | 8 | ~5GB | Primary (panels) |
| `krea2_turbo-Q4_K_M` | 28s | 8 | ~5GB | Primary fallback |
| `flux-2-klein-4b-Q4_K_M` | ~41s | 20 | ~3GB | Design fallback (character refs + panels; swapped from flux1-schnell 2026-08) |
| `ltx-2.3-22b-distilled-1.1-Q4_K_M` | 55s | 8 | ~5.8GB | Animation primary (LTX 2.3 22B) |
| `ltxv-2b-0.9.8-distilled-fp8-i2v` | 29s | 8 | ~5GB | Animation fallback (LTX 2B) |

Banned checkpoints enforced at runtime: `z-anime-distill-4step-fp8`, `wai-illustrious-v110`, `NoobAI-XL-v1.1`, `animagine-xl-4.0`, `FLUX.1-Krea-dev`.

---

## Testing

```bash
cd olympus/engines/pipeline
python -m pytest tests/ -v
# 195 passing (4 pre-existing failures: stage3c cache 'planned_tier', stage5 shot-duration default)
```

Key test modules:
- `test_gpu_lock.py` — GpuLock + GpuBatch
- `test_video_router.py` — LTX template selection + M-AP-3 gate
- `test_stage3b_new_features.py` — WorldBible angles, plate keys, patch keys
- `test_stage3c_cache.py` — LTX render cache
- `test_stage5_assembly.py` — ffmpeg segment assembly
- `test_video_metrics.py` — dHash, align-ratio, location diversity
- `test_stage3b_new_features.py` — M-AP-7 patch keys, workflow validation

Smoke test:
```bash
python tests/smoke_test_stage3b.py
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| OOM on 8GB | Lower resolution, reduce batch, `comfy.free()` between panels |
| Ollama + ComfyUI OOM | Use `GpuBatch` / `comfy.unload_ollama()` / `comfy.free()` |
| krea2 weights missing | Run `python tools/model_smoke.py --template image_krea2.json` |
| LTX smoke gate fails | `python tools/ltx_smoke.py --template ltx2b_i2v.json` |
| VLM review hangs | Check Ollama has `qwen2.5vl:7b` pulled |
| Stage gate blocked | `python run.py report <slug>` → check missing metrics |

---

## Documentation

- `docs/GUIDE.md` — Full user guide (services, GPU rules, pipeline, Linux)
- `docs/TROUBLESHOOTING.md` — Common issues + fixes
- `olympus/engines/pipeline/workflows/NODES.md` — Workflow node docs
- `olympus/engines/pipeline/docs/` — Pipeline design docs

---

## License

Personal use only. Not for redistribution. All models subject to their respective licenses (GGUF quantizations, Ollama terms).