# AGENTS.md — Local AI Stack builder rules

This file is the agent build playbook for the Local AI Stack. It defines how
agents (Claude, OpenCode, or any builder) should interact with this project.

## Architecture

```
stack.toml          ← Single source of truth (all services, models, ports, paths)
stack/config.py     ← Typed config loader (pydantic v2)
olympus/kernel/     ← Olympus kernel (:4600 FastAPI) — the central hub
olympus/engines/    ← Pipeline engine, Voice Studio
olympus/web/        ← Dashboard UI (single-page, vanilla HTML/JS/CSS)
ComfyUI/            ← Image/animation generation (external, port 8188)
```

## Chain of command

You are a builder, not the manager. The manager (Fable, in Claude Code
sessions) verifies gates and commits — **builders never run git**, in
OpenCode or otherwise. If a task seems to need a commit, stop and report
that it is ready for the manager instead of running `git` yourself.

## Repo conventions

- **pydantic v2** for all structured data models — no bare dicts for
  anything that crosses a stage boundary in the pipeline.
- **Single config**: `stack/config.py` + `stack.toml`. No separate config.json
  or olympus.toml or pipeline.toml — all merged into one.
- **Touch only named files.** Same rule as work orders, generalized: don't
  drive-by refactor, reformat, or "clean up" files outside the stated scope.
- **Verify before calling anything done.** Import the module, run the
  relevant test, or smoke-test the endpoint.
- **No git for builders.** Ever. Leave commits to the manager.

### Artifact naming rules (VFX identity standard — enforced going forward)

Canonical ids live in `pipeline/identity.py`; every *new* artifact follows the
pattern `{project}_sc{scene:03d}_sh{shot:03d}_{asset}[_{variant}][_tk##]_v###.{ext}`.
The internal machine id (`sh-001-01` = scene 001 + shot 01) is the JSON-contract
/ cache / storyboard key and is **never renamed** once downstream stages
reference it — `identity.legacy_sid_from_filename()` / `canonical_id_from_filename()`
resolve both styles. Rules:

1. IDs are lowercase ASCII and use underscores only.
2. Do not use spaces, dates, punctuation, or narrative prose in engine filenames.
3. Scene numbers are sequential: `sc001`, `sc002`, `sc003`.
4. Shot numbers increment: `sh001`, `sh002`, `sh003` (gap-numbering `sh010` is
   a documented future option — do not renumber existing shots).
5. Panels are variants within one shot: `pn01`, `pn02`, `pn03`.
6. Clips are output variants within one shot: `cl01`, `cl02`.
7. Use `tk##` for retry attempts and seed exploration (already implicit in
   ComfyUI's `_0000N` counter).
8. Use `v###` only for a deliberate new approved revision (starts at `v001`,
   bumped only on regeneration).
9. Never rename an artifact after downstream stages reference it.
10. Human-readable names belong in `labels.json`/metadata, not core filenames.
11. Deliverables: `{project}_master_v###.mp4` / `.srt` / `_chapters.txt`.

## Environment

This machine runs Nobara Linux (Fedora-based) with OpenCode running
**directly on the host**.

- **Stack venv**: `~/Downloads/my-local-ai-stack/.venv`, Python 3.12, uv-managed.
- **ComfyUI venv**: `ComfyUI/.venv`, PyTorch 2.6.0+cu124 pinned.
- **GPU**: RTX 4070 Laptop, 8GB VRAM.

## Services (systemd)

| Service | Port | Unit | Type |
|---------|------|------|------|
| Ollama | 11434 | `ollama.service` | System unit |
| Open WebUI | 8080 | `open-webui.service` | User unit (podman) |
| ComfyUI | 8188 | `comfyui-server.service` | User unit |
| Voice Studio | 5050 | `voice-studio.service` | User unit |
| Olympus Kernel | 4600 | `olympus-kernel.service` | User unit |
| OpenCode MCP | 4720 | `opencode-mcp.service` | User unit |
| llama.cpp | 8081 | `llama-server.service` | User unit (optional) |

## GPU scheduling

RTX 4070 8GB VRAM. Ollama and ComfyUI must NEVER run GPU work
simultaneously — they will OOM each other. Rules:

1. **LLM work**: ComfyUI must be idle (unload models).
2. **Image/video work**: Unload all Ollama models before queuing ComfyUI.
3. **Kernel agents** use `llama3.2:3b` (triage) by default to coexist with
   ComfyUI. Heavy pipeline stages use `qwen3:8b` when ComfyUI is idle.

## Image models (GGUF, 512×512)

| Model | Time | Steps | VRAM | Status |
|-------|------|-------|------|--------|
| krea2_turbo-Q4_K_S | 32s | 8 | ~5GB | Primary |
| krea2_turbo-Q4_K_M | 28s | 8 | ~5GB | Fallback |
| FLUX.2-klein-4B-GGUF|  |  | ~ | Floor |

## Where things live

- Config: `stack.toml` → `stack/config.py`
- Kernel: `olympus/kernel/app.py`
- Pipeline: `olympus/engines/pipeline/`
- Voice: `olympus/engines/voice/`
- Dashboard: `olympus/web/index.html`
- Docs: `docs/`
- AGENTS.md: This file.
- DeepSeek Harness: `harness-deepseek/` (local clone of `deepseek-ai/deepseek-harness` v0.1, 80M) + `~/Documents/harness` (second copy)
- Git history: `git log --oneline` (80 commits since 2026-07-02); `origin` at `github.com/amiracle1803/my-local-ai-stack`

## DeepSeek Harness (dsh) — integration notes

**What it is:** A plugin-based agent harness on Cordis (everything is a plugin — model adapter, tools, sandbox, LSP, permission system, session log, summarizer, subagent registry, web UI). Ships 4 presets: `standard` (full coding agent), `code` (PTC / programmatic tool calling), `minimal` (persistent shell + str-replace editor, RL-compatible), `cordis` (creation mode — self-modifying runtime).

**Key architecture:** Append-only event log (source of truth); derived messages projected from log on every step (prefix-caching stable); immutable history enforced by invariant module. Persistence via JSONL or SQLite (monotonic `SCHEMA_VERSION`).

**Run locally:**
- Quick: `npx @deepseek-ai/dsh web` → Web UI at `http://127.0.0.1:3080`
- From source (in `harness-deepseek/`): `pnpm install && pnpm run build && pnpm dsh web`
- Headless task: `pnpm dsh --profile headless "your task"`

**LLM endpoint config:** `packages/llm/llm-deepseek/` uses `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` (OpenAI-compatible). Generic multi-provider via `packages/llm/llm-pi-ai/` (`baseURL`, `apiKeyEnv`, `models` overrides) — supports Ollama / any OpenAI-compatible gateway.

**Subagent / external agent connection:**
- Register a `SubagentProvider` plugin (see `packages/subagent/subagent-claude-code/`, `subagent-codex/`, `subagent-acp/`)
- ACP server: `packages/acp/` + `examples/acp-agent/cordis.yml`
- JSON-RPC: `packages/sdk/` + `examples/jsonrpc-agent/cordis.yml`
- Subagent tools in presets (`tool-subagent-codex`, `tool-subagent-claude-code`) are `disabled: true` by default — copy preset, remove `disabled` to enable.

**Agent/builder docs:**
- `harness-deepseek/docs/architecture.md` — extension map (no privileged core; mount plugins beside others)
- `harness-deepseek/docs/capability-seams.md` — seams for tools/agents/persistence
- `harness-deepseek/examples/headless-agent/composition.md` — runnable headless composition
- `harness-deepseek/docs/config-catalog.md` — all config keys
- `harness-deepseek/.agents/notes/` — 684 design memos (proposed/implemented/rejected/archived) + validation gates

**Git history view:** This repo has **80 commits** (first `5be9c2c` 2026-07-02). Full log: `git log --format="%h %ad %s" --date=short`. Key milestones:
- 2026-07-09: Olympus rebuilt from recovered spec (Windows reinstall)
- 2026-07-10: Full pipeline stages (M1–M7), Linux migration, ComfyUI update
- 2026-07-11: Krea2 live, zero-error workflows, kornia pin
- 2026-08-16: Skills library import, weekly-commit timer, Qwen3-30B default, harness-deepseek added

The harness can "see" all changes via `git log` and GitHub remote; append-only log design means history is immutable and reconstructible — aligns with DeepSeek's "never edit past history" rule.


Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

# Project: Local Anime / Manga Recap Video Pipeline

> **⚠ State note (2026-07-09, post Windows reinstall):** The original `olympus/`
> was **lost** (lived only on the old C: drive, never pushed to GitHub). It was
> **rebuilt the same day** from the spec recovered in
> `E:\AI\Models\hermes\skills\local-agent-hub-ops\` — same API contract
> (kernel :4600, opencode MCP :4720), same agent-as-markdown registry, 7 agents
> (scribe, conductor, calliope, plutus, forge, archivist, anna). All model roles
> currently map to `llama3.1:8b` (originals were qwen2.5:3b/7b + qwen3:8b — see
> `olympus/olympus.toml` to restore). The voice engine and pipeline engine are
> NOT yet rebuilt. Surviving pieces:
> ComfyUI (`C:\AI\ComfyUI`), Obsidian vault (copied to
> `C:\Users\amire\Documents\Obsidian Vault`, original kept at
> `E:\Obsidian Vault`), `E:\LifeOS`, and `anime-pipeline-updated` in
> `E:\Projects`. The E: drive was reorganized 2026-07-09 (AI models under
> `E:\AI\Models`, projects under `E:\Projects`). ComfyUI's venv base
> (Python 3.11.9) and the stack venv (Store Python 3.12) were reinstalled
> the same day.

## Code backup protocol (MANDATORY — established after the olympus loss)

**Every time a piece of code is completed, immediately run:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup-code.ps1
```

It (1) commits + pushes to GitHub, (2) zips the tracked source into
`C:\Users\amire\Documents\Obsidian Vault\Projects\Code Backups\`, and
(3) copies the zip to `E:\Backups\code-snapshots\` (skipped gracefully when
the E: drive is offline — it drops sometimes). Claude: run this yourself at
the end of any session that produced code; never leave new code existing only
on one disk.

## Session startup rules

On every new session:
1. Read this `CLAUDE.md` first.
2. Inspect the actual repo structure before making assumptions.
3. Distinguish clearly between:
   - what already exists,
   - what is partially implemented,
   - and what is still planned.
4. Propose a short plan before editing files.
5. Prefer minimal, targeted changes over broad rewrites.
6. Do not replace working local tooling unless I ask.


## Edit safety rules

- Do not rewrite large files just to “clean them up.”
- Preserve existing working behavior unless the task requires changing it.
- When fixing bugs, prefer the smallest correct patch first.
- Before introducing a new dependency, explain why it is needed.

- If a local/free tool is good enough, prefer it over a paid or cloud tool.
- Show me the plan before major edits.
- For multi-file changes, explain which files will change and why.
- Prefer modifying existing structure over inventing a new architecture unless necessary.



## High-level goal

Build a **fully local** pipeline that takes a long-form story script (light novel / webnovel style), analyzes it, and outputs an **anime / manga recap-style video**: structured scenes, consistent character designs, anime panels/clips, TTS narration, and ffmpeg assembly. This should run on my Windows 11 laptop via VS Code, with no cloud dependencies unless I explicitly request them.       

The system should:
- Read a pasted script, break it into scenes/shots, and build a **world bible** with characters, outfits, locations, and other assets.  
- Generate consistent anime / manga character designs that can evolve over the story while staying on-model.  
- Map each scene and shot to prompts for diffusion / video models and assemble everything into a recap video.  
- Re-run over its own outputs to detect inconsistencies (wrong outfit, missing character, etc.) and propose improvements.       

---

## Environment & constraints

- OS: Windows 11
- Editor: VS Code with Claude Code extension
- Hardware: Lenovo Legion with RTX 4070 Laptop GPU (8 GB VRAM), 32 GB RAM (assume mid-range GPU budget).    
- Preference: **fully local** stack (local LLM via Ollama/LM Studio, ComfyUI, local TTS, local video models). Cloud APIs only if I explicitly say so.

---

## Current components (conceptual)

These pieces either already exist or are planned per the executive summaries:

- **Script parsing / NLP (Python)**  
  - Reads `script.txt` / pasted text and outputs structured JSON:  
    - `worldbible.json`: title, synopsis, characters, global info  
    - `scenes.json`: per-scene summary with empty/partial `shots` arrays  
  - Uses a local LLM (e.g., Gemma/Qwen/Phi via Ollama) plus rules/regex/NLP to segment scenes and extract characters/dialogue.       

- **Anime image generation (local)**  
  - Runs anime-focused diffusion models (Pony / Illustrious / other SDXL anime checkpoints) via **ComfyUI** to generate character sheets and per-shot panels.    

- **Optional video generation**  
  - Uses open-weight text/image-to-video models (e.g., **CogVideoX** or similar) to animate key shots, possibly via ComfyUI workflows.    

- **TTS / audio**  
  - Uses **Kokoro TTS** or similar local TTS for narration and character lines; later possibly lip-sync with models like Wav2Lip or LatentSync.       

- **Composition**  
  - Uses **ffmpeg** (and/or MoviePy) to stitch panels/clips, narration, SFX, and background music into a final MP4.       

- **Frontend / control surface**  
  - Eventually: a local web UI (React or plain JS) on `localhost` to paste scripts and monitor progress, backed by a Python/Node orchestrator.       

---

## Repo structure (current — olympus-centric)

```
my-local-ai-stack/
├── olympus/                    ← the system
│   ├── kernel/                 FastAPI core (app.py, config, agents, voice, etc.)
│   ├── agents/                 agent .md definitions (aether, iris, athena...)
│   ├── data/                   runtime DB, logs, voice/shared artifacts
│   ├── web/                    dashboard UI (index.html, css, js)
│   ├── engines/                pipeline components
│   │   ├── voice/              TTS engine (Kokoro/F5 — standalone Flask app)
│   │   ├── pipeline/           story → anime pipeline (mangapipeline)
│   │   └── vault-sample/       sample Obsidian vault stand-in
│   ├── shared/                 shared Python libs + prompts
│   ├── skills/                 opencode config + MCP server
│   ├── olympus.toml            config (models, paths, keys)
│   ├── run.bat                 start Olympus directly
│   └── watchdog.ps1            auto-restart on crash
├── foundation/                 Docker/infra layer (n8n, Langfuse, MCP gateway)
│   ├── docker-compose.yml
│   └── *.bat                   per-service start/stop scripts
├── docs/                       documentation
│   ├── planning/               plans + research (PIPELINE_PLAN, amir_life_os…)
│   │   ├── agent-design-notes/ agent system deep-dives
│   │   └── references/         workflow references (amplifier-superpowers)
│   ├── GUIDE.md                full walkthrough
│   └── TROUBLESHOOTING.md      symptom → fix table
├── llm-wiki-workflow/          wiki engine (referenced by olympus.toml wiki_root)
├── _archive/                   everything not actively needed but preserved
│   ├── legacy/                 prior-session frozen archives (pre-2026-07-05)
│   ├── projects/               archived side projects (LifeOS, Personal-Coding-AI…)
│   ├── reference-pdfs/         10 research PDFs
│   └── reference-html/         3 saved web pages
├── .venv/                      Python virtual environment
├── config.json                 user config (vault_path, models, ports)
├── config.example.json         template for config.json
├── start.bat                   ONE-button startup (Ollama → Olympus → OpenCode → ...)
├── setup.bat                   one-time installer
├── requirements.txt            Python dependencies
├── requirements-optional.txt   optional extras
├── .mcp.json                   MCP server config
├── CLAUDE.md                   this file
└── README.md      
```

---

## How to run things (initial expectations)

These commands are **targets**; adjust to the real commands after you inspect the repo:

- **Create/activate venv (Windows, PowerShell)**  
  - `python -m venv .venv`  
  - `.\.venv\Scripts\Activate.ps1`  
  - `pip install -r requirements.txt`

- **Script parsing (MVP):**  
  - `python scripts/parse_script.py data/inputscripts/my_story.txt`  
  - Expected outputs: `data/parsed/worldbible.json`, `data/parsed/scenes.json`

- **Panel generation (future):**  
  - `python scripts/generate_panels.py data/parsed/scenes.json`

- **Video assembly (future):**  
  - `python scripts/build_video.py data/parsed/scenes.json`

- **ComfyUI location (since 2026-07-09):** primary install `C:\AI\ComfyUI`;
  `E:\AI\ComfyUI` is a weekly-synced mirror (scheduled task "SyncComfyUI" →
  `scripts\sync-comfyui.ps1`, robocopy /MIR C→E). Make changes on C: only.

- **ComfyUI startup (RTX 4070 Laptop, 8 GB VRAM):**  
  - Required flags: `--lowvram --disable-cuda-malloc`
  - **Disabled nodes** (rename-disabled, do not re-enable without testing):
    - `C:\AI\ComfyUI\comfy_api_nodes_disabled` — ComfyUI cloud API nodes (Anthropic/OpenAI); crashes pydantic on import
    - `C:\AI\ComfyUI\custom_nodes\ComfyUI-WanVideoWrapper_disabled` — re-enable only when doing video generation
  - **Package pins** (do not upgrade without testing): `torch==2.6.0+cu124`, `pydantic==2.13.4`, `pydantic-core==2.46.4`
  - Start command (`--novram` offloads aggressively to CPU — more stable for consecutive generations):
    ```powershell
    Start-Process -FilePath "C:\AI\ComfyUI\.venv\Scripts\python.exe" `
      -ArgumentList "main.py","--listen","127.0.0.1","--port","8188","--novram","--disable-cuda-malloc" `
      -WorkingDirectory "C:\AI\ComfyUI" `
      -RedirectStandardOutput "C:\AI\ComfyUI\comfyui_out.log" `
      -RedirectStandardError "C:\AI\ComfyUI\comfyui_err.log" `
      -WindowStyle Normal
    ```
  - **VRAM note**: After ~5 consecutive SDXL generations the GPU accumulates fragmented VRAM that persists across process restarts on Windows. Use `scripts/generate_safe.py` which auto-restarts ComfyUI between characters, or reboot the PC to fully clear GPU state.

- **Voice Studio:**  
  ```powershell
  cd olympus\engines\voice
  start.bat
  ```

- **Run pipeline scripts (PowerShell):**
  ```powershell
  cd olympus\engines\pipeline
  $env:PYTHONPATH = "C:\Users\amire\dev\anime-pipeline"
  .\.venv\Scripts\python.exe scripts/generate_character_sheets.py my_first_story
  ```

---

## Coding style & preferences

- Languages: **Python first**, Node/TypeScript second if needed for web frontend.       
- Style:  
  - Small, composable functions; pure where possible.  
  - Prefer explicit, typed data models (Pydantic) over loose dicts.  
  - Clear, pragmatic docstrings; minimal comments where the code is self-explanatory.  
  - No huge “god scripts” that do everything; I want modular steps (parse → generate → assemble).    
- Testing:  
  - Add at least minimal unit tests for core steps (e.g., parser, basic image pipeline wiring, ffmpeg command builder).

---

## Obsidian vault skills

The real Obsidian vault (`C:\Users\amire\Documents\Obsidian Vault`) is the shared second brain for this whole stack — the dashboard's `_generated/` output, Agent Atlas's memory/indexer, and AnythingLLM's MCP connection to the Obsidian Local REST API plugin all read/write it. A sample stand-in vault lives at `olympus/engines/vault-sample/` for testing without touching your real vault.

The **`obsidian@obsidian-skills`** plugin (from `github.com/kepano/obsidian-skills`, 39k+ stars, maintained by Obsidian's own creator) is installed for the standalone Claude Code CLI (`claude plugin list` to confirm) and cloned for OpenCode at `~/.opencode/skills/obsidian-skills/`. It is **not** auto-loaded in the VS Code extension session, but the skill files are real and on disk at `~/.claude/plugins/cache/obsidian-skills/obsidian/<version>/skills/` — read them directly with the Read tool when working with vault content instead of guessing at Obsidian's syntax:

- **`obsidian-cli`** — drive a *running* Obsidian instance via the `obsidian` CLI (read/create/search notes, daily notes, properties, tags, backlinks; also plugin/theme dev workflow).
- **`obsidian-markdown`** — Obsidian-flavored Markdown: wikilinks, embeds, callouts, frontmatter properties, tags, comments, highlights, Mermaid, footnotes. Use this instead of writing plain generic Markdown into vault notes.
- **`obsidian-bases`** — `.base` file schema (filters, formulas, views, summaries) for anyone building database-style views over notes.
- **`json-canvas`** — `.canvas` file schema (nodes/edges/groups) for mind maps, flowcharts, project boards.
- **`defuddle`** — CLI (`defuddle parse <url> --md`) that extracts clean markdown from web pages; prefer it over WebFetch for normal articles/docs to save tokens.

When a task involves creating or editing files in the vault, check the relevant `SKILL.md` first rather than writing ad-hoc Markdown/JSON.

---

## How I want you (Claude Code) to help

### General behavior

- Read **this file first** before doing anything else.  
- When I ask for help, **propose a short plan first** (1–5 steps), then implement.  
- When editing, **show diffs** and ask before applying changes.  
- Before big refactors, ask me to confirm and recommend creating a git commit or branch.

### Priority tasks (short-term)

1. **Script parsing & world/scene JSON**  
   - Ensure we have a solid `ParsedScript` model (world bible + scenes + shots) and a working `script_parser.py` that can handle long scripts.  
   - Add robust error handling if LLM output is malformed JSON.    

2. **Tight integration with local LLM**  
   - Create or refine `llm_client.py` for a local HTTP endpoint (Ollama/LM Studio/etc.).  
   - Make prompts deterministic and easy to tweak (system message + user instructions in one place).    

3. **Glue to ComfyUI / diffusion**  
   - Define how `Shot.prompt_anime` + character states map into a concrete ComfyUI workflow (e.g., via HTTP API).  
   - Implement a batch panel generator script that reads `scenes.json` and outputs images to `data/images/`.    

4. **ffmpeg composition skeleton**  
   - Even if image/video generation is stubbed, create a basic `build_video.py` that composes a folder of images + narration into an MP4 with simple transitions.       

5. **Self-critique loop (later)**  
   - Add a second-pass LLM step that compares script vs. generated panels and flags inconsistencies, then propose prompt tweaks or regeneration steps.    

### Things you should NOT do unless I ask

- Add cloud dependencies (OpenAI, Google, etc.) or send data off-machine.  
- Replace my local tools (ComfyUI, Kokoro TTS, AnimateDiff, etc.) with cloud SaaS unless I explicitly request it.      
- Massive repo-wide refactors without a clear plan and my approval.  
- Introduce complex infra (Kubernetes, full microservices) for this local project.

---
## Cost and tool selection policy

I want this project designed with a **free-first, local-first** mindset.

Rules for tool choices:
- Prefer **free, open-source, or locally runnable** tools by default.
- Only recommend **paid APIs, SaaS tools, or subscriptions** if there is a clear reason they outperform the free option for my exact use case.
- When suggesting a paid tool, always also list:
  - the best free/local alternative,
  - what I lose by staying free,
  - and when upgrading would actually make sense.

Decision priority:
1. Free and local
2. Low setup complexity
3. Good enough quality
4. Paid upgrade only if it gives a major improvement in speed, quality, reliability, or developer time

For this project, assume I want to start with:
- Local LLMs instead of paid model APIs
- ComfyUI / local open models instead of paid image services
- Local TTS if possible
- ffmpeg / open-source video assembly tools
- Minimal recurring cost unless I explicitly approve otherwise

When giving recommendations, present them in this format:
- Default free option
- Better paid option (only if justified)
- Why/when I should upgrade


## How to talk to me

Assume I’m a CS student comfortable with Python/Node, Docker, and VS Code. I want **production-grade, pragmatic code**, not toy examples, and I’m okay with reading non-trivial scripts as long as they’re well-structured.    

When you respond:

- Be concise but technical.  
- Show complete functions/scripts when it reduces back-and-forth.  
- Favor concrete file paths and commands I can paste into a VS Code terminal.

If anything in this file conflicts with the actual repo structure, **tell me explicitly** and propose a corrected structure plus the minimal changes needed.