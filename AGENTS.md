# AGENTS.md — Local AI Stack builder rules

This file is the agent build playbook for the Local AI Stack. It defines how
agents (Claude, OpenCode, or any builder) should interact with this project.

> The human-facing description of the stack (setup, services, pipeline usage,
> model tables, troubleshooting) lives in `README.md`. This file covers only
> working rules for agents. If the two ever conflict, `README.md` and the
> code win — update this file.

## Architecture

```
stack.toml          ← Single source of truth (all services, models, ports, paths)
stack/config.py     ← Typed config loader (pydantic v2)
olympus/kernel/     ← Olympus kernel (:4600 FastAPI) — the central hub
olympus/engines/    ← Pipeline engine, Voice Studio
olympus/web/        ← Dashboard UI (single-page, vanilla HTML/JS/CSS)
ComfyUI/            ← Image/animation generation (external, port 8188)
```

## Pipeline stages

Stage order (source of truth: `pipeline/blueprint.py STAGE_ORDER`):

```
stage0 → stage0_dossier → stage1 → stage1_world → stage3 → stage2 → stage4
       → stage1r → stage3b → stage3c → stage_vlm_review → stage5
```

Storyboard-first: stage 3 turns the intake scenes into shot direction and
composition, stage 2 times narration/dialogue to those shot durations, and
stage 4 renders the timed audio spine. stage3b/3c only generate visuals for
the already-fixed shots. The Studio cards (`olympus/web/app.js STAGE_META`)
render in this same order.

- **stage0_dossier** (intake enrichment): reads the finished `input/script.txt`
  (read-only) and extracts `intake/dossier.json` — rich character profiles
  (appearance, race, age, height, gender, family, relationships, skills),
  location **360-views**, per-scene setting facts (time/season/environment),
  and a verbatim dialogue log (speaker → addressee → body movement). The world
  bible, screenplay, and storyboard stages consume it.
- **On-model consistency loop**: `Character.appearance_spec()` is the canonical
  appearance. stage3b's `vision_judge` (extract-then-compare) and
  `stage_vlm_review` check panels/clips against it;
  `pipeline/consistency_report.py` aggregates mismatches into
  `consistency/consistency_report.json` with proposed fixes (the self-critique
  loop from the original spec).

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
- **Touch only named files.** Don't drive-by refactor, reformat, or "clean up"
  files outside the stated scope.
- **Verify before calling anything done.** Import the module, run the
  relevant test, or smoke-test the endpoint.
- **No git for builders.** Ever. Leave commits to the manager.

### Artifact naming rules (VFX identity standard — enforced going forward)

Canonical names come from `pipeline/identity.py: canonical_name()`; every
*new* artifact follows the pattern
`{project}_sc{scene:03d}_sh{shot:03d}_{asset}[_{variant}][_tk##]_v###.{ext}`.
The internal machine id (`sh-001-01` = scene 001 + shot 01) is the
JSON-contract / cache / storyboard key and is **never renamed** once
downstream stages reference it — `identity.legacy_stem()` resolves the legacy
`sh_001_01` filename form. Rules:

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
- **ComfyUI venv**: `~/Downloads/ComfyUI/.venv`, PyTorch 2.6.0+cu124 pinned.
  (`~/Downloads/ComfyUI` is a symlink to `~/Documents/Personal projects/ComfyUI` —
  fix the symlink, not the paths, if it moves again.)
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
| n8n plane | 5679 | docker compose (`~/n8n-stack`, see `[automation]` in stack.toml) | Compose project |
| SGW proxy | 8787 | `sgw-proxy.service` | User unit (paced ShopGoodwill relay for n8n) |
| Stack dashboard | 8790 | `stack-dashboard.service` | User unit (read-only repo+status UI, `~/bin/stack-dashboard.py`) |

## GPU scheduling

RTX 4070 8GB VRAM. Ollama and ComfyUI must NEVER run GPU work
simultaneously — they will OOM each other. Rules:

1. **LLM work**: ComfyUI must be idle (unload models).
2. **Image/video work**: Unload all Ollama models before queuing ComfyUI.
3. **Kernel agents** use `llama3.2:3b` (triage) by default to coexist with
   ComfyUI. Heavy pipeline stages use `qwen3:8b` when ComfyUI is idle.
4. Pipeline GPU work goes through `GpuBatch` (`pipeline/gpu_lock.py`):
   file lease → unload Ollama → ComfyUI work → free VRAM → release.

Enforced ban list (runtime, `pipeline/comfy_client.py`):
`z-anime-distill-4step-fp8`, `wai-illustrious-v110`, `NoobAI-XL-v1.1`,
`animagine-xl-4.0`, `FLUX.1-Krea-dev`.

## Image / video models

Reality check against the live ComfyUI install
(`~/Downloads/ComfyUI`) — change models in `stack.toml`, never hard-code in
stage code:

| Model | Role | State |
|-------|------|-------|
| flux-2-klein-4b-Q4_K_M | Panels (832×512) | Installed, validated default |
| svd_xt.safetensors | Short clips when animation enabled | Installed |
| animation as a whole | `[animation] enabled = false` (panels/Ken Burns default) | Opt-in |
| krea2_turbo-* / LTX 2.3 22B | Superseded sizes for 8 GB | NOT installed; OOMs here (see `docs/planning/comfyui-rebuild-log.md`) |

`llama-server.service` (llama.cpp) survives to squat ~4 GB VRAM while
`stack.toml [llamacpp] enabled = false` — stop and disable it before heavy
ComfyUI or Ollama work.

## Where things live

- Config: `stack.toml` → `stack/config.py`
- Kernel: `olympus/kernel/app.py`
- Pipeline: `olympus/engines/pipeline/`
- Voice: `olympus/engines/voice/`
- Dashboard: `olympus/web/index.html`
- Docs: `docs/` (incl. `docs/n8n-automation.md` — n8n plane contract)
- n8n plane: `stack.toml [automation]` → compose project at `~/n8n-stack` (NOT moved into repo); see `docs/n8n-automation.md` before touching n8n workflows
- AGENTS.md: This file.
- DeepSeek Harness: `harness-deepseek/` (local clone of `deepseek-ai/deepseek-harness` v0.1, 80M) + `~/Documents/harness` (second copy)
- Git history: `git log --oneline`; `origin` at `github.com/amiracle1803/my-local-ai-stack`
- Superseded pre-2026-08-21 README history: `docs/planning/README-superseded-2026-08-21.md`

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

The harness can "see" all changes via `git log` and GitHub remote; append-only log design means history is immutable and reconstructible — aligns with DeepSeek's "never edit past history" rule.

## Coding style & preferences

- Languages: **Python first**, Node/TypeScript second for web frontend.
- Small, composable functions; pure where possible.
- Explicit, typed data models (pydantic) over loose dicts.
- Clear, pragmatic docstrings; minimal comments where code is self-explanatory.
- No "god scripts"; modular steps (parse → generate → assemble).
- Add at least minimal unit tests for core steps.

## Obsidian vault skills

The Obsidian vault is the shared second brain for this stack. When a task
involves creating or editing vault content, read the matching skill file
first instead of guessing Obsidian syntax
(`~/.opencode/skills/obsidian-skills/skills/`):

- `obsidian-cli` — drive a running Obsidian instance via the CLI
- `obsidian-markdown` — wikilinks, embeds, callouts, frontmatter, tags
- `obsidian-bases` — `.base` file schema (filters, formulas, views)
- `json-canvas` — `.canvas` file schema (nodes/edges/groups)
- `defuddle` — clean-markdown extraction from web pages (prefer over raw fetch)

## Behavioral guidelines (reduce common LLM coding mistakes)

These bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think before coding

Before implementing: state assumptions explicitly; if multiple
interpretations exist, present them — don't pick silently. If something is
unclear, stop, name what's confusing, and ask.

### 2. Simplicity first

Minimum code that solves the problem. No features beyond what was asked, no
abstractions for single-use code, no unrequested configurability, no error
handling for impossible scenarios. If 200 lines could be 50, rewrite it.

### 3. Surgical changes

Touch only what you must. Match existing style, don't "improve" adjacent
code, don't refactor what isn't broken. If you notice unrelated dead code,
mention it — don't delete it. Every changed line should trace directly to
the user's request.

### 4. Goal-driven execution

Transform tasks into verifiable goals ("fix the bug" → "write a test that
reproduces it, then make it pass") and loop until verified. For multi-step
tasks, state a brief plan with a verification check per step.

## Working agreement (from the original project brief — codified)

- Propose a short plan (1–5 steps) before editing; for multi-file changes,
  say which files change and why.
- Prefer minimal, targeted patches over broad rewrites; don't rewrite large
  files just to "clean them up".
- Before introducing a new dependency, explain why it's needed.
- Don't replace working local tooling unless asked.

### Do NOT do unless asked

- Add cloud dependencies (OpenAI, Google, etc.) or send data off-machine.
- Replace local tools (ComfyUI, Kokoro TTS, etc.) with cloud SaaS.
- Repo-wide refactors without a plan and approval.
- Complex infra (Kubernetes, full microservices) for this local project.

## Cost and tool selection policy

Free-first, local-first. Decision priority: (1) free and local, (2) low
setup complexity, (3) good-enough quality, (4) paid only for a major win.
When recommending a paid tool, always also give: the best free/local
alternative, what is lost by staying free, and when upgrading is justified.

## How to talk back

Assume a CS student comfortable with Python/Node, Docker, and VS Code.
Be concise but technical; show complete functions/scripts when it reduces
back-and-forth; favor concrete file paths and paste-able commands.

If anything in this file conflicts with the actual repo structure, **say so
explicitly** and propose a corrected structure plus the minimal changes.
