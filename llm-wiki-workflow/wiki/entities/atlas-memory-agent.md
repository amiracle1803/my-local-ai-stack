---
title: "Atlas: Memory Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-obsidian-brain.md
  - wiki/entities/obsidian.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Manages three scopes of memory (profile, project, episodic) in SQLite and mirrors all writes to the Obsidian vault automatically.
---

# Atlas: Memory Agent

**Layer:** Knowledge | **ID:** `memory_agent`

The Memory Agent is the persistent memory system for Agent Atlas. It stores structured facts about the user, per-project context, and session summaries — all in SQLite with automatic mirroring to Obsidian.

## Memory scopes

| Scope | SQLite table | Obsidian path | Content |
|---|---|---|---|
| `profile` | `memory_profile` | `Atlas/Profile/{category}.md` | Long-term user facts (style prefs, skills, goals) |
| `project` | `memory_projects` | `Atlas/Projects/{project_id}.md` | Context for ongoing projects |
| `episodic` | `memory_episodes` | `Atlas/Sessions/YYYY-MM-DD.md` | Session summaries (what was done, decisions made) |

## Operations

```python
# Save a user fact
await memory_agent.save_profile(key="preferences/tone", value="concise and technical")

# Get context for a conversation
context = await memory_agent.get_context(
    project_id="proj_abc",
    include_profile=True,
    include_recent_episodes=5
)

# Save a session episode
await memory_agent.save_episode(
    project_id="proj_abc",
    summary="Implemented async job queue. Decided to use BEGIN IMMEDIATE for atomicity."
)
```

## Obsidian mirror

Every write to SQLite automatically creates or updates the corresponding Obsidian file. This means:
- Obsidian Brain can semantic-search all memory
- The user can browse/edit memory directly in Obsidian
- Memory persists across Agent Atlas restarts

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | operation (`save_episode`/`get_profile`/`save_fact`/`get_context`), payload |
| **Outputs** | Requested memory data or confirmation |
| **Message type** | `memory_request` |

## Connections
- Called by: [[entities/atlas-orchestrator]], all agents that declare `memory_scopes` in their YAML
- Mirrors to: [[entities/obsidian]] vault via [[entities/atlas-obsidian-brain]]
