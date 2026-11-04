---
title: Model Router
type: concept
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/entities/atlas-hermes-bridge.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Agent Atlas auto-discovers available LLMs (local-first) and routes each agent to the best available model based on declared preferences and live probe results.
---

# Model Router

The Model Router gives every agent access to the best available LLM without hardcoding an endpoint. It probes local services on startup and caches results for 45 seconds, re-probing on failure.

## Priority order (default)

```
1. ollama_local      → http://127.0.0.1:11434   (fastest, fully local)
2. lmstudio_local    → http://127.0.0.1:1234    (local GUI, OpenAI-compat)
3. groq_powerful     → Groq API (llama-3.3-70b) (cloud, free tier)
4. groq_fast         → Groq API (llama-3.1-8b)  (cloud, fastest)
5. claude            → Anthropic API             (most capable)
```

Each agent declares a `model_preference` list in its YAML. The router picks the highest-priority model from that list that is currently available.

## Probe logic

```python
async def _probe(model_name: str) -> bool:
    config = get_model(model_name)
    if config.provider == "local":
        r = await httpx.get(f"{config.endpoint}/models", timeout=3.0)
        models = r.json().get("data", [])
        return any(config.model in m["id"] for m in models)
    elif config.provider == "groq":
        return bool(os.getenv("GROQ_API_KEY"))
    elif config.provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
```

The probe for local models hits `/models` and checks whether the configured model is actually loaded — not just that the server is running.

## Model config (`config/models.yml`)

```yaml
models:
  ollama_local:
    provider: local
    endpoint: http://127.0.0.1:11434/v1/chat/completions
    model: gemma2:9b
    capabilities: [general, coding, reasoning, cheap, fast]
    max_tokens: 4096

  lmstudio_local:
    provider: local
    endpoint: http://127.0.0.1:1234/v1/chat/completions
    model: meta-llama-3.1-8b-instruct
    capabilities: [general, fast]

  groq_powerful:
    provider: groq
    api_key_env: GROQ_API_KEY
    model: llama-3.3-70b-versatile
    capabilities: [general, reasoning, cloud]

routing:
  discovery_order: [ollama_local, lmstudio_local, groq_powerful, groq_fast]
```

## Hermes Bridge

The [[entities/atlas-hermes-bridge]] agent extends the router by auto-detecting which models are currently loaded in Ollama and LM Studio, registering them dynamically without requiring manual config updates. This makes model switching seamless — start a different model in Ollama and the router picks it up automatically.

## Cache behavior

- Cache TTL: 45 seconds
- On probe failure: immediately invalidate, try next in list
- Multiple agents can share the same client instance (connection pooling via httpx)

## LLM client abstraction

All model implementations share the same interface:
```python
class ModelClient(ABC):
    async def chat(self, messages: List[Dict], **kwargs) -> Dict[str, str]:
        return {"content": "..."}
```
Clients: `OllamaClient`, `LMStudioClient`, `GroqClient`, `ClaudeClient`, `PerplexityClient`.
