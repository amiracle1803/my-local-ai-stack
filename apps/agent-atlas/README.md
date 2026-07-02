# Agent Atlas

A **local-first, free-to-run multi-agent system** with a collaborative agent mesh, autonomous background execution, hybrid model routing, Obsidian brain integration, and a React web UI control plane.

---

## Quick Start

### 1. Clone & copy env

```bash
cp .env.example .env
# Edit .env — add API keys only if you want remote models
```

### 2. Backend

```bash
cd backend
py -3 -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend runs at **http://localhost:8000**. API docs at **http://localhost:8000/docs**.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at **http://localhost:5173**.

### 4. Or use the dev script

**Windows:**
```powershell
.\scripts\dev.ps1
```
**Linux/WSL:**
```bash
bash scripts/dev.sh
```

---

## Configuration

### Model Config (`config/models.yml`)

Edit to change endpoints, add models, or set API key env var names.

| Model | Provider | Default endpoint |
|-------|----------|-----------------|
| `hermes_local` | local | `http://localhost:11434/v1/chat/completions` |
| `claude_pro` | claude | Anthropic API |
| `perplexity_pro` | perplexity | Perplexity API |
| `local_specialist_fallback` | local | `http://localhost:11435/v1/chat/completions` |

### Hermes / Ollama

Make sure Ollama is running and your model is pulled:

```bash
ollama serve
ollama pull hermes-2  # or whatever model you prefer
```

Then test:

```bash
curl http://localhost:8000/llm/test
```

### Claude (optional)

```env
CLAUDE_API_KEY=sk-ant-...
```

### Perplexity (optional)

```env
PERPLEXITY_API_KEY=pplx-...
```

### Obsidian Brain (optional)

```env
OBSIDIAN_VAULT_PATH=/home/USER/Obsidian/MainVault
```

Trigger indexing:

```bash
curl -X POST http://localhost:8000/obsidian/index
```

### Local-Only Mode

```env
LOCAL_ONLY=true
```

All remote model and search calls are disabled. Only Hermes (or any local OpenAI-compatible endpoint) is used.

---

## Architecture

Four layers, 17+ agents:

```
Control:   Orchestrator → Planner → Evaluator (+ Collaboration Bus)
Knowledge: Knowledge Hub → Memory Agent, Obsidian Brain, Retrieval Agent
Action:    Action Hub → Code Agent, Automation Agent, Background Runtime
Platform:  Creative Studio, Agent Factory, Model Router, Guardian,
           Deployment Agent, Observability Agent, Local Trainer
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System health + loaded counts |
| POST | `/run` | Send a goal to the Orchestrator |
| GET | `/agents/` | List all agent definitions |
| POST | `/agents/factory` | Create a new agent (Agent Factory) |
| GET | `/jobs/` | List all jobs |
| POST | `/jobs/` | Create a new job |
| POST | `/jobs/{id}/pause` | Pause a job |
| POST | `/jobs/{id}/resume` | Resume a paused job |
| POST | `/jobs/{id}/stop` | Stop a job |
| GET | `/llm/models` | List models + availability |
| GET | `/llm/test` | Smoke-test Hermes endpoint |
| POST | `/llm/chat` | Direct chat with any model |
| GET | `/obsidian/notes` | List indexed notes |
| POST | `/obsidian/search` | Semantic search notes |
| POST | `/obsidian/index` | Re-index the vault |
| GET | `/metrics/agents` | Agent call counts + latency |
| GET | `/metrics/models` | Model usage stats |

---

## Tests

```bash
cd backend
.venv/Scripts/activate   # or source .venv/bin/activate
pytest
```

18 tests covering: ModelRouter, Collaboration Bus, Job Queue, and the full FastAPI HTTP layer.

---

## Adding a New Agent

**Via UI:** Go to `http://localhost:5173/factory`, fill in the form, click Create.

**Via API:**

```bash
curl -X POST http://localhost:8000/agents/factory \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "my_agent",
    "display_name": "My Agent",
    "layer": "action",
    "description": "Does something useful",
    "tools": [],
    "model_preference": ["hermes_local"],
    "memory_scopes": ["project"],
    "policies": [],
    "system_prompt": "You are my custom agent."
  }'
```

**Via file:** Drop a `config/agents/my_agent.yml` following the existing agent YAML format.

---

## Implementation Phases

- [x] Phase 1 — Repo scaffold, FastAPI, SQLite, all 17 agents, config system
- [x] Phase 2 — ModelClient abstraction + `/run` endpoint + trace recording
- [x] Phase 3 — Observability metrics API (`/metrics/agents`, `/metrics/models`, `/metrics/errors`)
- [x] Phase 4 — ChromaDB vector store + Obsidian indexer (semantic + keyword hybrid search)
- [x] Phase 5 — Background worker auto-start + job type routing (research/code/obsidian/…)
- [x] Phase 6 — Claude + Perplexity clients (set `CLAUDE_API_KEY` / `PERPLEXITY_API_KEY` in `.env`)
- [x] Phase 7 — Guardian YAML policy engine (`config/policies.yml`), block/warn/allow rules
- [x] Phase 9 — WebSocket `/ws` for real-time events + Chat UI page with live activity sidebar
- [x] Tests — 24 passing (ModelRouter, Bus, Job Queue, HTTP API, Policy Engine)
- [ ] Phase 8 — Fine-tune CLI (dataset export ready; training pipeline hookup is manual)
- [ ] Hermes/Ollama — install Ollama and pull a model to enable local LLM calls (see below)
