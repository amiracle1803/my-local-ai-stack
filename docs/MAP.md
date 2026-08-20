# MAP.md — Repo Master Map & File-Structure Reference

> **Purpose** — the single document an agent (or human) reads to know where
> anything lives and what every file does. This supplements `AGENTS.md`
> (the chain-of-command playbook); it does **not** replace it.
>
> Last updated: 2026-08-12 (post-cleanup).

---

## 1. Architecture in one paragraph

`my-local-ai-stack` is a personal local-AI hub on Nobara Linux
(RTX 4070 Laptop, 8 GB VRAM). One Python venv (`.venv`), one config
(`stack.toml` → `stack/config.py`), one GPU mutually exclusive between
Ollama (LLM) and ComfyUI (image/video). The stack has four live subsystems:

- **Olympus Kernel** (FastAPI, :4600) — agent hub + dashboard + MCP server.
- **Anime Recap Pipeline** (`olympus/engines/pipeline/`) — 11-stage LLM+ComfyUI
  script→video pipeline.
- **Angelic Harness** (`harness/`) — independent loop engine
  (intake→plan→execute→verify→deliver) for general agentic tasks. **Running
  parallel to Olympus, not wired into it.**
- **LLM Wiki Workflow** (`llm-wiki-workflow/`) — self-contained Obsidian+LLM
  knowledge-base tool with its own MCP server and React frontend.

External: `ComfyUI/` (live install, gitignored), `tools-external/` (kohya
`sd-scripts` + `skills-audit` clones, gitignored), `.aitk/` (ai-toolkit +
training dataset, gitignored).

## 2. Single Source of Truth

- **Config** — `stack.toml` + `stack/config.py` (pydantic v2). There is
  no `config.json`, no `olympus.toml`, no `pipeline.toml`.
- **Playbook** — `AGENTS.md` (build chain-of-command, repo conventions,
  GPU-scheduling rules). Modified Dec 2025 forward.
- **This file** — `docs/MAP.md` — the canonical directory of where things
  physically live.

---

## 3. Canonical file structure (post-cleanup)

```
my-local-ai-stack/
├── AGENTS.md                # Build playbook (opencode-era authority)
├── README.md                # User README
├── stack.toml               # Single source of truth — all service config
├── requirements.txt         # Base deps
├── requirements-optional.txt # Heavy optional deps (cv2, faster-whisper, …)
├── setup.sh / setup.bat      # One-time installers
├── start.sh / start.bat      # Daily boot launchers
├── stop.sh                   # systemd service-stopper (Linux)
│
├── stack/                    # Typed config loader
│   ├── config.py             #   pydantic v2 loader, exposes `cfg`
│   └── __init__.py           #   forbids config.json / olympus.toml / pipeline.toml
│
├── olympus/                  # Core
│   ├── kernel/app.py         #   FastAPI :4600 — all endpoints
│   ├── agents/*.md           #   9 agent prompt crafts (jarvis, conductor, forge, …)
│   ├── web/index.html        #   single-page dashboard (vanilla HTML/CSS/JS)
│   ├── skills/opencode/mcp_server.py    #   MCP :4720 (web_fetch, read_file, code-search)
│   ├── engines/voice/        #   Flask TTS :5050 (Kokoro)
│   └── engines/pipeline/     #   Anime recap pipeline — see §4
│
├── harness/                  # Angelic Harness (independent of Olympus)
│   ├── cli.py __main__.py    #   `python -m harness` → models/smoke/run/golden
│   ├── core/                 #   loop.py (946 L), registry, models, memory, runstate
│   ├── ports/model_port.py   #   Ollama seam (4-rung fallback ladder)
│   ├── agents/*.prompt.md    #   5 role prompts + preamble
│   ├── registry/             #   models.yaml, agents.yaml, routing.yaml, workflows/
│   ├── schemas/              #   5 JSON schemas (task/handoff/report/scorecard/verdict)
│   ├── evals/golden/         #   3 golden tasks G1/G2/G3 + runner
│   ├── memory/ runs/         #   per-task run state (gitignored contents)
│   └── tests/                #   9 test files
│
├── llm-wiki-workflow/        # Standalone Obsidian+LLM wiki tool
│   ├── tools/                #   wiki.py / agent.py / watcher.py / server.py / mcp_server.py
│   ├── frontend/             #   React+Vite SPA (dev :7338)
│   ├── static/               #   built SPA
│   ├── wiki/ raw/            #   generated + source content
│   └── README.md             #   (note: not authoritative for the parent stack)
│
├── foundation/              # Docker layer (n8n, langfuse, qdrant) — mostly optional
│   ├── docker-compose*.yml
│   └── .env.example          #   (real .env is gitignored, see §6)
│
├── docs/
│   ├── GUIDE.md              #   Long-form user guide
│   ├── TROUBLESHOOTING.md    #   Common fixes
│   ├── MAP.md                #   THIS FILE
│   └── planning/             #   design docs (angelic-harness/*, second-brain/, comfyui/krea2 plans)
│
├── scripts/                 # Backup/sync ops
│   ├── backup-code.sh        #   git push → git archive zip → mira to vault + SSD
│   ├── backup-code.ps1       #   Windows mirror
│   └── sync-comfyui.ps1      #   weekly robocopy /MIR of ComfyUI → SSD
│
├── .opencode/               # ACTIVE opencode runtime — skills load from here
│   ├── skills/               #   ~365 dirs, ~592 SKILL.md — flat per-skill layout
│   ├── node_modules/         #   runtime deps (@opencode-ai/plugin 1.17.15)
│   └── package.json
│
│   ─── gitignored, on disk but not source ───
├── ComfyUI/                  #   live ComfyUI install (port 8188) — 466 GB
├── models/                   #   LLAMA_CPP GGUF fallback (~7 GB)
├── hf_cache/                 #   HuggingFace cache stub (CLIP ViT-L/14)
├── tools-external/           #   sd-scripts + skills-audit clones (5.6 GB)
├── .aitk/                    #   ai-toolkit clone + Kela LoRA dataset (6.1 GB)
├── _archive/                 #   moved-here dust (kept for posterity)
└── .agent-secrets/           #   secrets (gitignored)
```

---

## 4. Anime recap pipeline — file-by-file (`olympus/engines/pipeline/`)

**Stage order**: `stage0 → stage1 → stage1_world → stage1r → stage3 → stage2
→ stage3b → stage3c → stage_vlm_review → stage5` (per `pipeline/blueprint.py::STAGE_ORDER`).

### 4a. The importable package — `pipeline/` (36 .py modules, ~12.4 K LOC)

**Stage modules** (one .py per pipeline stage):
| File | Stage | Lines | Purpose |
|------|-------|------:|---------|
| `stage0_intake.py` | 0 | 623 | blueprint JSON → per-scene prose → integration → `script.txt` |
| `stage1_worldbible.py` | 1 M2a | 642 | full-script character scan + per-character profiles |
| `stage1_world.py` | 1 M2b | 495 | world inference, relationships, locations, voice registry |
| `stage1r_references.py` | 1R [GPU] | 394 | character refs, location angles, style refs, voice auditions |
| `stage3_storyboard.py` | 3 | 298 | block partition, motion tiers, panel state, SFX tagging |
| `stage2_screenplay.py` | 2 | 643 | scene segmentation, shot plan, SD prompts, narration/dialogue |
| `stage3b_images.py` | 3B [GPU] | 307 | scene plate + per-shot panels via `image_router`, VJEPA2 gate |
| `stage4_audio.py` | 4 | 322 | Voice Studio TTS, pacing bake-in, forced alignment |
| `stage3c_animation.py` | 3C [GPU] | 505 | LTX-2/Hailuo animation, upscale, lip-sync (runs AFTER stage 4) |
| `stage_vlm_review.py` | VLM | 362 | keyframe extract → Ollama llava → PASS/REVIEW/REJECT |
| `stage5_assembly.py` | 5 | 597 | per-shot segments → blocks → final MP4 + chapters + SRT |

**Client/router/util modules**:
| File | Lines | Purpose |
|------|------:|---------|
| `comfy_client.py` | 294 | ComfyUI client: queue, poll, copy, ban-list, `free()` |
| `voice_client.py` | 401 | Voice Studio HTTP client → stage 4 |
| `image_router.py` | 260 | image template selection: krea2 → anima → flux fallback |
| `video_router.py` | 110 | LTX i2v template selection (2B primary, 23B tiled fallback) |
| `hailuo_i2v.py` | 253 | Hailuo 2.3 I2V adapter (`engine=hailuo23`) |
| `lipsync.py` | 330 | alignment visemes → mouth_flipbook MP4 (Tier-3) |
| `realesrgan_upscale.py` | 118 | Real-ESRGAN anime 2x on LTX clips (ncnn/Vulkan, no torch) |
| `align.py` | 204 | forced alignment via whisperX → faster-whisper fallback |
| `chunking.py` | 96 | deterministic token chunking via `chonkie.TokenChunker` |
| `blueprint.py` | 190 | `Blueprint` project identity + story-pollution guard + `STAGE_ORDER` |
| `scores.py` | 174 | sqlite per-stage scorecards + `require_stage()` gate |
| `config.py` | 263 | loads `stack.toml` via `stack.config.cfg` → `PipelineConfig` |
| `gpu_lock.py` | 213 | file-lease GPU lock + `GpuBatch` (ComfyUI/Ollama mutex) |
| `llm.py` | 336 | shared Ollama layer: `.md` prompts w/ frontmatter, JSON repair loop |
| `_util.py` | 44 | shared helpers: `now_iso`, `read_json`/`write_json`, loaders |
| `vjepa.py` | 77 | V-JEPA2 perceptual sim (consistency gate) |
| `video_metrics.py` | 231 | `repeat_detect`, `segment_align_ratio`, `location_diversity` |
| `model_lab.py` | 370 | model testing (12-prompt suite, stress, compare) |
| `lora_docker.py` | 206 | kohya-ss LoRA training in podman (replaces old stub) |
| `agi_scorer.py` | 180 | AGI Brain V3 scorer (fidelity/causal_flow/consistency) |
| `agi_brain_v3.py` | 381 | AGI Brain V3 model definition (vendored; SBERT + JEPA) |
| `schemas/` | 333 | pydantic contracts: `stage0.py` + `worldbible.py` + `__init__.py` |

> The `olympus/engines/pipeline/pipeline/` double path is intentional — outer
> `pipeline/` is the engine root (run.py, docs, prompts, workflows_active/); inner
> `pipeline/` is the importable Python package so `from pipeline.X import Y` works
> when invoked from `ympus/engines/pipeline/`. Do NOT rename without updating
> every `from pipeline.x import y` across all 36 modules + tests.

### 4b. The engine root (NOT inside the package)
| File/Dir | Purpose |
|---------|---|
| `run.py` | CLI: `new-project`, `run <slug> <stage>`, `report` |
| `docs-lora-training.md` | kohya sd-scripts LoRA runbook |
| `comfyui-venv-pins.txt` | ComfyUI venv pin record |
| `prompts/` | 21 versioned LLM `.md` prompt templates w/ YAML frontmatter |
| `workflows/` | **LIVE** ComfyUI workflow JSONs + `manifest.json` + `ui/` (consumed by `pipeline/comfy_client.py::WORKFLOWS_DIR`). Despite `workflows_active/README.md`'s "deprecated" note, the code never migrated — `workflows/` is the source of truth. |
| `workflows_active/` | curated subset / experimental staging area (NOT wired into code; do not delete without confirming `comfy_client.WORKFLOWS_DIR` is updated) |
| `tests/` | 22 pytest files (169 passing per current run; README's "192" reflects pre-drift state) |
| `tools/` | smoke-tests, `model_smoke.py`, `ltx_smoke.py`, validation scripts |
| `assets/sfx/manifest.json` | empty placeholder `[]` (SFX catalog unbuilt) |
| `projects/ models/ loras/` | per-project + weight dirs (gitignored) |
| `.pytest_cache __pycache__/` | ignored object cruft |

---

## 5. Other subsystems — file-by-file

### 5a. `stack/`
- `stack/config.py` (258 L) — pydantic v2 loader for repo-root `stack.toml`;
  defines `OllamaModels`, `OllamaAgentRoles`, kernel/comfyui/voice-studio/
  open-webui/llama-server/pipeline sections. Exposes `cfg` singleton.
- `stack/__init__.py` (13 L) — declares `stack.toml` single source of truth.

### 5b. `olympus/`
- `kernel/app.py` (617 L) — FastAPI app exposing health / services / agents /
  tasks / orchestrate / voice-tts / pipeline / artifacts / brain-notes /
  system endpoints. Serves the dashboard at `/`. Loads `stack.config.cfg`.
- `agents/` — 9 prompt `.md` files: anna, archivist, calliope, conductor,
  forge, jarvis, plutus, scribe (per kernel docs).
- `web/index.html` (1078 L) — HUD dark dashboard, 4 tabs (home/voice/
  pipeline/brain).
- `skills/opencode/mcp_server.py` (85 L) — FastMCP on :4720 (web_fetch,
  read_file, code-search).
- `engines/voice/app.py` (111 L) — Flask TTS (Kokoro-82M, `/api/health`,
  `/api/voices`, `/api/tts`).

### 5c. `harness/`
- `cli.py` (188 L) — `python -m harness` commands: `models`, `smoke`, `run`,
  `golden`.
- `core/loop.py` (946 L) — the Manager state machine (INTAKE→PLAN→EXECUTE→
  VERIFY→DELIVERY) with per-step GATHER/ACT/VERIFY, ReAct executor,
  critic, scorer, verifier; wall-clock budget; one-replan cap; episodic memory
  writeback. The largest file in harness.
- `core/registry.py` — loads `registry/*.yaml` → resolves role/tier to a model.
- `core/models.py memory.py runstate.py` — pydantic models, filesystem memory,
  run-dir scaffolding.
- `ports/model_port.py` — Ollama role→tier→model seam, JSON-schema output,
  4-rung fallback ladder (primary→repair→sibling→tier+1).
- `agents/*.prompt.md` (6 files) — planner / executor / critic / scorer /
  verifier / `__preamble.prompt.md`.
- `registry/{models,agents,routing}.yaml` + `registry/workflows/` (1 n8n JSON
  + 1 markdown card).
- `schemas/` — 5 JSON-schema contracts.
- `evals/golden/` — `G1_writing.yaml`, `G2_coding.yaml`, `G3_analysis.yaml`
  + `golden_runner.py`.
- `tests/` — 9 test files.

### 5d. `llm-wiki-workflow/`
- `tools/` — `wiki.py` (deterministic CLI), `agent.py` (LLM ingest), `watcher.py`
  (auto-ingest), `server.py` (FastAPI + SPA host), `mcp_server.py` (MCP stdio),
  `atlas_bridge.py`, `obsidian_sync.py`.
- `frontend/` — React 18 + Vite 6 SPA (`Home/WikiPage/WikiList/Search/Log/Atlas/Raw/Tools`).
- `static/` — built SPA (`index.html`, `assets/`).
- `wiki/` — generated: `index.md`, `overview.md`, `log.md`, `entities/*.md`,
  `concepts/*.md`, `comparisons/`, `sources/`.
- `raw/` — immutable source inputs (`articles/`, `repos/`, `papers/`, etc.).
- `wiki-cli` / `*.bat` — bash/Windows shims for the tools.
- `README.md` — wiki's own readme (independent of parent stack).
- `.mcp.json`, `.claude/settings.local.json`, `.vscode/{tasks,settings,extensions}.json`.

### 5e. `foundation/`
- `docker-compose.yml` — n8n at :5678 (basic auth, persistent volume).
- `docker-compose.optional.yml` — Qdrant :6333 + Portainer :9443.
- `docker-compose-langfuse.yml` — Langfuse+v2 + postgres at :3030.
- `README.md` — explains mostly-optional Docker layer.
- `.env.example` — TZ, N8N_USER/PASSWORD, N8N_API_KEY placeholders.
  (Real `.env` is **gitignored — never committed again** after history scrub.)

### 5f. `docs/`
- `GUIDE.md` — long-form human guide.
- `TROUBLESHOOTING.md` — symptom→fix list.
- `MAP.md` — this file.
- `planning/` — design docs:
  - `comfyui-anime-pipeline-plan.md`, `node-additions-plan.md`, `krea2-lab-report.md`,
    `anime-pipeline-v2-design.md`, `aether-studio-original-spec-stages0-2.md`
  - `second-brain/DESIGN.md`
  - `angelic-harness/` — 13 design docs (overview, walkthrough, agent, claude,
    handoff, improvement, integration, loop-engineering, memory, n8n, routing,
    skills, systems-prompts, training, todos)

### 5g. `scripts/`
- `backup-code.sh` / `.ps1` — git push → `git archive` zip to vault + SSD mirror
  (added after the 2026-07-09 Olympus loss).
- `sync-comfyui.ps1` — weekly robocopy `/MIR` of `C:\AI\ComfyUI` → `E:\AI\ComfyUI`
  as scheduled task `SyncComfyui`.

---

## 6. Secrets & history hygiene

**Rules (enforced):**
- `foundation/.env` is gitignored — never stage it. Set values via `.env.example`.
- `__pycache__/`, `*.pyc`, `*.log`, `.pytest_cache/`, `.cache/`, `*.zip`,
  `*.safetensors`, `*.ckpt`, `*.pt`, `*.pth`, `*.bin`, `*.sqlite*` are
  gitignored.
- `ComfyUI/`, `tools-external/`, `.aitk/`, `olympus/engines/voice/.venv`,
  `olympus/engines/pipeline/projects/`, `models/`, `hf_cache/` are gitignored.
- Shared tokens must come from `.agent-secrets/` (gitignored) or environment
  variables, never hardcoded into source.

**Rotated & scrubbed (transcript commit ref):**
- n8n password + `N8N_API_KEY` (was in `foundation/.env`, scrubbed from history).
- MCP_GATEWAY_AUTH_TOKEN (was baked into `foundation/start-mcp-gateway.bat`,
  scrubbed from history + value removed).

---

## 7. Bloat-removed log

| Date | Item | Size | Reason | Action |
|------|------|-----:|--------|--------|
| 2026-08-12 | `CLAUDE.md` (root) | 19 KB | Windows-era, contradicts `AGENTS.md` | Deleted |
| 2026-08-12 | `claude-skills/` (gitlink) | ~84 MB tree / 1,110 SKILL.md | `wired via .opencode/skills/` already | Removed |
| 2026-08-12 | `ComfyUI.zip` | 2.6 GB | Offline backup blob, unreferenced | Deleted from disk |
| 2026-08-12 | `upscale_work/` | 29 GB | Aug 8 WIP media, zero references | Deleted from disk |
| 2026-08-12 | `session-ses_0132.md` | 340 KB | Session paste w/ terminal garbage | Deleted |
| 2026-08-12 | `projects/` (root) | 0 | Empty ghost dir (not tracked by git) | rmdir |
| 2026-08-12 | `agi-brain` (symlink) | tiny | Orphan — points at external dir | Removed |
| 2026-08-12 | `constraints.txt` | 71 B | Stale `torch cu130` pin (host uses 2.6.0+cu124) | Deleted |
| 2026-08-12 | `pipeline_workflow.mermaid` | small | Zero references anywhere | Deleted |
| 2026-08-12 | `llm-wiki-workflow/long guide.txt` | small | Corrupted duplicate of root `CLAUDE.md` prologue | Deleted |
| 2026-08-12 | `llm-wiki-workflow/run-all.bat`, `workflow.bat` | tiny | Deprecated stubs → `start.bat` | Deleted |
| 2026-08-12 | `harness/runs/` contents | small | 30 stale G1 golden-run smoke dirs from 2026-08-05 | Wiped |
| 2026-08-12 | `olympus/engines/voice/.venv` | 4.9 GB | Should never have been in repo tree (gitignored since) | Deleted from disk |

**Total recovered: ≈ 36.5 GB on disk + ~1 MB tracked bloat.**

---

## 8. Cheat-sheet: "if you want to edit X, look at Y"

| Want to edit | File |
|---|---|
| Models in use (script/vision/review/triage) | `stack.toml` `[ollama.models]` + `[ollama.agents]` |
| Pipeline panel resolution, denoise, motion tiers | `stack.toml` `[animation]` + `[pipeline]` |
| Banned ComfyUI checkpoints | `stack.toml` `[comfyui.models].banned_checkpoints` + `pipeline.config.resolve_image_model` |
| Add an Olympus kernel endpoint | `olympus/kernel/app.py` |
| Add an Olympus agent | new `.md` under `olympus/agents/` (mirror existing frontmatter) |
| Edit a pipeline stage | `olympus/engines/pipeline/pipeline/stageN_*.py` |
| Add a new pipeline stage | new `stageN_xxx.py` in `pipeline/` + register in `pipeline/blueprint.py::STAGE_ORDER` |
| Edit an LLM prompt template | `olympus/engines/pipeline/prompts/*.md` (frontmatter version-stamped) |
| Add a ComfyUI workflow | new JSON under `olympus/engines/pipeline/workflows/` + entry in `workflows/manifest.json` (this is what `pipeline.comfy_client.py::WORKFLOWS_DIR` reads; `workflows_active/` is an experimental staging area, not wired in) |
| GPU lock / Ollama-ComfyUI mutex | `pipeline/gpu_lock.py::GpuBatch` |
| Bypass/extend pydantic contracts | `pipeline/schemas/{stage0,worldbible}.py` |
| Add a harness agent role | `harness/agents/<role>.prompt.md` + `harness/registry/agents.yaml` |
| Change harness model routing | `harness/registry/routing.yaml` + `harness/registry/models.yaml` |
| Add a harness tool | `harness/ports/*.py` (define a new port) |
| Install a new opencode skill | drop `<name>/SKILL.md` under `.opencode/skills/<name>/` |
| Add a backup/sync job | `scripts/` |
| Update Dockerized services | `foundation/docker-compose*.yml` |

---

## 9. Verification commands (re-run after future changes)

```bash
cd /home/amire/Downloads/my-local-ai-stack

# Config loads
.venv/bin/python -c "import stack.config; print(stack.config.cfg.kernel.port)"

# Kernel smoke-imports
.venv/bin/python -c "from olympus.kernel import app; print('ok')"

# Pipeline CLI
.venv/bin/python olympus/engines/pipeline/run.py --help

# Pipeline CLI — run.py all (Self-Critique Loop)
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ DEFAULT: Full critique + auto-retry                                          │
# │ python run.py all my-story --brief /tmp/my-brief.md                          │
# │                                                                              │
# │ --no-critique: Skip all LLM critique calls                                  │
# │ python run.py all my-story --brief /tmp/my-brief.md --no-critique            │
# │                                                                              │
# │ --no-retry: Critique runs but NO auto-retry on failure                      │
# │ python run.py all my-story --brief /tmp/my-brief.md --no-retry               │
# └─────────────────────────────────────────────────────────────────────────────┘

# Pipeline tests (expect ~199 passing)
cd olympus/engines/pipeline && ../../.venv/bin/python -m pytest tests/ -q

# Harness CLI
.venv/bin/python -m harness.cli --help

# Disk sanity
du -sh . ComfyUI/ upscale_work/ 2>/dev/null
```
