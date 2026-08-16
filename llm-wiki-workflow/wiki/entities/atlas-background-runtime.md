---
title: "Atlas: Background Runtime Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/concepts/background-job-queue.md
  - wiki/concepts/collaboration-bus.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Multi-worker async job executor — polls the SQLite job queue using atomic BEGIN IMMEDIATE claims to dispatch queued tasks to the correct agent without double-execution.
---

# Atlas: Background Runtime Agent

**Layer:** Action | **ID:** `background_runtime`

The Background Runtime is the async execution engine. It runs as multiple concurrent workers (default: 2) that poll the `jobs` SQLite table, atomically claim queued tasks, and dispatch them to the appropriate agent via the collaboration bus.

## How it works

See [[concepts/background-job-queue]] for full details on the SQLite BEGIN IMMEDIATE atomic claim pattern.

```python
# Worker loop (runs every 2s)
async def _worker_loop(worker_id: int):
    while True:
        claimed = await _claim_and_run_job(worker_id)
        if not claimed:
            await asyncio.sleep(2)
```

## Job routing table

| Job type | Dispatched to | Message type |
|---|---|---|
| `compose_task` | orchestrator | `user_goal` |
| `research` | knowledge_hub | `research_request` |
| `code` | code_agent | `code_request` |
| `automation` | automation_agent | `schedule` |
| `obsidian` | obsidian_brain | `search` |
| `evaluate` | evaluator | `evaluate_request` |
| `creative` | creative_studio | `create_doc` |
| `train` | local_model_trainer | `prepare` |
| `deploy` | deployment_agent | `status` |

## Inputs / Outputs

- **Input:** Polls `jobs` table directly (not via bus message — it IS the queue consumer)
- **Output:** Writes `result_json` and updates `status` to `done` or `failed`

## Connections
- Dispatches to: All agents depending on job type
- Monitors: SQLite `jobs` table
- Entry point for: All background-mode (`run_mode="background"`) API requests
