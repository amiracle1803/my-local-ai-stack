---
title: Agent Atlas Architecture
type: concept
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/concepts/collaboration-bus.md
  - wiki/concepts/layered-agent-architecture.md
  - wiki/concepts/model-router.md
  - wiki/concepts/policy-engine.md
  - wiki/concepts/background-job-queue.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Full system design of Agent Atlas — how tasks flow from web UI through 18 agents to Obsidian memory.
---

# Agent Atlas Architecture

Agent Atlas is built around three core design principles: **local-first** (prefer local models over cloud), **persistent memory** (everything goes to Obsidian + SQLite), and **traceable execution** (every agent call is logged with input/output/timing).

## End-to-end request flow (sync mode)

```
User submits goal via /compose page
         │
         ▼
POST /api/run { goal, risk_level, context }
         │
         ▼
Create Job record (status = running)
         │
         ▼
Collaboration Bus → Orchestrator
         │
         ├── trivial goal? → direct LLM call → return
         │
         └── complex goal?
              │
              ▼
           Planner Agent
              │  returns JSON subtask DAG
              ▼
         Orchestrator executes plan
           (respects depends_on, parallel where possible)
           │
           ├── bus.send(to=knowledge_hub, ...)
           ├── bus.send(to=code_agent, ...)
           └── bus.send(to=action_hub, ...)
                    │
                    ▼
             Evaluator scores results
                    │
                    ▼
         _save_to_obsidian(goal, response, route)
                    │
                    ▼
         _finish_job(job_id, "done", result)
                    │
                    ▼
HTTP 200 RunResponse + WebSocket broadcast
```

## Background mode (async)

```
POST /api/run { run_mode: "background" }
         │
         ▼
Create Job (status = queued)
HTTP 200 "Task queued..."
         │
         ▼ [async]
Background Workers (2 workers, poll every 2s)
         │
         ├── BEGIN IMMEDIATE  (atomic SQLite claim)
         ├── SELECT job WHERE status='queued'
         ├── UPDATE status='running'
         └── dispatch to agent via bus
```

## Agent communication

All inter-agent calls go through the **Collaboration Bus** (see [[concepts/collaboration-bus]]). Every message is:
1. Built with unique IDs and timestamps
2. Persisted to `messages` SQLite table
3. Dispatched as a direct async coroutine call
4. Broadcast to WebSocket clients if `user_visible=True`

## Memory architecture (3 layers)

| Layer | Storage | Lifespan | Used for |
|---|---|---|---|
| Working memory | In-request context dict | Single request | Subtask results |
| Short-term | SQLite episodes | Days–weeks | Session summaries |
| Long-term | SQLite profile + Obsidian | Permanent | User facts, preferences |

## Security model

**Guardian Agent** sits between Action Hub and all destructive tools. It evaluates every tool call against `config/policies.yml` rules (top-to-bottom, first match wins):
- `block` — hard stop, return error
- `warn` — log and ask for review
- `allow` — proceed

High-risk submissions go through the `/review` page for manual human approval before execution.

## Technology stack

- **Backend:** FastAPI + uvicorn + SQLite + ChromaDB
- **Frontend:** React + Zustand + WebSocket
- **LLMs:** Ollama / LM Studio (local) or Groq / Claude (cloud)
- **Embeddings:** nomic-embed-text-v1.5 via LM Studio
- **Memory:** Obsidian vault + SQLite
- **Protocol:** MCP (SSE) for Claude Desktop / VS Code integration
