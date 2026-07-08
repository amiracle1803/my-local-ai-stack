# Angelic Harness — Executive Architecture Overview

> Planning package for a local-first, offline-capable, multi-agent harness built on
> LangChain / LangGraph / Deep Agents. **Design only — no implementation in this package.**
>
> Package files: `00-overview.md` (this file), `01-walkthrough.md` (one task traced end-to-end),
> `agent.md`, `routing.md`, `handoff.md`, `memory.md`, `skills.md`, `systems-prompts.md`,
> `claude.md`, `todos.md`, `training.md`, `n8n.md`, `integration.md` (second brain, MCP,
> service topology), `improvement.md` (debugging + benchmark-gated switchover),
> `loop-engineering.md` (disciplines, canonical loop anatomy, guardrail stack).
> Companion application design: `../second-brain/DESIGN.md`.

---

## 1. What this is

A doctrine + specification set for an autonomous agent organization ("angelic agents") that:

- runs **entirely on this machine** (Windows 11, RTX 4070 Laptop 8 GB VRAM, 32 GB RAM),
- keeps working when the internet is off,
- separates **PLANNING** from **EXECUTION** as hard states,
- routes tasks to the best local model tier by default and escalates only via explicit policy,
- verifies before finalizing (critique → revise → score → verify),
- retrieves before generating,
- logs every failure into a learnable error memory,
- can (eventually, under governance) improve its own adapters via LoRA/QLoRA/DPO,
- emits n8n workflows when it detects automatable patterns.

## 2. Grounding in the existing repo (what already exists)

This design does **not** start from zero. It extends what is on disk today:

| Existing asset | Location | Role in the harness |
|---|---|---|
| Deep Agent Manager (LangGraph + `create_deep_agent`, manager → coding/research/writer/critic subagents, virtual FS `workspace/`, deep-agents-ui) | `deep-agent-manager/` | **Seed of the execution plane.** The harness grows out of this, not beside it. |
| Olympus kernel (FastAPI, scheduler, agent `.md` defs, role-based models in `olympus.toml`) | `olympus/` | Service plane: schedules, voice, pipeline engines, dashboard. |
| Model roles (`triage`/`worker`/`planner`/`verifier` → qwen2.5:3b / qwen2.5:7b / qwen3:8b; Ornith 9B) | `olympus/olympus.toml`, `deep-agent-manager/backend/.../config.py` | Already the "models are roles" pattern this design standardizes as **capability tiers**. |
| Hermes fallback LLM server (OpenAI-compatible, port 8642) | `olympus.toml [hermes]` | Existing fallback rung in the routing ladder. |
| n8n + API key bridge | `foundation/`, `olympus.toml [n8n]` | Target of the workflow-builder agent. |
| Langfuse (optional docker) | `foundation/docker-compose-langfuse.yml` | Observability backend. |
| SearXNG (local metasearch) | `foundation/searxng/` | Offline-friendly research tool. |
| LifeOS vault (`E:\LifeOS`) + Obsidian vault | `olympus.toml [paths]` | Second-brain integration surface for memory. |
| ComfyUI, Voice Studio (Kokoro/F5), manga pipeline | `E:\ComfyUI`, `olympus/engines/` | Non-LLM execution tools reachable via the tool router. |
| OpenCode MCP + skills | `olympus/skills/`, `.mcp.json` | Existing MCP tool surface. |

**Consequence:** the recommended route is *evolve `deep-agent-manager` into the harness control plane* and treat Olympus as the tool/service plane — not a third system.

## 3. Architecture at a glance

```
┌─────────────────────────── CONTROL PLANE (LangGraph) ───────────────────────────┐
│  Manager (supervisor)                                                           │
│    ├─ state machine: INTAKE → PLANNING ⇄ EXECUTION → VERIFICATION → DELIVERY    │
│    ├─ Planner        (writes plan.md + todos; never executes)                   │
│    ├─ Model Router   (tier selection per task node; see routing.md)             │
│    ├─ Tool Router    (MCP / local tool selection)                               │
│    └─ Subagent pool  (scoped contexts, handoff contracts; see handoff.md)       │
│         advisor · researcher · retriever · coder · executor · workflow-builder  │
│         critic · scorer · verifier · memory-curator · training-orchestrator     │
│         offline-ops steward                                                     │
├─────────────────────────── STATE PLANE (filesystem) ────────────────────────────┤
│  runs/<task-id>/  plan/  artifacts/  reports/  scores/  logs/                   │
│  memory/  (episodic, semantic, procedural, error)  + Qdrant vectors             │
│  skills/  (progressive-loading skill packs)                                     │
│  registry/ (agents.yaml, models.yaml, adapters.yaml, tools.yaml)                │
├─────────────────────────── EXECUTION PLANE (local runtimes) ────────────────────┤
│  Ollama (primary) · llama.cpp server (pinned GGUFs) · Hermes fallback           │
│  whisper.cpp · ComfyUI / sd.cpp · Kokoro TTS · ffmpeg · n8n · Crawl4AI/SearXNG  │
│  Qdrant · local embeddings/reranker · Unsloth (training box, offline)           │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Three planes, deliberately decoupled:

1. **Control plane** — LangGraph graphs; owns state machines, routing, verification gates. Model-agnostic: every model call goes through a `ModelPort` interface (routing.md §7).
2. **State plane** — plain files + one vector DB. Everything auditable with a text editor. Planning artifacts and execution artifacts live in **separate directories, never mixed**.
3. **Execution plane** — swappable local runtimes. Any runtime can be replaced by editing a registry entry, never code.

## 4. Design goals (ranked) and the constraint that shapes everything

Goals, in priority order: **(1)** local-first, **(2)** offline resilience, **(3)** modularity, **(4)** swappable models, **(5)** reproducible behavior, **(6)** strong verification, **(7)** long-horizon planning, **(8)** safe self-improvement, **(9)** low context waste, **(10)** consistent handoffs.

The dominant physical constraint is **8 GB VRAM**. It dictates:

- Capability tiers top out locally around **14B Q4 GGUF** (partially CPU-offloaded); the routine workhorses are 7–9B.
- Only **one large model resident at a time** → the router must serialize tier-2 work and prefer keep-alive reuse over model churn.
- KV-cache quantization (q8_0/q4_0), context budgeting (default `num_ctx` 8–16k), and retrieval-first (send 2k of the *right* tokens, not 16k of everything) are not optimizations, they are requirements. See memory.md §8 and routing.md §5.
- Training = **QLoRA via Unsloth on ≤8B models**, nothing bigger. See training.md.

## 5. Honest capability labels

Used throughout the package:

- **Practical now** — buildable this month with existing tools on this machine.
- **Near-term experimental** — plausible in 1–2 quarters; needs eval harness first.
- **Research-grade / speculative** — direction, not commitment; gated behind governance.

Headline placement:

| Capability | Label |
|---|---|
| Manager + subagents + handoffs + file state (LangGraph/Deep Agents) | Practical now |
| PLANNING/EXECUTION state machine, verification gates, scoring rubrics | Practical now |
| Tiered model routing with fallback ladder (Ollama → llama.cpp → Hermes) | Practical now |
| Retrieval-first memory (Qdrant + local embeddings + error ledger) | Practical now |
| n8n workflow synthesis with human approval gate | Practical now |
| Human-triggered QLoRA/DPO pipeline with eval-gated promotion | Near-term experimental |
| Agents *proposing* their own training runs (human approves) | Near-term experimental |
| Agents *executing* their own adapter training end-to-end | Research-grade / speculative |
| Unsupervised recursive self-improvement | Out of scope by doctrine (todos.md red-team section) |

## 6. Repository / folder blueprint

Target layout (new pieces marked ●; existing pieces retained in place):

```
my-local-ai-stack/
├── harness/                          ● the angelic harness (grows from deep-agent-manager)
│   ├── graphs/                       ● LangGraph graph definitions (manager, planner, verifier loops)
│   ├── agents/                       ● agent definitions: <name>.agent.yaml + <name>.prompt.md
│   ├── ports/                        ● interface adapters: model_port, tool_port, memory_port
│   ├── registry/                     ● agents.yaml, models.yaml, tools.yaml, adapters.yaml, skills.yaml
│   ├── skills/                       ● skill packs (see skills.md)
│   ├── memory/                       ● filesystem memory root (see memory.md §4 for tree)
│   ├── runs/                         ● per-task state: runs/<task-id>/{plan,artifacts,reports,scores,logs}
│   ├── schemas/                      ● JSON Schemas: task, handoff, scorecard, adapter-card
│   ├── evals/                        ● golden tasks, regression suites, scorer configs
│   └── training/                     ● dataset staging, adapter workdirs, promotion queue (see training.md)
├── deep-agent-manager/               (existing — absorbed into harness/ during V1)
├── olympus/                          (existing — service plane, unchanged)
├── foundation/                       (existing — docker: n8n, langfuse, searxng, + qdrant service ●)
├── docs/planning/angelic-harness/    ● this package
└── ...
```

**Naming conventions**

- Task IDs: `T-YYYYMMDD-<slug>-<4hex>` (e.g. `T-20260707-wiki-index-a3f1`). Run dirs are named by task ID.
- Agents: lowercase-kebab role names (`memory-curator`), one YAML + one prompt file each.
- Models in registries: kebab-case `family-size[-quant]@runtime` (e.g. `qwen2.5-7b@ollama`, `qwen2.5-14b-q4@llamacpp`); the runtime's own tag (Ollama's `qwen2.5:7b`) appears only in the entry's `model:` field. Roles (tiers) map to model IDs; code references **roles only**.
- Adapters: `<base-model>__<skill>__vN` (e.g. `qwen2.5-7b__json-planner__v3`).
- Artifacts: `artifacts/<step>-<name>.<ext>`; reports: `reports/<kind>-<step>.md` (e.g. `critique-04.md`, `evidence-04.md`); scores: `scores/scorecard-<step>.json` and `scores/verdict-<step>.json`; every artifact hashed in `manifest.json`.
- Memory files: dated, typed prefixes — `epi-`, `sem-`, `proc-`, `err-` (memory.md §4).
- Planning outputs live only in `runs/<id>/plan/`; execution outputs only in `runs/<id>/artifacts/`. **A file may never move between them; executors reference plans read-only.**

## 7. Core state schemas (canonical, JSON Schema in `harness/schemas/`)

**Task record** (`runs/<id>/task.json`):

```json
{
  "id": "T-20260707-wiki-index-a3f1",
  "goal": "…user goal verbatim…",
  "state": "PLANNING",
  "class": {"domain": "coding", "difficulty": "hard", "risk": "low", "offline_ok": true},
  "route": {"tier": "T2", "model": "qwen3-8b@ollama", "fallbacks": ["qwen2.5-14b-q4@llamacpp", "hermes"]},
  "budget": {"max_loops": 3, "max_tokens": 200000, "max_wall_minutes": 45},
  "plan_ref": "plan/plan.md",
  "verification": {"required_score": 0.8, "verifier": "verifier", "status": "pending"},
  "parent": null, "children": [],
  "created": "2026-07-07T12:00:00Z", "updated": null
}
```

Handoff payload → handoff.md §3. Scorecard → handoff.md §7 / routing.md §9. Adapter card → training.md §6. Agent registry entry → agent.md §5.

## 8. Design tradeoffs and alternative routes

### Recommended: Route A — LangGraph control plane over existing services

Evolve `deep-agent-manager` into `harness/`; Olympus stays the service/scheduler plane; all models behind a `ModelPort`.

- **Pros:** builds on working code; Deep Agents already gives todo tracking, virtual FS, subagent delegation; clean plane separation; every layer swappable.
- **Cons:** two Python processes to keep healthy (harness + Olympus); LangGraph adds a framework dependency and its upgrade churn; some duplication of scheduling concerns until V2 consolidation.

### Alternative: Route B — Deep Agents monolith

One `create_deep_agent` process owns everything (planning, routing, memory, n8n) as tools; no separate graphs.

- **Pros:** simplest to ship; least code; single context of truth; the current `deep-agent-manager` is already 60 % of it.
- **Cons:** planning/execution separation becomes prompt-enforced instead of state-machine-enforced (drift risk); routing and verification live inside one model's judgment; poor failure isolation — one bad loop stalls everything; hard to run planner and executor on *different* models, which is the whole point of tiering on 8 GB VRAM.

### Alternative: Route C — n8n-centric orchestration

n8n is the spine; LLM calls are n8n nodes; agents are workflows; LangGraph only for the inner reasoning loops.

- **Pros:** visual audit of every flow; retry/queue semantics for free; workflow-builder agent becomes self-hosting; non-Python surface for automations.
- **Cons:** n8n is a workflow engine, not an agent runtime — scoped context windows, recursive critique loops, and file-memory doctrine map badly onto nodes; state lives in n8n's DB (opaque vs. the file doctrine); heavier Docker dependency for the *core* rather than the edge.

**Verdict:** A for the organism, C's ideas at the edges (n8n owns recurring/side-effect automations, per n8n.md), B as the degraded mode — if the harness is down, the plain deep-agent-manager still runs.

### Other notable tradeoffs

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| Vector store | Qdrant (docker, local) | Chroma/FAISS embedded | payload filters, snapshots for offline backup, already in optional compose; FAISS kept as zero-dep fallback |
| Model server | Ollama primary, llama.cpp pinned secondary | vLLM | vLLM is server-class/Linux-first; on 8 GB laptop GGUF + Ollama wins. vLLM re-enters only if a desktop GPU box is added |
| API shape | OpenAI-compatible everywhere (Ollama, llama.cpp, Hermes all speak it) | bespoke clients | one `ModelPort`, N backends; LiteLLM optional as a router shim, not required |
| Prompt optimization | DSPy offline, compile-time only | DSPy in the runtime loop | reproducibility: runtime prompts are frozen artifacts; DSPy output is reviewed and versioned like code |
| State | Files + git-style manifests | DB-first | auditability, offline diffing, "text editor is the debugger" |

## 9. Reading order

1. `agent.md` — the constitution (planes, taxonomy, state machine, lifecycle, failure domains); then `01-walkthrough.md` — one task traced end-to-end through every rule.
2. `routing.md` + `handoff.md` — how work moves; `loop-engineering.md` — the canonical loop every part of the system runs.
3. `memory.md` + `skills.md` — what the organization knows; `integration.md` — how it reaches the second brain, MCP servers, and local services.
4. `systems-prompts.md` — the voice of each agent.
5. `claude.md` — where Claude (Fable) fits and where it must not.
6. `n8n.md`, `training.md` — the two governed side-effect pipelines; `improvement.md` — debugging protocols and benchmark-gated switchover for every change class.
7. `todos.md` — the phased path from today's repo to V3.
