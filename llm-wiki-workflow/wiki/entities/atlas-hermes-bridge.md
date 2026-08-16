---
title: "Atlas: Hermes Bridge Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/concepts/model-router.md
  - wiki/entities/local-llm-runtimes.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Auto-detects and registers locally running LLM servers (Ollama, LM Studio) so the Model Router always knows what models are currently available without manual configuration.
---

# Atlas: Hermes Bridge Agent

**Layer:** Platform | **ID:** `hermes_bridge`

The Hermes Bridge is the auto-discovery layer for local LLM runtimes. It probes Ollama and LM Studio endpoints, registers available models with the [[concepts/model-router]], and maintains a live inventory of what's loaded. Named "Hermes" after the Hermes-2 family of local models optimized for agentic tasks.

## How it works

```python
async def _detect_ollama():
    r = await httpx.get("http://127.0.0.1:11434/api/tags", timeout=3.0)
    models = r.json().get("models", [])
    for m in models:
        router.register_model(name=m["name"], endpoint="ollama_local")

async def _detect_lmstudio():
    r = await httpx.get("http://127.0.0.1:1234/v1/models", timeout=3.0)
    models = r.json().get("data", [])
    for m in models:
        router.register_model(name=m["id"], endpoint="lmstudio_local")
```

Runs on startup and can be re-triggered via the `/settings` page or `POST /api/system/provider-health`.

## What it enables

- **Zero config model switching** — switch the model in Ollama without touching any config file; Hermes Bridge re-detects and the router picks it up automatically
- **Live model inventory** — the `/settings` page shows which models are currently loaded
- **Fallback awareness** — tells the router which local models are down so it can route to cloud

## Probe frequency

- On startup (always)
- On explicit `/api/system/provider-health` call
- Cache TTL: 45 seconds (shared with Model Router cache)

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `operation` (detect/status/register) |
| **Outputs** | List of `{model_id, endpoint, available}` |
| **Message type** | `detect_models` |

## Connections
- Probes: Ollama (localhost:11434), LM Studio (localhost:1234)
- Updates: [[concepts/model-router]] model registry
- Referenced by: [[entities/local-llm-runtimes]]
