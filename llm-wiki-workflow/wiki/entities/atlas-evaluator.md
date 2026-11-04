---
title: "Atlas: Evaluator Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-orchestrator.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Scores agent outputs on a 0-10 scale and requests retries when quality falls below threshold. No direct side effects — review only.
---

# Atlas: Evaluator Agent

**Layer:** Control | **ID:** `evaluator`

The Evaluator is the quality gate in Agent Atlas. It reviews the output of any agent execution and produces a structured score. If the score is below threshold, it sends a retry request back to the Orchestrator.

## Responsibilities

1. Receive a `(task, result)` pair from the Orchestrator
2. Score the result on accuracy, completeness, and relevance (0–10)
3. If score < threshold: return `retry_request` with specific feedback
4. If score ≥ threshold: pass with optional improvement notes

## Output format

```json
{
  "score": 8.5,
  "pass": true,
  "feedback": "Response is accurate but could add more concrete examples.",
  "retry_request": null
}
```

Or on failure:

```json
{
  "score": 3.0,
  "pass": false,
  "feedback": "Answer missed the main question about X.",
  "retry_request": {
    "agent": "knowledge_hub",
    "additional_context": "Focus specifically on X and Y."
  }
}
```

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `task`, `result`, `criteria` (optional) |
| **Outputs** | `score`, `pass`, `feedback`, `retry_request` |
| **Message type** | `evaluate_request` |

## Policy
No direct side effects. Never writes files, never calls external APIs. Review only.

## Connections
- Called by: [[entities/atlas-orchestrator]] (optional, adds latency)
- Can trigger: retry via Orchestrator → any knowledge or action agent
