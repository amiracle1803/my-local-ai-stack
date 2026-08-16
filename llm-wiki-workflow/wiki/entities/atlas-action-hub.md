---
title: "Atlas: Action Hub Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-code-agent.md
  - wiki/entities/atlas-automation-agent.md
  - wiki/entities/atlas-guardian.md
  - wiki/concepts/policy-engine.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Routes action requests to Code Agent or Automation Agent, with mandatory Guardian policy check before any destructive operation.
---

# Atlas: Action Hub Agent

**Layer:** Action | **ID:** `action_hub`

The Action Hub is the single entry point for all side-effecting operations — anything that writes files, runs code, calls external APIs, or schedules tasks. All calls pass through the Guardian policy engine before execution.

## Responsibilities

1. Receive an action request from the Orchestrator
2. **Policy check first** — call Guardian before any tool execution
3. Route to Code Agent, Automation Agent, or other action handlers
4. Return results to caller

## Policy gate pattern

```python
async def handle(self, message):
    tool = message.payload["tool"]
    args = message.payload["args"]

    # Always check Guardian first
    policy = await bus.send_message(
        from_agent="action_hub",
        to_agent="guardian",
        msg_type="policy_check",
        payload={"tool": tool, "args": args, "agent_id": message.from_agent}
    )

    if policy["decision"] == "block":
        return {"error": f"Blocked by policy: {policy['reason']}"}

    # Route to appropriate agent
    if tool in CODE_TOOLS:
        return await bus.send_message(to_agent="code_agent", ...)
    elif tool in AUTOMATION_TOOLS:
        return await bus.send_message(to_agent="automation_agent", ...)
```

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `tool`, `args`, `context` |
| **Outputs** | Tool execution result or blocked error |
| **Message type** | `action_request` |

## Connections
- Calls before executing: [[entities/atlas-guardian]] (mandatory)
- Delegates to: [[entities/atlas-code-agent]], [[entities/atlas-automation-agent]]
- Called by: [[entities/atlas-orchestrator]]
