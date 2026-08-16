---
title: "Atlas: Guardian Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-action-hub.md
  - wiki/concepts/policy-engine.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: The policy enforcement agent — evaluates every destructive tool call against config/policies.yml rules and returns block/warn/allow decisions before execution.
---

# Atlas: Guardian Agent

**Layer:** Platform | **ID:** `guardian`

Guardian is the security and safety layer for Agent Atlas. It evaluates every action request against a declarative YAML policy file before the Action Hub executes any tool with side effects.

## How it's called

Action Hub calls Guardian before every destructive operation:

```python
policy_result = await bus.send_message(
    from_agent="action_hub",
    to_agent="guardian",
    msg_type="policy_check",
    payload={
        "tool": "shell_exec",
        "args": "rm -rf /tmp/old_cache",
        "agent_id": "code_agent"
    }
)
# Returns: {"decision": "block", "reason": "Recursive deletion is destructive."}
```

## Policy evaluation

Rules in `config/policies.yml` are evaluated top-to-bottom. First match wins.

Match fields available: `tool`, `agent_id`, `args_contains`, `args_regex`.
Decisions: `block`, `warn`, `allow`.

See [[concepts/policy-engine]] for full rule format and examples.

## Risk level integration

Guardian also enforces risk-level gating:
- `high` risk tasks: pauses execution, routes to `/review` for human approval
- `critical` risk tasks: hard blocks until explicit human approval + reason

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `tool`, `args`, `agent_id`, `risk_level` |
| **Outputs** | `decision` (block/warn/allow), `reason`, `review_required` |
| **Message type** | `policy_check` |

## Design principle
Guardian has no LLM component — all decisions are deterministic rule evaluation. This makes it fast and auditable. LLM judgment is deliberately excluded from safety-critical path.
