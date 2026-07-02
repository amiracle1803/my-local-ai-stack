---
title: Background Job Queue
type: concept
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-background-runtime.md
  - wiki/concepts/agent-atlas-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Agent Atlas's async task queue using SQLite as the backing store with atomic BEGIN IMMEDIATE claims to prevent double-execution by concurrent workers.
---

# Background Job Queue

Agent Atlas uses a lightweight SQLite-backed job queue so tasks can run asynchronously without blocking the HTTP response. The queue supports multiple concurrent workers using SQLite's `BEGIN IMMEDIATE` transaction for atomic job claims.

## Job lifecycle

```
User submits task (run_mode="background")
         │
         ▼
status = "queued"  ← HTTP returns immediately
         │
         ▼  (worker polls every 2s)
status = "running" ← atomic claim via BEGIN IMMEDIATE
         │
         ├── success → status = "done",   result_json = {...}
         └── failure → status = "failed", error = "..."
```

Other possible statuses: `paused`, `stopped` (user-triggered via PATCH /api/jobs/{id}).

## Atomic worker claim (prevents double-execution)

```python
async def _claim_and_run_job(worker_id: int) -> bool:
    conn.execute("BEGIN IMMEDIATE")   # exclusive write lock
    row = conn.execute(
        "SELECT id, type, payload_json FROM jobs WHERE status='queued' LIMIT 1"
    ).fetchone()
    if not row:
        conn.execute("ROLLBACK")
        return False
    conn.execute("UPDATE jobs SET status='running' WHERE id=?", [row["id"]])
    conn.commit()
    # now execute safely — only this worker holds this job
    ...
```

`BEGIN IMMEDIATE` takes a write lock before reading. If two workers race, one gets the lock, reads the queued job, marks it running, and commits. The other gets the lock after the commit, finds no queued jobs, and backs off.

## Job routing

Each job type maps to a specific agent and message type:

```python
JOB_ROUTES = {
    "compose_task":  ("orchestrator",    "user_goal"),
    "research":      ("knowledge_hub",   "research_request"),
    "code":          ("code_agent",      "code_request"),
    "automation":    ("automation_agent","schedule"),
    "obsidian":      ("obsidian_brain",  "search"),
    "evaluate":      ("evaluator",       "evaluate_request"),
    "creative":      ("creative_studio", "create_doc"),
    "train":         ("local_trainer",   "prepare"),
    "deploy":        ("deployment_agent","status"),
}
```

## Jobs table schema

```sql
CREATE TABLE jobs (
    id          TEXT PRIMARY KEY,
    type        TEXT,
    title       TEXT,
    status      TEXT DEFAULT 'queued',  -- queued|running|done|failed|paused|stopped
    payload_json TEXT,
    result_json TEXT,
    progress    REAL DEFAULT 0.0,
    error       TEXT,
    notes       TEXT,
    created_at  TEXT,
    updated_at  TEXT
);
```

## Worker configuration

Default: 2 concurrent workers. Poll interval: 2 seconds. Timeout: 90 seconds per job (falls back to direct LLM if plan execution exceeds this).

Workers are started in `main.py` lifespan as asyncio background tasks. Each worker loops independently, claiming one job per iteration.
