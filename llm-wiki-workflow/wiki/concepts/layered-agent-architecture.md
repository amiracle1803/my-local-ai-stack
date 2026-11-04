---
title: Layered Agent Architecture
type: concept
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/concepts/agent-atlas-architecture.md
  - wiki/concepts/collaboration-bus.md
  - wiki/entities/atlas-orchestrator.md
  - wiki/entities/atlas-knowledge-hub.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Agent Atlas organizes 18 agents into 4 functional layers — Control, Knowledge, Action, and Platform — each with distinct responsibilities and interaction patterns.
---

# Layered Agent Architecture

Agent Atlas uses a 4-layer architecture where agents at each layer have specific roles and typical communication patterns. Higher layers delegate to lower layers; platform agents support all layers.

## The 4 layers

### Layer 1: Control
**Who:** Orchestrator, Planner, Evaluator
**Responsibility:** Understand user intent, break it into a plan, coordinate execution, judge quality.
**Pattern:** Receives raw user goals → produces structured subtask DAGs → aggregates results.

```
User Goal
    │
    ▼
Orchestrator ──► Planner (returns JSON DAG)
    │
    ├── bus.send(to=knowledge_hub, ...)
    ├── bus.send(to=action_hub, ...)
    └── bus.send(to=evaluator, ...) ← optional scoring
```

### Layer 2: Knowledge
**Who:** Knowledge Hub, Memory Agent, Obsidian Brain, Retrieval Agent
**Responsibility:** Retrieve, synthesize, and store information. No direct side effects.
**Pattern:** Fan-out to multiple sources in parallel, return evidence packs.

```
Knowledge Hub
   │
   ├── async bus.send(to=retrieval_agent, ...) ← ChromaDB vector search
   └── async bus.send(to=obsidian_brain, ...)  ← Vault semantic search
       (both run in parallel via asyncio.gather)
```

### Layer 3: Action
**Who:** Action Hub, Code Agent, Automation Agent, Background Runtime
**Responsibility:** Produce real-world effects (write files, run code, schedule jobs). Policy-gated.
**Pattern:** All tool calls pass through Guardian before execution.

```
Action Hub
   │
   ├── bus.send(to=code_agent, ...)        ← generate + exec code
   ├── bus.send(to=automation_agent, ...)  ← schedule recurring tasks
   └── bus.send(to=guardian, ...)          ← policy check first
```

### Layer 4: Platform
**Who:** Creative Studio, Agent Factory, Guardian, Deployment, Observability, Local Model Trainer, Hermes Bridge
**Responsibility:** System-level capabilities. Support all other layers. Not called for typical tasks.

## Agent YAML definition format

Every agent is declared in `config/agents/{agent_id}.yml`:

```yaml
id: knowledge_hub
display_name: Knowledge Hub
layer: knowledge
description: Fan-out retrieval coordinator
model_preference:
  - hermes_local
  - groq_fast
inputs: [query, context]
outputs: [evidence_pack]
tools: [retrieval_agent.run, obsidian_brain.search]
memory_scopes: [episodic]
policies: [no_direct_side_effects]
system_prompt: |
  You coordinate knowledge retrieval...
```

The Python class at `agents/{agent_id}.py` implements `handle(message) → result`.

## Base agent contract

```python
class BaseAgent(ABC):
    async def handle(self, message: AgentMessage) -> Any:
        # Each agent implements this
        ...

    async def llm_call(self, prompt: str) -> str:
        # Auto-routes through ModelRouter
        client = await get_best_client(self.definition.model_preference)
        return await client.chat(messages)
```

All agents get `handle_traced()` for free from the base class — wraps `handle()` with automatic SQLite trace recording.
