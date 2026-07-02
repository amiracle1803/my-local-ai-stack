---
title: "Atlas: Automation Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-action-hub.md
  - wiki/entities/atlas-background-runtime.md
  - wiki/concepts/background-job-queue.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Creates and manages scheduled and recurring tasks. Writes automation scripts and enqueues them as background jobs.
---

# Atlas: Automation Agent

**Layer:** Action | **ID:** `automation_agent`

The Automation Agent creates tasks that run on a schedule or trigger. It can write automation scripts, register them in the job queue, and configure recurrence — enabling Agent Atlas to work autonomously on long-running or periodic tasks.

## Capabilities

- **Schedule one-off tasks** — run at a specific datetime
- **Recurring tasks** — cron-style interval execution
- **Automation scripts** — generate Python/shell scripts for the background workers to run
- **Manage schedules** — list, pause, resume, delete scheduled jobs

## Job types it creates

```python
# Schedule a research task for tomorrow morning
await automation_agent.schedule({
    "type": "research",
    "payload": {"query": "Latest papers on vector databases"},
    "run_at": "2026-06-24T08:00:00",
    "recurrence": "daily"
})
```

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `task_description`, `schedule` (datetime or cron), `recurrence` |
| **Outputs** | `job_id`, `scheduled_at`, `confirmation` |
| **Message type** | `schedule` |

## Connections
- Called by: [[entities/atlas-action-hub]]
- Enqueues to: [[entities/atlas-background-runtime]] job queue
