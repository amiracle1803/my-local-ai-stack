---
title: Collaboration Bus
type: concept
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/concepts/agent-atlas-architecture.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: The async message-passing backbone of Agent Atlas — every agent-to-agent call is persisted, traced, and broadcast over WebSocket.
---

# Collaboration Bus

The Collaboration Bus is the central message-passing system in [[entities/agent-atlas-system]]. Every agent-to-agent interaction goes through it — no agent calls another agent's methods directly.

## Core API

```python
await bus.send_message(
    from_agent="orchestrator",
    to_agent="knowledge_hub",
    msg_type="research_request",
    payload={"query": "...", "context": {...}},
)
```

The bus:
1. Builds a `AgentMessage` with unique ID, conversation ID, timestamp
2. Persists it to the `messages` SQLite table
3. Looks up the registered handler for `to_agent`
4. Calls `handler(message)` as a direct async coroutine
5. Optionally broadcasts to all WebSocket clients if `user_visible=True`

## Message structure

```json
{
  "id": "msg_abc123",
  "conversation_id": "conv_xyz",
  "from_agent": "orchestrator",
  "to_agent": "knowledge_hub",
  "role": "agent",
  "type": "research_request",
  "payload": { ... },
  "created_at": "2026-06-23T14:32:11"
}
```

## Agent registration

At startup, `register_all_agents()` instantiates all 18 agents and calls `bus.register_handler(agent_id, agent.handle_traced)`. The `handle_traced` wrapper:
1. Calls the agent's `handle(message)` method
2. Records input/output/duration/model to `agent_traces` table
3. Returns the result

## Why a bus instead of direct calls?

- **Full audit trail** — every inter-agent call is in `messages` table, queryable anytime
- **Decoupling** — agents don't import each other, only the bus
- **WebSocket broadcast** — the Swarm View page shows live message flows
- **Swap agents** — register a new handler for an agent ID to replace it without touching callers

## Common message types

| Type | From | To | Purpose |
|---|---|---|---|
| `user_goal` | user / background_runtime | orchestrator | New task submission |
| `plan_request` | orchestrator | planner | Break goal into subtasks |
| `research_request` | orchestrator / knowledge_hub | retrieval_agent | Vector search |
| `obsidian_search` | knowledge_hub | obsidian_brain | Vault semantic search |
| `code_request` | action_hub | code_agent | Generate or edit code |
| `evaluate_request` | orchestrator | evaluator | Score a result |
| `policy_check` | action_hub | guardian | Check a tool call |
