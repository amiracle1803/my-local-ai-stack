---
title: Agent Atlas System
type: entity
sources: []
related:
  - wiki/concepts/agent-atlas-architecture.md
  - wiki/concepts/collaboration-bus.md
  - wiki/concepts/layered-agent-architecture.md
  - wiki/concepts/model-router.md
  - wiki/concepts/policy-engine.md
  - wiki/concepts/background-job-queue.md
  - wiki/entities/atlas-orchestrator.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Local-first multi-agent AI system with 18 specialized agents, FastAPI backend, React web UI, and Obsidian memory integration.
---

# Agent Atlas System

**Agent Atlas** is a local-first multi-agent AI system built around a collaboration bus architecture. It runs 18 specialized agents across 4 layers that collectively collect user goals, break them into subtasks, execute those tasks using the best available LLM, and store results in Obsidian as persistent memory.

## System components

| Component | Location | Purpose |
|---|---|---|
| FastAPI backend | `agent-atlas/backend/` | REST API, WebSocket, SQLite, agent registry |
| React frontend | `agent-atlas/frontend/` | Web UI with dashboard, task compose, swarm view |
| SQLite database | `agent-atlas/data/db/agent_atlas.sqlite` | Jobs, messages, traces, memory, metrics |
| ChromaDB | (in-memory or persistent) | Vector embeddings for semantic search |
| Obsidian vault | `Documents/Obsidian Vault/` | Long-term memory and knowledge indexing |
| Config YAMLs | `agent-atlas/config/` | Agent definitions, model routing, policies |

## Web UI pages

| Route | Page | What you do here |
|---|---|---|
| `/` | Dashboard | System health, live activity feed, failed tasks |
| `/compose` | Compose | Submit tasks with risk level and templates |
| `/tasks` | Task List | All jobs with filtering |
| `/tasks/:id` | Task Detail | Execution trace, logs, errors |
| `/review` | Review Center | Approve high-risk actions manually |
| `/swarm` | Swarm View | Live agent-to-agent message visualization |
| `/agents` | Agent Tree | View all 18 agents and their layer |
| `/logs` | Logs | Agent call counts, latency, metrics |
| `/factory` | Factory | Create new agents dynamically at runtime |
| `/settings` | Settings | API keys, Obsidian path, model selection |

## API surface

- `POST /api/run` — submit a goal (sync or background)
- `GET /api/health` — system status
- `GET /api/agents/` — list agents
- `GET/POST /api/jobs/` — job management
- `POST /api/obsidian/search` — semantic search vault
- `WS /ws` — live activity WebSocket
- `SSE /mcp/sse` — MCP server for Claude Desktop / VS Code

## The 18 agents

### Control layer
- [[entities/atlas-orchestrator]] — entrypoint, classifies goals, delegates
- [[entities/atlas-planner]] — breaks goals into subtask DAGs
- [[entities/atlas-evaluator]] — scores results, requests retries

### Knowledge layer
- [[entities/atlas-knowledge-hub]] — fan-out to retrieval + Obsidian
- [[entities/atlas-memory-agent]] — SQLite memory (profile, episodes, projects)
- [[entities/atlas-obsidian-brain]] — semantic search + write to vault
- [[entities/atlas-retrieval-agent]] — ChromaDB vector search

### Action layer
- [[entities/atlas-action-hub]] — routes actions to code/automation
- [[entities/atlas-code-agent]] — LLM code generation + file execution
- [[entities/atlas-automation-agent]] — scheduled/recurring tasks
- [[entities/atlas-background-runtime]] — multi-worker async job executor

### Platform layer
- [[entities/atlas-creative-studio]] — document generation
- [[entities/atlas-agent-factory]] — create new agents at runtime
- [[entities/atlas-guardian]] — policy engine (block/warn/allow rules)
- [[entities/atlas-deployment-agent]] — deployment status and rollback
- [[entities/atlas-observability-agent]] — metrics collection and analysis
- [[entities/atlas-local-model-trainer]] — fine-tuning on local data
- [[entities/atlas-hermes-bridge]] — auto-detects Ollama / LM Studio

## Database tables

| Table | Purpose |
|---|---|
| `jobs` | Task queue (queued → running → done/failed) |
| `messages` | Full audit trail of every bus message |
| `agent_traces` | Per-agent call log with input/output/duration |
| `memory_profile` | Long-term user facts (key/value) |
| `memory_projects` | Per-project context |
| `memory_episodes` | Session summaries mirrored to Obsidian |
| `metrics` | Performance counters per agent |
| `obsidian_notes` | Vault index (MD5 dedup, tags, links) |

## Obsidian integration

Every completed task appends to `Atlas/Sessions/YYYY-MM-DD.md`. Memory facts go to `Atlas/Profile/{category}.md`. Project context goes to `Atlas/Projects/{id}.md`. This wiki syncs to `Atlas/Knowledge/` so Obsidian Brain can index it.

## Model routing

Agent Atlas auto-discovers available LLMs in this priority order:
1. Ollama (localhost:11434)
2. LM Studio (localhost:1234)
3. Groq cloud (fast, free tier)
4. Claude (Anthropic API)

See [[concepts/model-router]] for probe logic and caching.
