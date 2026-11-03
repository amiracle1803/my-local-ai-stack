# Olympus — Local AI Stack

> **Role since 2026-11-03: the W.A.T. Studio (Legion GPU).** This repo is now only the
> media side: ComfyUI + the anime pipeline (`olympus/engines/pipeline`) + Voice Studio,
> served by the **Studio API** (`olympus-kernel`, :4600, `/api/studio/*`, bearer token in
> `~/.config/wat/studio.token`). Hermes on either node uses it through the W.A.T. tools
> `studio_image`, `studio_tts`, `studio_video`.
>
> Moved into W.A.T. (`~/Dev/wat`): the dashboard -> W.A.T. Catalog (Integrations +
> Activity tabs), the harness -> `wat/harness` + the `goal_loop` workflow, Mem0 memories ->
> W.A.T. `memory_fact`. Retired here: Legion n8n + its Qdrant + jarvis-tunnel (n8n runs on
> the ProDesk), Open WebUI, stack-dashboard, memory-engine/qdrant-memory (snapshots in
> `_archive/qdrant-snapshots-2026-11-03`). Archived to the ProDesk HDD
> (`/mnt/nas_data/archive/legion-ai-stack-2026-11-03`): `.aitk`, `tools-external/sd-scripts`
> (LoRA training), `harness-deepseek` (run it on demand with `npx @deepseek-ai/dsh`).

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

The `AGENTS.md` playbook noted a stage order matching the zero-error build
(2026-08), but the single source of truth is `pipeline/blueprint.py
STAGE_ORDER`:

| Stage | Purpose | Major output |
|---|---|---|
| stage0 | Converts a brief into a structured script and project blueprint | `input/script.txt`, blueprint |
| stage0_dossier | Rich intake extraction: characters (appearance/race/family/relationships), location 360-views, scene settings, verbatim dialogue | `intake/dossier.json` |
| stage1 | Extracts characters, traits, voices, and contradictions | Character world bible |
| stage1_world | Builds locations, relationships, world rules, and voice registry | Full world bible |
| stage3 | Storyboard: shot direction and composition from scenes | `storyboard/storyboard.json` |
| stage2 | Screenplay: narration, dialogue, SFX timed to shot durations | `screenplay/screenplay.json` |
| stage4 | Creates TTS audio, timing, and viseme data | `audio/` |
| stage1r | Generates character, location, style, and voice reference assets | `references/` |
| stage3b | Creates still panels with identity and style controls | `panels/` |
| stage3c | Animates panels into short video clips | `clips/` |
| stage_vlm_review | Runs visual and audio quality checks | `reviews/vlm_review.json` |
| stage5 | Joins clips, audio, subtitles, chapters, and metadata | `video/final.mp4` |

Run one stage at a time while developing (order follows `STAGE_ORDER`):

```bash
python run.py run my-story stage0
python run.py run my-story stage0_dossier
python run.py run my-story stage1
python run.py run my-story stage1_world
python run.py run my-story stage3
python run.py run my-story stage2
python run.py run my-story stage4
python run.py run my-story stage1r
python run.py run my-story stage3b
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

## Artifact Identity (VFX naming standard)

Every shot keeps a **stable internal machine id** — `sh-001-01` (scene 001 +
shot 01) — as the JSON-contract, cache, and storyboard key. New artifacts are
written with a **canonical VFX-style name** derived from the machine id
(implemented as `canonical_name()` in `pipeline/identity.py`):

```
{project}_sc{scene:03d}_sh{shot:03d}_{asset}[_{variant}][_tk##]_v###.{ext}
```

Examples:

```
my-story_sc001_sh001_panel_v001.png       # panel
my-story_sc001_sh001_audio_v001.wav       # narration audio
my-story_master_v001.mp4                  # deliverable
```

Semantics:
- `tk##` — retry attempts / seed exploration
- `v###` — **approved revisions only**, starts at `v001`, bumped on deliberate
  regeneration. Never use `final`, `final2`, …
- `{project}` — the blueprint slug, sanitized
- Shot keys stay stable: legacy `sh_001_01` filenames resolve via
  `identity.legacy_stem()`; the pipeline never renames files that downstream
  stages already reference

> The companion human-readable labels index (`labels.json/.txt/.html`) from
> the superseded design is not part of the current pipeline build — see
> `docs/planning/README-superseded-2026-08-21.md` if it needs to be revived.

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
| Panel interpretation | `qwen2.5vl:7b` | Vision judge (must be a VLM) |
| Visual QA | `qwen2.5vl:7b` | Structured audio/visual review |
| Primary panel generator | `flux-2-klein-4b-Q4_K_M` | 832×512 panels via `image_flux_fallback` graph (installed, validated) |
| Animation (optional) | SVD XT (`svd_xt.safetensors`) | Off by default (`[animation] enabled = false` → panels/Ken Burns mode) |
| Experimenting | `krea2_turbo-*` / LTX 2.3 22B | **Not installed on the current host** — krea2 OOMs at panel res on 8 GB; see `docs/planning/comfyui-rebuild-log.md` |

Current defaults prioritize panels that fit 8 GB VRAM next to Ollama. Enable
animation in `stack.toml` only after a smoke-render passes on this host.

## Testing and Validation

Run the pipeline test suite:

```bash
cd olympus/engines/pipeline
python -m pytest tests/ -v
```

The suite lives in `tests/test_studio_pipeline.py` (stage order contract,
blueprint identity, scene split, optimizer gates, audio/video gating);
**10 passing tests** as of 2026-10-04:

```bash
python -m pytest tests/ -v
```

GPU renders require smoke-gate markers per profile (written into
`<project>/optimizer/`); without them the GPU stages run deterministic local
fallbacks (PIL placeholder panels + Ken Burns motion), which is what
`python run.py all <slug>` exercises by default.

## Troubleshooting

| Symptom | Likely cause | First action |
|---|---|---|
| Out-of-memory during generation | Resolution, batch size, or stale models exceed VRAM | Lower resolution, use batch size 1, call ComfyUI `/free` |
| Ollama and ComfyUI both OOM | Both workloads are occupying the GPU | `gpu_batch` unloads Ollama first; stop `llama-server.service` if it is holding VRAM |
| krea2 weights are missing | Not installed on the current host (OOMs at panel res on 8 GB) | Use the flux-2-klein default; see `docs/planning/comfyui-rebuild-log.md` |
| Stage3c produced zero clips | Animation is disabled (panels mode) | Set `[animation] enabled = true` in `stack.toml`; run a smoke render first |
| VLM review hangs | Review model is not installed or Ollama is unavailable | Check `ollama list`, then pull `qwen2.5vl:7b` |
| Stage gate is blocked | A required artifact or metric is missing | Run `python run.py report <slug>` |
| GPU lock stuck | A crashed run left the lease | Inspect owner/age in `/tmp/olympus-gpu.lock` before removing it |

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
> **History:** The full pre-2026-08-21 README (old stage orders, M-AP fix history,
> legacy repo layout, and superseded trials) is preserved at
> [`docs/planning/README-superseded-2026-08-21.md`](docs/planning/README-superseded-2026-08-21.md).
> Nothing in that file is active — this README is the single source of truth.
