---
title: Policy Engine
type: concept
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-guardian.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: The Guardian agent's rule evaluation system — YAML-defined policies (block/warn/allow) evaluated top-to-bottom before any destructive tool call.
---

# Policy Engine

The Policy Engine is owned by the [[entities/atlas-guardian]] agent. Every tool call that could have side effects passes through the engine before execution. Rules are declared in `config/policies.yml` and evaluated top-to-bottom; the first matching rule wins.

## Rule structure

```yaml
rules:
  - id: block_rm_rf
    match:
      tool: shell_exec
      args_contains: "rm -rf"
    decision: block
    reason: "Recursive deletion is permanently destructive."

  - id: block_sql_drop
    match:
      tool: db_execute
      args_contains: "DROP TABLE"
    decision: block
    reason: "Schema-dropping DDL requires manual approval."

  - id: warn_email_send
    match:
      tool: send_email
    decision: warn
    reason: "Email sends are visible externally — verify intent."

  - id: warn_external_http
    match:
      agent: code_agent
      tool: http_post
    decision: warn
    reason: "Code agent making outbound HTTP POST — check payload."

  - id: allow_file_read
    match:
      tool: file_read
    decision: allow

  - id: default_allow
    match: {}
    decision: allow
```

## Decisions

| Decision | Effect |
|---|---|
| `block` | Hard stop. Guardian returns error to caller. Never executes the tool. |
| `warn` | Logged as warning. Execution proceeds but is flagged in `/review`. |
| `allow` | Proceeds immediately. |

## Risk levels

Separate from policy rules, the task's `risk_level` field (set by the user in `/compose`) controls whether the task needs human review before the orchestrator even starts:

| Risk level | Review behavior |
|---|---|
| `low` | Auto-approve, execute immediately |
| `medium` | Log, execute, flag in review queue |
| `high` | Pause, require human approval in `/review` |
| `critical` | Block until explicit approval + reason logged |

## Integration with Action Hub

The Action Hub calls `bus.send(to="guardian", msg_type="policy_check", payload={tool, args, agent_id})` before every destructive tool invocation. The Guardian evaluates the rules and returns `{decision, reason}`. Only if `decision == "allow"` does Action Hub proceed.
