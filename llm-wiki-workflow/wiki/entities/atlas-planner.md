---
title: "Atlas: Planner Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-orchestrator.md
  - wiki/concepts/layered-agent-architecture.md
  - wiki/concepts/collaboration-bus.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Breaks complex user goals into a JSON subtask DAG with agent assignments and dependency ordering.
---

# Atlas: Planner Agent

**Layer:** Control | **ID:** `planner`

The Planner receives a user goal from the Orchestrator and returns a structured execution plan as a JSON DAG. Each node in the DAG is a subtask assigned to a specific agent, with optional `depends_on` references that force sequential execution.

## Responsibilities

1. Analyze the goal and identify all required subtasks
2. Assign each subtask to the best-suited agent
3. Model dependencies between subtasks
4. Return a JSON plan the Orchestrator can execute

## Plan format

```json
{
  "subtasks": [
    {
      "id": "1",
      "description": "Search knowledge base for relevant context",
      "agent": "knowledge_hub",
      "depends_on": []
    },
    {
      "id": "2",
      "description": "Write Python script to process the data",
      "agent": "code_agent",
      "depends_on": ["1"]
    },
    {
      "id": "3",
      "description": "Evaluate code output quality",
      "agent": "evaluator",
      "depends_on": ["2"]
    }
  ]
}
```

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `goal`, `context` |
| **Outputs** | JSON subtask DAG |
| **Message type** | `plan_request` |

## System prompt style
"Break the goal into the minimum set of subtasks needed. Each subtask must have a clear description, the best agent for it, and any subtask IDs it depends on. Return JSON only — no prose."

## Model preference
`hermes_local` → `groq_powerful`

## Connections
- Called by: [[entities/atlas-orchestrator]]
- Plan is executed by: [[entities/atlas-orchestrator]] dispatching to all layer 2/3 agents
