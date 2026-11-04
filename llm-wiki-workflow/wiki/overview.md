---
title: LLM Wiki — Agent Atlas Knowledge Layer
type: overview
sources:
  - raw/articles/karpathy-llm-wiki-complete-guide.md
  - raw/articles/build-this-workflow-notes.md
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/concepts/agent-atlas-architecture.md
  - wiki/concepts/collaboration-bus.md
  - wiki/concepts/layered-agent-architecture.md
  - wiki/concepts/model-router.md
  - wiki/concepts/policy-engine.md
  - wiki/concepts/background-job-queue.md
  - wiki/entities/obsidian.md
  - wiki/entities/local-llm-runtimes.md
  - wiki/comparisons/wiki-vs-rag.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
---

# LLM Wiki — Agent Atlas Knowledge Layer

This wiki is the **structured knowledge base and memory framework** for [[entities/agent-atlas-system]] — a local-first multi-agent AI system with 18 specialized agents, a FastAPI backend, and a React web UI for collecting, delegating, and running tasks.

The wiki pages sync to `Atlas/Knowledge/` inside the Obsidian vault. Agent Atlas's [[entities/atlas-obsidian-brain]] agent indexes that folder and makes every page here searchable by all 18 agents. When you ingest a raw source, that knowledge becomes immediately available to the full Agent Atlas pipeline.

## How the two systems connect

```text
LLM Wiki (this repo)          Agent Atlas (localhost:8000)
─────────────────────         ────────────────────────────
raw/  ──ingest──► wiki/       Web UI: collect + delegate tasks
                    │                        │
          obsidian_sync.py            18 agents (4 layers)
                    │                        │
                    ▼                        ▼
         Atlas/Knowledge/  ◄──── Obsidian Brain indexes ────
         (in Obsidian vault)
```

## The Agent Atlas pipeline

**18 agents across 4 layers:**

**Control** — [[entities/atlas-orchestrator]] (entrypoint, delegates), [[entities/atlas-planner]] (subtask DAGs), [[entities/atlas-evaluator]] (scores results)

**Knowledge** — [[entities/atlas-knowledge-hub]] (fan-out retrieval), [[entities/atlas-memory-agent]] (SQLite + Obsidian memory), [[entities/atlas-obsidian-brain]] (vault search + write), [[entities/atlas-retrieval-agent]] (ChromaDB vector search)

**Action** — [[entities/atlas-action-hub]] (policy-gated routing), [[entities/atlas-code-agent]] (generate + exec code), [[entities/atlas-automation-agent]] (scheduled tasks), [[entities/atlas-background-runtime]] (async job workers)

**Platform** — [[entities/atlas-creative-studio]], [[entities/atlas-agent-factory]], [[entities/atlas-guardian]], [[entities/atlas-deployment-agent]], [[entities/atlas-observability-agent]], [[entities/atlas-local-model-trainer]], [[entities/atlas-hermes-bridge]]

## Key architectural concepts

- [[concepts/agent-atlas-architecture]] — full request flow (sync + background modes)
- [[concepts/collaboration-bus]] — how agents message each other with full audit trail
- [[concepts/layered-agent-architecture]] — the 4-layer pattern and agent YAML format
- [[concepts/model-router]] — local-first LLM auto-discovery (Ollama → LM Studio → Groq → Claude)
- [[concepts/policy-engine]] — Guardian agent YAML rule evaluation (block/warn/allow)
- [[concepts/background-job-queue]] — SQLite-backed async workers with atomic BEGIN IMMEDIATE claims

## How to use this wiki

**Add knowledge for Agent Atlas to use:**

```bash
agent-cli ingest raw/articles/my-research.md
python tools/obsidian_sync.py          # push to Atlas/Knowledge/
python tools/atlas_bridge.py reindex   # tell Atlas to re-index
```

**Submit a task to Agent Atlas:**

```bash
python tools/atlas_bridge.py run "Summarize what you know about vector databases"
python tools/atlas_bridge.py status
python tools/atlas_bridge.py jobs
```

**Browse the wiki:**

```bash
server.bat  # http://localhost:7337  ->  /atlas for Agent Atlas status
```

**Query across the knowledge base:**

```bash
agent-cli query "Which agent handles file operations?"
agent-cli query "How does the policy engine work?" --save
```

## Wiki foundations

This wiki system is built on the [[concepts/llm-wiki-workflow]] pattern from [[entities/andrej-karpathy]]. The core insight: instead of re-deriving knowledge from raw sources on every query (like [[concepts/retrieval-augmented-generation]]), compile it once into structured wiki pages and keep them current. See [[comparisons/wiki-vs-rag]] for the full trade-off analysis.

The [[concepts/idea-file]] and [[concepts/memex]] pages trace the intellectual history back to Vannevar Bush's 1945 vision for associative personal knowledge — now finally achievable with local LLMs and [[entities/obsidian]].
