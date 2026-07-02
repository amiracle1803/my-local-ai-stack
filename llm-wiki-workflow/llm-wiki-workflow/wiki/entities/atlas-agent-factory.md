---
title: "Atlas: Agent Factory"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/concepts/layered-agent-architecture.md
  - wiki/concepts/collaboration-bus.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Dynamically creates new agents at runtime via the /factory web UI or POST /api/agents/factory — writes YAML config and registers with the collaboration bus without restarting.
---

# Atlas: Agent Factory

**Layer:** Platform | **ID:** `agent_factory`

The Agent Factory allows new specialized agents to be created at runtime — no restart required. Agents are defined via a form in the `/factory` web UI page or via the API, and are immediately available on the collaboration bus.

## What you can configure

| Field | Description |
|---|---|
| `id` | Unique agent identifier (slug) |
| `display_name` | Human-readable name |
| `layer` | `control`, `knowledge`, `action`, or `platform` |
| `description` | What this agent does |
| `model_preference` | Ordered list of preferred models |
| `tools` | List of tool names this agent can use |
| `memory_scopes` | `profile`, `project`, `episodic` |
| `policies` | Policy names from `policies.yml` |
| `system_prompt` | The agent's core behavior prompt |

## Creation flow

```
POST /api/agents/factory
    │
    ├── Validate definition
    ├── Write config/agents/{id}.yml
    ├── Instantiate DynamicAgent(definition)
    └── bus.register_handler(id, agent.handle_traced)
         (agent is now callable via bus.send_message(to_agent=id))
```

## Use cases

- Rapid prototyping of new agent behaviors
- Domain-specific agents (e.g., `legal_reviewer`, `sql_optimizer`)
- Temporary agents for a specific project
- Experimenting with different system prompts

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | Full agent definition JSON |
| **Outputs** | `agent_id`, `registered: true`, `endpoint` |
| **Message type** | `factory_create` |

## API endpoint
`POST /api/agents/factory` — also accessible from the `/factory` page in the web UI.
