# Olympus — Local AI Stack

A private, local-first AI hub for Windows and Linux. Olympus runs local models through Ollama, coordinates specialized agents through one dashboard, and includes an end-to-end anime recap-video pipeline.

No subscriptions, no hosted inference, and no per-token fees. Your models, projects, vault, and generated media stay on your machine unless you explicitly configure external web tools.

> **Designed and tested around an RTX 4070 Laptop GPU with 8 GB VRAM and 32 GB RAM.** It can run on other hardware, but video generation is GPU- and VRAM-intensive.

## What Olympus Does

Olympus combines two local workflows under one project system:

| Workflow | Purpose | Main output |
|---|---|---|
| **Agent Hub** | Local chat, planning, research, writing, task routing, vault interaction, and developer workflows | Dashboard tasks, notes, plans, code artifacts |
| **Anime Video Pipeline** | Converts a brief or script into a storyboard, image panels, narrated audio, animated clips, QA results, and a final video | MP4, SRT, chapters, project asset index |

The dashboard runs at **http://127.0.0.1:4600** after startup.

## Requirements

| Component | Minimum | Recommended / tested |
|---|---|---|
| OS | Windows 10/11 or Fedora-family Linux | Windows 11, Fedora, or Nobara |
| Python | 3.11+ | Python 3.11 or 3.12 |
| GPU | NVIDIA GPU for ComfyUI generation | RTX 4070 Laptop, 8 GB VRAM |
| RAM | 16 GB | 32 GB |
| Free disk | 40 GB | 100 GB+ for model cache, projects, clips, and exports |
| Local LLM runtime | Ollama | Ollama with `qwen3:8b` and `qwen2.5vl:7b` |

On 8 GB VRAM, Olympus intentionally runs **one heavy GPU tenant at a time**: either Ollama inference or ComfyUI image/video generation.

## First-Time Setup

### Windows

1. Install Ollama, then launch it once.
2. Install Python 3.11+.
   - During installation, select **Add python.exe to PATH**.
3. Clone or extract this repository.
4. Run `setup.bat`.
5. Open `stack.toml` and set your project paths and preferred models.
6. Open `config.json` and set `vault_path` if you use Obsidian.
7. Double-click `start.bat`.
8. Visit `http://127.0.0.1:4600`.

### Linux: Fedora / Nobara

```bash
sudo dnf install python3 git
git clone <your-repository-url> olympus
cd olympus
chmod +x setup.sh start.sh
./setup.sh
```

Then:

1. Install Ollama using its native Linux installer and ensure `ollama serve` is running.
2. Set your vault and project paths in `config.json` / `stack.toml`.
3. Start Olympus:

```bash
./start.sh
```

On Linux, Ollama is normally managed as a systemd user service. Optional n8n and Langfuse services use Podman; see `docs/GUIDE.md`.

## Daily Start

### Windows

Double-click:

```
start.bat
```

### Linux

```bash
./start.sh
```

Olympus starts the core services it owns, checks optional services, and opens the local hub.

| Service | Port | Purpose |
|---|---|---|
| Ollama | 11434 | Local LLM runtime; install separately |
| Olympus | 4600 | Dashboard, API, agents, scheduler, task routing |
| OpenCode MCP | 4720 | Code, fetch, search, and tool integration |
| Obsidian Local REST API | 27123 | Optional vault integration |
| Voice Studio | 5050 | Optional Kokoro / F5-TTS service |
| ComfyUI | 8188 | Optional image and video generation |
| Langfuse | 3030 | Optional local LLM tracing |

Open `http://127.0.0.1:4600` when the startup check completes.

## First Successful Run

Before starting a full video project, verify the stack with a small test.

```bash
cd olympus/engines/pipeline

# Create a project from a source script (stage0 can also take a creative brief).
python run.py new-project first-demo --script my-script.txt

# See what Olympus expects before running.
python run.py report first-demo

# Run the project end-to-end.
python run.py all first-demo --brief brief.md   # --brief only needed for stage0 brief-mode
```

A completed project contains:

```
projects/first-demo/
├── input/
├── worldbible/
├── references/
├── storyboard/
├── screenplay/
├── panels/
├── audio/
├── clips/
├── reviews/
├── video/
│   ├── final.mp4
│   ├── chapters.txt
│   ├── subtitles.srt
│   └── timeline.json
├── labels.json
├── labels.txt
└── labels.html
```

Open `labels.html` in a browser to browse readable descriptions of panels and clips without changing stable engine filenames.

## Configuration

`stack.toml` is the **primary configuration source** for Olympus services, model roles, and pipeline behavior.

`config.json` contains shared service URLs and paths used by components that need a lightweight common configuration layer.

### Minimal configuration

```toml
[ollama]
num_ctx = 16384

[ollama.models]
default = "qwen3:8b"
script  = "qwen3:8b"
vision  = "qwen3:8b"
review  = "qwen2.5vl:7b"

[animation]
engine = "ltx_director"
ltx_director_workflow = "ltx_director_23.json"
```

```json
{
  "vault_path": "/path/to/obsidian/vault",
  "ollama_url": "http://127.0.0.1:11434",
  "comfyui_url": "http://127.0.0.1:8188",
  "voice_studio_url": "http://127.0.0.1:5050"
}
```

### Configuration precedence

Use this order when diagnosing unexpected behavior:

1. CLI arguments passed to `run.py`
2. Environment variables
3. `stack.toml`
4. `config.json`
5. Built-in defaults

Keep `stack.toml` as the place to change model roles, context limits, animation engines, and pipeline-wide behavior.

## Agent Hub

Olympus agents are local role-based workers defined as Markdown craft files in `olympus/agents/`. They communicate through the kernel task queue and MCP-compatible tools.

| Agent | Focus | Typical use |
|---|---|---|
| Jarvis | Chat | Main conversational interface and request routing |
| Conductor | System | Morning briefs, evening reviews, life triage |
| Forge | Pipeline | Recap plans, scene prompts, shot lists, production guidance |
| Archivist | Research | Vault scanning, research synthesis, knowledge retrieval |
| Scribe | Content | Writing, editing, summaries, and structured notes |
| Plutus | Commerce | eBay, finance, listing and planning workflows |
| Calliope | Creative | YouTube scripts, creative concepts, Aether Echoes |
| Athena | Strategy | Planning, verification, task oversight |
| Sovereign | Development | TDD-focused software engineering and debugging |

### Common agent flows

| User action | Primary agent | Outcome |
|---|---|---|
| "Turn this premise into a recap plan" | Forge | Brief, worldbuilding plan, shot direction, pipeline-ready structure |
| "Plan my day from my vault and tasks" | Conductor | Prioritized daily brief and triage |
| "Research this topic and save notes" | Archivist | Research output and vault-ready notes |
| "Fix this failed pipeline test" | Sovereign | Root-cause analysis, test-first patch plan |
| "Write a YouTube recap script" | Calliope + Scribe | Structured narration, hooks, pacing, title ideas |

## Anime Video Pipeline

The production pipeline turns a short brief or finished script into a narrated, reviewed recap video.

```
Brief / Script
      ↓
Intake and blueprint
      ↓
Character and world bible
      ↓
Reference assets
      ↓
Storyboard and screenplay
      ↓
Panels and narration
      ↓
Animated clips
      ↓
Visual-language review
      ↓
MP4, subtitles, chapters, labels
```

### Pipeline stages

| Stage | Purpose | Major output |
|---|---|---|
| stage0 | Converts a brief into a structured script and project blueprint | `input/script.txt`, blueprint |
| stage1 | Extracts characters, traits, voices, and contradictions | Character world bible |
| stage1_world | Builds locations, relationships, world rules, and voice registry | Full world bible |
| stage1r | Generates character, location, style, and voice reference assets | `references/` |
| stage3 | Segments scenes and plans shots | `storyboard/storyboard.json` |
| stage2 | Creates narration, dialogue, SFX, and style cards | `screenplay/screenplay.json` |
| stage3b | Creates still panels with identity and style controls | `panels/` |
| stage4 | Creates TTS audio, timing, and viseme data | `audio/` |
| stage3c | Animates panels into short video clips | `clips/` |
| stage_vlm_review | Runs visual and audio quality checks | `reviews/vlm_review.json` |
| stage5 | Joins clips, audio, subtitles, chapters, and metadata | `video/final.mp4` |

Run one stage at a time while developing:

```bash
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
```

Or run the complete chain:

```bash
python run.py all my-story
```

Check a project's state at any time:

```bash
python run.py report my-story
```

## Asset Labeling

Pipeline files use stable shot identifiers such as:

```
sh-001-01.png
sh-001-01_director_00001.mp4
```

Olympus does **not** rename these files because stable paths protect stage contracts, caching, tests, and downstream automation. Instead, it writes a human-readable companion index after panel and clip generation.

| File | Use |
|---|---|
| `labels.json` | Structured machine-readable scene, panel, and clip index |
| `labels.txt` | Searchable plain-text project overview |
| `labels.html` | Browser-based asset table for manual review |

Example:

```
SC-001 · The Village · Morning · Wide Shot · Kana arrives at the shrine.
SC-001 · Shrine Path · Morning · Medium Shot · Kana notices the missing bell.
SC-002 · The Village · Noon · Close-up · The elder warns Kana not to enter.
```

This lets you search for recurring locations, time-of-day mismatches, or composition repetition without touching pipeline filenames.

Rebuild the index manually when needed:

```bash
cd olympus/engines/pipeline
python -c "from pipeline.labeling import write_labels; write_labels('projects/<slug>')"
```

## GPU Scheduling

On an 8 GB GPU, Ollama and ComfyUI must not perform heavy work at the same time.

Olympus enforces this through `GpuBatch`:

```
Acquire file lease
      ↓
Unload Ollama models
      ↓
Run ComfyUI image/video work
      ↓
Free ComfyUI models and VRAM
      ↓
Release lease
```

### Rules

1. Run local LLM-heavy agent work while ComfyUI is idle.
2. Before ComfyUI work, unload Ollama models.
3. After ComfyUI work, free models before returning to agent activity.
4. Do not manually run multiple ComfyUI-heavy stages simultaneously.
5. Treat a stale GPU lease carefully; do not delete a lock that belongs to an active render.

Useful checks:

```bash
python run.py report my-story
ls -la /tmp/pipeline-gpu/
```

> A future dashboard status panel should show whether the GPU is free, leased by the pipeline, or occupied by an external process.

## Model Defaults

Olympus is Ollama-native for language models and ComfyUI-native for image/video workflows. Change models in `stack.toml`; do not hard-code a model name into stage code.

| Role | Default model | Purpose |
|---|---|---|
| General agent work | `qwen3:8b` | Chat, planning, fallback generation |
| Scripts and worldbuilding | `qwen3:8b` | Intake, character analysis, screenplay generation |
| Panel interpretation | `qwen3:8b` | Vision-related analysis and pipeline planning |
| Visual QA | `qwen2.5vl:7b` | Structured audio/visual review |
| Primary panel generator | `krea2_turbo-Q4_K_S` | 768×448 anime-style panels |
| Design fallback | `flux-2-klein-4b-Q4_K_M` | Character references and design alternatives |
| Primary animation | LTX Director V2V | 97-frame, approximately 4-second clips |
| Animation fallback | LTX 2B I2V | Lower-cost clip generation |

Current animation defaults prioritize stable short clips and repeatable 8 GB VRAM operation rather than long, uncontrolled generations.

## Testing and Validation

Run the pipeline test suite:

```bash
cd olympus/engines/pipeline
python -m pytest tests/ -v
```

The project currently documents **230 passing tests** as of 2026-08-21, including labeling-standard coverage.

Useful focused tests:

```bash
python -m pytest tests/test_gpu_lock.py -v
python -m pytest tests/test_video_router.py -v
python -m pytest tests/test_stage3c_cache.py -v
python -m pytest tests/test_stage5_assembly.py -v
python -m pytest tests/test_labeling.py -v
```

Run a panel smoke test:

```bash
python tests/smoke_test_stage3b.py
```

Run the LTX Director validation gate:

```bash
PYTHONPATH=olympus/engines/pipeline .venv/bin/python \
  olympus/engines/pipeline/tools/ltx_director_smoke.py \
  --template ltx_director_23.json \
  --panel <panel.png>
```

A successful lab gate writes:

```
workflows/.ltx_director_smoke_passed
```

## Troubleshooting

| Symptom | Likely cause | First action |
|---|---|---|
| Out-of-memory during generation | Resolution, batch size, or stale models exceed VRAM | Lower resolution, use batch size 1, call `comfy.free()` |
| Ollama and ComfyUI both OOM | Both workloads are occupying the GPU | Use GpuBatch, unload Ollama, then retry |
| krea2 weights are missing | ComfyUI model path or checkpoint installation issue | Run `python tools/model_smoke.py --template image_krea2.json` |
| Stage3c produced zero clips | Fresh-but-stale GPU lease is blocking the run | Inspect `/tmp/pipeline-gpu/gpu.lock` and verify owner/age |
| VLM review hangs | Review model is not installed or Ollama is unavailable | Check `ollama list`, then pull `qwen2.5vl:7b` |
| Stage gate is blocked | A required artifact or metric is missing | Run `python run.py report <slug>` |
| LTX test fails | Workflow, checkpoint, or node mismatch | Run the relevant LTX smoke tool and inspect workflow logs |

For complete diagnosis paths, see `docs/TROUBLESHOOTING.md`.

## Repository Layout

```
my-local-ai-stack/
├── start.bat / start.sh
├── setup.bat / setup.sh
├── stack.toml
├── config.json
├── olympus/
│   ├── kernel/                 # FastAPI, task queue, scheduler, agent runtime
│   ├── agents/                 # Markdown craft definitions
│   ├── web/                    # Dashboard frontend
│   └── engines/
│       └── pipeline/           # Anime recap-video pipeline
├── opencode/
│   ├── mcp_server.py
│   └── crafts/
├── shared/lib/
├── docs/
│   ├── GUIDE.md
│   └── TROUBLESHOOTING.md
├── foundation/                 # Optional n8n / container layer
├── voice-studio/
├── llm-wiki-workflow/
└── ComfyUI/
```

### Deeper implementation details

| Need | Read |
|---|---|
| Everyday setup and operations | `docs/GUIDE.md` |
| Errors, GPU conflicts, and recovery | `docs/TROUBLESHOOTING.md` |
| ComfyUI node and workflow details | `olympus/engines/pipeline/workflows/NODES.md` |
| Pipeline architecture and design decisions | `olympus/engines/pipeline/docs/` |
| Prompt templates per production stage | `olympus/engines/pipeline/prompts/` |
| Test coverage and contracts | `olympus/engines/pipeline/tests/` |

## Privacy and Network Use

Olympus is designed to run locally.

- Models are served by your local Ollama installation.
- Generated images, videos, prompts, project data, and logs are stored locally.
- Obsidian access uses your local vault and local REST API plugin.
- External traffic occurs only when you explicitly configure web search, web fetch, RSS, package installation, or other external integrations.

Review the configuration before enabling third-party services, containers, or MCP tools with network access.

## License

**Personal use only.** Do not redistribute this repository or its bundled configuration without permission.

You may modify the stack for your own local projects. Model checkpoints, GGUF quantizations, Ollama, ComfyUI custom nodes, and third-party dependencies remain governed by their own licenses.

If you use Olympus for public video content, you are responsible for ensuring that your source material, audio, images, model outputs, and publishing workflow comply with applicable platform policies and intellectual-property rules.

---

<!--
═══════════════════════════════════════════════════════════════════════════
SUPERSEDED / HISTORICAL CONTENT (kept for history — do not delete)
This is the previous full README (pre-2026-08-21 rewrite). It is preserved
verbatim so no engineering notes, plans, or tuning history are lost. Nothing
in this block is active; it is superseded by the sections above.

═══════════════════════════════════════════════════════════════════════════

# [OLD] Olympus — Local AI Stack  (superseded 2026-08-21)

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
-->