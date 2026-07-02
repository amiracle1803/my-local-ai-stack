---
title: "Atlas: Orchestrator Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-planner.md
  - wiki/entities/atlas-evaluator.md
  - wiki/concepts/collaboration-bus.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Control layer entrypoint — classifies user goals as trivial or complex, coordinates the full execution plan, and aggregates results from all delegated agents.
---

# Atlas: Orchestrator Agent

**Layer:** Control | **ID:** `orchestrator`

The Orchestrator is the first agent to receive every user request. It decides whether a goal is simple enough for a direct LLM call or requires full multi-agent orchestration.

## Responsibilities

1. **Classify** — determine if goal is trivial (direct LLM) or complex (multi-agent plan)
2. **Load context** — pull relevant memory from Memory Agent and Obsidian Brain
3. **Delegate to Planner** — get a JSON subtask DAG for complex goals
4. **Execute plan** — dispatch subtasks to appropriate agents (respects `depends_on`)
5. **Aggregate results** — merge outputs into a final coherent response
6. **Save to Obsidian** — append the run to `Atlas/Sessions/YYYY-MM-DD.md`
7. **Finish job** — mark job `done` in SQLite

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `user_goal`, `permissions`, `context_snapshot` |
| **Outputs** | `task_graph`, `branch_assignments`, `final_response` |
| **Message type** | `user_goal` |

## Key logic

```python
async def _classify(goal: str) -> str:
    # LLM call: "Is this goal trivial or multi-agent? Reply one word."
    return "trivial" | "multi-agent"

async def _execute_plan(plan: dict, context: dict):
    for subtask in plan["subtasks"]:
        if all(dep in completed for dep in subtask["depends_on"]):
            result = await bus.send_message(
                from_agent="orchestrator",
                to_agent=subtask["agent"],
                msg_type=infer_msg_type(subtask),
                payload=subtask,
            )
            completed[subtask["id"]] = result
```

## Model preference
`hermes_local` → `groq_powerful` → `claude`

## Timeout
90 seconds for full plan execution. Falls back to direct LLM call if exceeded.

## Connections
- Delegates to: [[entities/atlas-planner]], [[entities/atlas-knowledge-hub]], [[entities/atlas-action-hub]], [[entities/atlas-evaluator]]
- Called by: User via `/api/run`, [[entities/atlas-background-runtime]]
