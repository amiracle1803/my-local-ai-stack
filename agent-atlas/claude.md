Below is a detailed markdown spec you can drop into VS Code and feed to Claude as a “build this system” prompt.

***

# Agent Atlas – Local‑First Multi‑Agent System Design Spec

Design and implement a **local‑first, free‑to‑run multi‑agent system** (“Agent Atlas”) with:

- A **collaborative agent mesh** (agents can talk to each other and work together on the same task).
- **Autonomous background execution** (jobs keep running until done or explicitly stopped via a web UI).
- **Hybrid model routing** between:
  - Local **Hermes** (primary, private default).
  - **Claude Pro** (premium reasoning / coding / writing).
  - **Perplexity Pro** (live search / research).
  - **Self‑trained local fallback models** in case paid services disappear.
- An **Obsidian-based “integrated brain”** for long‑term knowledge, projects, and workflows.
- A browser **control plane web UI** (tree view, jobs, controls, new‑agent creation).
- Everything **as free and local as possible**, especially data storage and sensitive processing. External APIs are optional add‑ons; the system must remain functional in “local only” mode.

The starting architecture comes from an existing interactive HTML diagram (“AI Agents Architecture Atlas”), which you should treat as the visual/structural reference for the tree of agents, branches, and runtime concepts.

***

## 1. How you (Claude) should use this spec

You are to treat this document as a **detailed design + build plan**, not a question.

When responding:

1. **Respect constraints first**  
   - Assume the user wants **free, local‑first, self‑hostable** components wherever possible.
   - Paid services (Claude, Perplexity) are **optional plugins**, not hard dependencies.

2. **Work in phases**  
   Implement the system in clear, incremental phases (detailed in Section 11), **not all at once**, and:
   - Show **directory structure**.
   - Provide **actual code** for each component (backend, frontend, config).
   - Maintain a **single repository structure** with clear separation of concerns.

3. **Explain before code**  
   For each phase, give:
   - Short explanation of what you’re about to implement.
   - Then the code (files, functions, configs).
   - Then notes on how to run / test that phase.

4. **Never require paid infrastructure**  
   - Use free/open‑source tools; no managed DBs, no paid queues, no paid hosted services.
   - Only the **LLM providers** (Claude / Perplexity) are allowed as paid, optional *APIs*.

5. **Keep data local**  
   - All user data, logs, traces, Obsidian notes, embeddings, and model artifacts must live on the user’s machine (or LAN), not in third‑party clouds.

***

## 2. User environment and hardware assumptions

Assume the user is a **student developer** running on:

- **OS / Dev Stack**
  - Windows 11 with **WSL2/Ubuntu** for dev/runtime.
  - VS Code as primary editor.
  - Git + GitHub for version control.
  - Docker & Docker Compose available.

- **Programming skills**
  - Comfortable with **Python**, **JavaScript/TypeScript**, HTML/CSS, Bash/PowerShell.
  - Familiar with Docker, local AI models, and CLI workflows.

- **Example hardware (edit as needed)**
  - CPU: 8‑core (or better).
  - RAM: 32 GB (aim to be usable at 16 GB too).
  - GPU: single consumer GPU, e.g., 10–16 GB VRAM (e.g., 3060/4060/4070‑class).
  - Storage: at least 1 TB SSD, with:
    - `~/data/agent-atlas/` for DBs, models, logs.
    - `~/Obsidian/` for vaults.

**Requirement:**  
Design everything so it still works on a **single‑GPU or even CPU‑only** setup (just slower). Avoid design choices that require multi‑GPU or exotic hardware.

***

## 3. Hard constraints and design principles

Claude, you **must** satisfy these:

### 3.1 Local‑first, free stack

- All core components (backend, frontend, DB, queues, vector store, logging) must be:
  - Free.
  - Self‑hosted on the user’s machine (or local LAN).
- Acceptable building blocks (examples):
  - Backend: Python (**FastAPI** or **Litestar**).
  - Frontend: **React** or **SvelteKit** with Vite.
  - DB: local **SQLite** (start) with an option to upgrade to local Postgres.
  - Queue: simple **SQLite-backed job table** or local **Redis**.
  - Vector store: **FAISS**, **ChromaDB**, or **SQLite + embeddings**.
  - Obsidian integration: direct file access in a local folder, no cloud sync requirements.

### 3.2 Hybrid model routing

- Models:
  - Local **Hermes** (via e.g. Ollama / LM Studio / text-generation-webui / llama.cpp HTTP endpoint).
  - **Claude Pro** via official API (or OpenRouter, depending on what user uses).
  - **Perplexity Pro** via API for research/search.
  - Local fallback models trained via:
    - Fine‑tuning or adapters (LoRA/QLoRA) on local data.
- The **Model Router** component:
  - Must support configuration like:

    ```yaml
    models:
      hermes_local:
        provider: local
        endpoint: http://localhost:11434/v1/chat/completions
        capabilities: [general, private, cheap]
      claude_pro:
        provider: claude
        api_key_env: CLAUDE_API_KEY
        capabilities: [deep_reasoning, coding, complex_writing]
      perplexity_pro:
        provider: perplexity
        api_key_env: PERPLEXITY_API_KEY
        capabilities: [web_research, up_to_date]
      local_specialist_fallback:
        provider: local
        endpoint: http://localhost:11435/v1/chat/completions
        capabilities: [specialist, fallback]
    ```

  - Must choose routes based on:
    - **privacy** (local only).
    - **difficulty** (simple vs deep reasoning).
    - **freshness** requirements (needs live web vs static).
    - **cost** (paid tokens vs free local).
    - **availability** (what’s online).

### 3.3 Data locality and privacy

- All data (except what *must* be sent to remote models) stays local:
  - Agent traces, logs, embeddings.
  - Obsidian vault contents.
  - Training data for local fallback models.
- Provide clear **config switches**:
  - `allow_remote_models: true/false`
  - `allow_remote_search: true/false`
  - `log_remote_payloads: true/false`

### 3.4 Extensibility via config

- Agents, tools, and model routes must be defined in **config files**:
  - YAML or JSON in `config/agents/` and `config/models.yml`.
- New agents must be creatable either:
  - From config files, or
  - Through the **Agent Factory** UI, which writes those configs.

***

## 4. High‑level architecture

Refer to the HTML diagram as the canonical layout of this architecture.

### 4.1 Layers

Organize the system into four layers:

1. **Control / Coordination Layer**
   - Executive Orchestrator
   - Planner Agent
   - Evaluator Agent
   - Collaboration Bus (inter‑agent communication)

2. **Knowledge / Brain Layer**
   - Knowledge Hub
   - Memory Agent
   - Obsidian Brain
   - Retrieval Agent (vector & keyword)

3. **Action / Execution Layer**
   - Action Hub (tool execution)
   - Code Agent
   - Automation Agent
   - Background Runtime (job queue / scheduler)

4. **Platform / Governance Layer**
   - Creative Studio Agent
   - Agent Factory (new agent creator)
   - Model Router
   - Local Model Trainer
   - Guardian Agent (policy/safety)
   - Deployment Agent
   - Observability Agent

### 4.2 Major processes

- **Simple question**: Orchestrator → Model Router → Hermes local (fast reply) OR Perplexity (research) → return via Evaluator.
- **Complex project**: Orchestrator → Planner → multiple branch assignments:
  - Knowledge Hub + Retrieval + Obsidian Brain for research.
  - Code Agent for implementation.
  - Automation Agent for background tasks.
  - Creative Studio for visuals / docs.
  - Evaluator → Orchestrator for merge.
- **Background job**: Orchestrator → Planner → Action Hub → Background Runtime queue → long‑running tasks until completion or stop via web UI.

***

## 5. Agents and responsibilities

Claude, implement explicit **agent definitions** as data structures and classes. Example schema:

```ts
type AgentDefinition = {
  id: string;                 // e.g. "orchestrator"
  displayName: string;
  layer: "control" | "knowledge" | "action" | "platform";
  description: string;
  inputs: string[];
  outputs: string[];
  tools: string[];            // named tool ids
  modelPreference: string[];  // e.g. ["hermes_local", "claude_pro"]
  memoryScopes: string[];     // e.g. ["profile", "project", "obsidian", "short_term"]
  policies: string[];         // guardian policies that apply
};
```

Implement at least the following agents according to the HTML diagram:

- **Control**
  - `orchestrator`
  - `planner`
  - `evaluator`
  - `collaboration_bus`

- **Knowledge**
  - `knowledge_hub`
  - `memory_agent`
  - `obsidian_brain`
  - `retrieval_agent`

- **Action**
  - `action_hub`
  - `code_agent`
  - `automation_agent`
  - `background_runtime`

- **Platform**
  - `creative_studio_agent`
  - `agent_factory`
  - `model_router`
  - `local_model_trainer`
  - `guardian_agent`
  - `deployment_agent`
  - `observability_agent`

Each agent should have:

- A **handler function** on the backend (e.g. `run_orchestrator(payload)`).
- A **contract** (input/output schema).
- A **default prompt template** (for LLM‑driven parts).
- A **tool list** (function‑calling or RPC endpoints it can use).

***

## 6. Inter‑agent communication and collaboration bus

### 6.1 Message schema

Use a **JSON message schema** for inter‑agent communication:

```json
{
  "message_id": "uuid",
  "conversation_id": "uuid",
  "from_agent": "orchestrator",
  "to_agent": "knowledge_hub",
  "role": "request" | "response" | "event",
  "type": "research_request",
  "payload": { "goal": "...", "context": {...} },
  "created_at": "ISO8601",
  "metadata": {
    "priority": "low|normal|high",
    "runtime_mode": "sync|async|background",
    "user_visible": false
  }
}
```

### 6.2 Collaboration Bus

Implement a **Collaboration Bus** module:

- Responsibilities:
  - Route messages between agents.
  - Maintain **per‑task “rooms”** (multi‑agent collaboration sessions).
  - Support **parallel tasks** (fan‑out to multiple agents).
  - Provide **hooks for Observability** (log messages, durations, errors).

- Implementation:
  - Start with **in‑process Python** in Phase 1:
    - A simple router function with dispatch based on `to_agent`.
  - In a later phase, add:
    - Persistent message log in SQLite.
    - Background workers pulling from a `messages` table or queue.

### 6.3 Multi‑agent collaboration patterns

Support patterns like:

- **Research swarm**
  - Orchestrator spawns a room.
  - Knowledge Hub asks Perplexity + Retrieval + Obsidian Brain in parallel.
  - Evaluator merges their outputs into a single evidence pack.

- **Coding with critic**
  - Orchestrator assigns Code Agent to implement.
  - Evaluator acts as critic, suggesting fixes.
  - Code Agent and Evaluator exchange messages via Collaboration Bus until code passes tests.

***

## 7. Hybrid model strategy and connectors

### 7.1 General LLM abstraction

Define a **ModelClient** abstraction:

```python
class ModelClient(Protocol):
    async def chat(self, messages: list[dict], **kwargs) -> dict:
        ...
```

Where `messages` follow OpenAI‑style format:

```json
[{ "role": "system", "content": "..." }, { "role": "user", "content": "..." }]
```

### 7.2 Hermes local connector (primary)

- Assume Hermes is exposed at a local HTTP endpoint compatible with OpenAI or text‑generation.
- Create a `HermesLocalClient` that:
  - Reads endpoint and model name from env/config.
  - Supports streaming and non‑streaming.
  - Has configurable max tokens, temperature, etc.

### 7.3 Claude Pro connector

- Create a `ClaudeClient` that:
  - Reads `CLAUDE_API_KEY` from environment.
  - Wraps the official Claude API.
  - Is used primarily by:
    - Orchestrator.
    - Planner.
    - Evaluator.
    - Code Agent.

### 7.4 Perplexity Pro connector

- Create a `PerplexityClient` for research:
  - Reads `PERPLEXITY_API_KEY`.
  - Called mainly by Knowledge Hub / Retrieval Agent for up‑to‑date web search.
  - Must support:
    - Query text.
    - Optional constraints (domains, timeframes).
    - Returning **cited snippets**.

### 7.5 Local fallback models and training

- `LocalModelTrainer`:
  - Receives **successful traces** and **distilled examples**.
  - Writes them to a local dataset folder (`data/traces/`).
  - Adds CLI/HTTP endpoints:
    - `/trainer/prepare-dataset`
    - `/trainer/train-specialist` (for later manual run, not automatic long training).
  - Initial implementation can stub training and just simulate the process; later integrate real training pipelines (e.g. with huggingface/peft).

***

## 8. Memory, Obsidian brain, and data storage

### 8.1 Memory tiers

Implement at least four memory tiers:

1. **Profile memory** – stable facts about the user.
2. **Project memory** – per‑project context, decisions, artifacts.
3. **Episodic memory** – summaries of past sessions and big tasks.
4. **Vault memory (Obsidian)** – notes, docs, and graph from Obsidian.

Use a **local DB** (SQLite) to store structured memory:

- `memory_profile` table.
- `memory_projects` table.
- `memory_episodes` table.
- `agent_traces` table.

### 8.2 Obsidian Brain integration

- Assume one Obsidian vault folder, configurable path:
  - `OBSIDIAN_VAULT_PATH` (e.g., `~/Obsidian/MainVault`).
- Implement an **Obsidian indexer**:
  - Walks the vault.
  - Parses frontmatter for metadata (tags, type, status).
  - Stores note metadata (path, links, tags) into SQLite.
  - Builds embeddings for:
    - Selected notes (e.g. project/agent/prompt notes).
- The Obsidian Brain agent:
  - Exposes operations:
    - `find_notes_by_topic(topic)`
    - `summarize_notes(note_ids)`
    - `append_to_note(path, content_delta)`
  - Used by:
    - Knowledge Hub.
    - Memory Agent.
    - Automation Agent (to write logs / task pages).

### 8.3 Vector store

- Use a local vector store (FAISS/Chroma/SQLite).
- Requirements:
  - Works completely offline.
  - Can store embeddings for:
    - Obsidian notes.
    - Imported PDFs/markdown files.
    - Code snippets (for Code Agent).
- Retrieval Agent:
  - Combines:
    - Vector similarity.
    - Keyword search (BM25 or simple token search).
  - Returns **limited, high‑precision evidence packs**.

***

## 9. Background runtime and job system

Design a **Background Runtime** that:

- Accepts jobs from Orchestrator / Action Hub.
- Stores them in a `jobs` table in SQLite or a Redis queue.
- Runs a configurable number of worker processes (start with 1) that:
  - Pull jobs.
  - Invoke the appropriate agent or tool.
  - Update job status, logs, progress, and results.

Job schema (DB):

```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  type TEXT,
  status TEXT,            -- queued | running | paused | done | failed | stopped
  payload JSON,
  result JSON,
  created_at TEXT,
  updated_at TEXT,
  progress REAL,
  error TEXT
);
```

Expose APIs:

- `GET /jobs` – list jobs.
- `POST /jobs` – create new job.
- `POST /jobs/{id}/pause`
- `POST /jobs/{id}/resume`
- `POST /jobs/{id}/stop`

The web UI should surface these controls so the user can **start, pause, and stop** autonomous runs.

***

## 10. Web UI / control plane requirements

Build a single‑page app (“Control Plane”) that provides:

### 10.1 Main views

1. **Architecture Tree View**
   - Visual representation of the architecture tree (mirroring the HTML diagram).
   - Click a node → show live **Node Inspector** (definition, tools, routes, metrics).

2. **Jobs / Background Runtime View**
   - Table of jobs with:
     - Status.
     - Type.
     - Progress.
     - Start/end times.
   - Buttons:
     - Start new autonomous run.
     - Pause queue.
     - Stop all tasks.

3. **Agent Factory View**
   - Form to create a new agent blueprint:
     - Name, role, layer.
     - Connected tools.
     - Model preferences.
     - Memory scopes.
     - Policies.
   - Writes a new config file in `config/agents/`.
   - Shows a preview JSON or YAML.

4. **Logs / Observability View**
   - Basic charts / tables:
     - Calls per agent.
     - Model usage.
     - Average latency and token usage (where available).
   - Filter by time range.

### 10.2 Technologies and structure

- Frontend:
  - Prefer **React + Vite** or **SvelteKit**.
- Use:
  - TypeScript.
  - Tailwind or simple CSS modules.
- Make sure:
  - No paid UI libraries.
  - All logic is local in browser + local backend.

***

## 11. Implementation phases (what Claude should do step‑by‑step)

Claude, follow these phases in order. Each phase should include file structure and code.

### Phase 1 – Repo scaffolding and core config

- Create a monorepo structure:

```txt
agent-atlas/
  backend/
    app/
      __init__.py
      main.py
      models/
      agents/
      services/
      storage/
      config/
  frontend/
    (React or Svelte app)
  config/
    models.yml
    agents/
  data/
    db/
    embeddings/
    traces/
  scripts/
  README.md
```

- Implement:
  - Backend FastAPI (or similar) with:
    - `/health` endpoint.
  - Basic `models.yml` with Hermes local only.
  - Basic `agents.yml` with orchestrator stub.

### Phase 2 – Model Abstraction and Hermes integration

- Implement `ModelClient` abstraction.
- Implement `HermesLocalClient` wired to config.
- Add a simple `/llm/test` endpoint to test Hermes calls.

### Phase 3 – Orchestrator, Planner, Evaluator, Collaboration Bus

- Implement data models for messages and agents.
- Implement:
  - `run_orchestrator()`.
  - `run_planner()`.
  - `run_evaluator()`.
- Implement simple **in‑process Collaboration Bus**:
  - `send_message(message)` and `dispatch_message(message)`.

### Phase 4 – Knowledge Hub, Memory Agent, Retrieval Agent

- Implement SQLite DB and basic tables for memory.
- Implement a local vector store.
- Implement:
  - Knowledge Hub:
    - When to call Retrieval vs Obsidian vs Perplexity.
  - Memory Agent:
    - Saving session summaries.
  - Retrieval Agent:
    - Hybrid search.

### Phase 5 – Obsidian Brain integration

- Implement vault configuration and scanning.
- Parse frontmatter and build a small index.
- Add endpoints:
  - `GET /obsidian/notes`
  - `POST /obsidian/search`
- Wire Obsidian Brain agent to use these.

### Phase 6 – Action Hub, Code Agent, Automation Agent, Background Runtime

- Implement Action Hub with:
  - Tool registry pattern.
- Implement:
  - Code Agent (repo map + basic edit/test).
  - Automation Agent (stubbed scheduled tasks).
- Implement Background Runtime:
  - Job table.
  - Background worker (can be started via CLI or a backend task).
  - Job control APIs.

### Phase 7 – Model Router, Claude/Perplexity connectors, Local Trainer

- Implement Model Router logic:
  - Select model based on `capabilities` and config.
- Add connectors for:
  - Claude Pro.
  - Perplexity Pro.
- Implement Local Trainer stub:
  - Data collection from traces.
  - CLI for preparing training dataset.

### Phase 8 – Guardian, Deployment, Observability

- Implement Guardian Agent:
  - Policy engine.
  - Rules for high‑risk tools.
- Deployment Agent:
  - Management of versioning/config updates (initially just write configs + simulate).
- Observability Agent:
  - Logging of agent calls.
  - Simple metrics tables.

### Phase 9 – Web UI (tree, jobs, factory, logs)

- Build the SPA with:
  - Tree view bound to backend `/agents` definitions.
  - Jobs view bound to `/jobs` endpoints.
  - Agent Factory form writing new agent configs through backend.
  - Logs view bound to observability metrics.

### Phase 10 – Polish, docs, and local‑only fallback mode

- Add:
  - `LOCAL_ONLY` flag in config to disable remote models and search.
  - Documentation in `README.md`:
    - How to run backend + frontend (with commands).
    - How to configure Hermes, Claude, Perplexity.
    - How to point to Obsidian vault.
  - Example flows:
    - Simple Q&A using Hermes only.
    - Research task using Perplexity + Obsidian + Retrieval.
    - Coding task with Code Agent + Evaluator.
    - Long‑running background automation (example).

***

## 12. Additional expectations

- **Testing**:  
  Include at least:
  - Unit tests for Model Router.
  - Unit tests for message routing and job queue behavior.

- **Error handling**:
  - Graceful fallbacks when:
    - Remote APIs are unavailable.
    - Hermes endpoint is offline.
    - Obsidian vault path is invalid.

- **Configuration**:
  - Use `.env` + config files.
  - Provide example `.env.example`.

- **Style**:
  - Keep code readable, commented where non‑obvious.
  - Prefer explicit over clever.

***

**Claude, start from Phase 1 and work forward.  
Do not skip any phase or major step.  
Keep everything free, local‑first, and well‑documented.**
# Agent Atlas – Local‑First Multi‑Agent System Design Spec (Extended)

> Drop this file into your repo (e.g. `docs/agent-atlas-spec.md`) and feed sections to Claude as implementation prompts.
>
> This is an **opinionated, local‑first, free‑to‑run multi‑agent system blueprint** optimized for a single developer machine with optional API subscriptions.

---

## 0. Goals and Non‑Goals

### 0.1 Goals

- Build a **local‑first multi‑agent architecture** that:
  - Lets many focused agents collaborate on the same task.
  - Can run **autonomously in the background** until completion or manual stop.
  - Uses **Hermes + Claude Pro + Perplexity Pro** when available, but stays useful if APIs go away.
  - Treats an **Obsidian vault as the “brain”** for long‑term knowledge and project memory.
  - Exposes a clean **web UI control plane** for:
    - Inspecting the agent tree.
    - Starting/pausing/stopping jobs.
    - Creating new agents.
    - Viewing logs and metrics.

- Keep **all core infrastructure free and self‑hostable**:
  - Local DB, queues, vector store, logging, and training.
  - Everything runs on **Windows 11 + WSL2/Ubuntu** or directly on Linux.

- Design for a **single machine**, but make it easy to later move to a small local server or homelab.

### 0.2 Non‑Goals

- This is not a SaaS product with multi‑tenant support; it is a **personal agent OS**.
- No requirement for Kubernetes, distributed databases, or enterprise infrastructure.
- We are not optimizing for maximum throughput; we are optimizing for:
  - Clear mental model.
  - Reliability on a single box.
  - Hackability and extensibility.

---

## 1. User Environment and Assumptions

### 1.1 Hardware

Assume a reasonably powerful personal machine (adjustable in practice):

- CPU: 8+ logical cores.
- RAM: 32 GB preferred (minimum 16 GB, design should still work albeit slower).
- GPU: 10–16 GB VRAM (e.g. RTX 3060/4060/4070 class) **or** CPU‑only with performance tradeoffs.
- Storage:
  - System drive (C: or `/`) with OS and dev tools.
  - At least **1 TB SSD** for models and data.
  - Suggested base paths:
    - `~/agent-atlas/` – repo root.
    - `~/agent-atlas/data/` – DBs, embeddings, logs, artifacts.
    - `~/Obsidian/MainVault/` – Obsidian vault.
    - `~/models/` – local models (Hermes, fallback models).

### 1.2 Software

- OS: Windows 11 with **WSL2/Ubuntu** OR native Linux.
- Dev tools:
  - VS Code.
  - Git + GitHub.
  - Docker + Docker Compose.
  - Python 3.11+.
  - Node.js LTS (for frontend).

### 1.3 Model Providers

- **Local Hermes** (primary default):
  - Exposed via a local HTTP endpoint, ideally OpenAI‑compatible.
- **Claude Pro** (optional):
  - API key set via `CLAUDE_API_KEY`.
- **Perplexity Pro** (optional):
  - API key set via `PERPLEXITY_API_KEY`.
- **Local specialist models** (optional, future):
  - Fine‑tuned/LoRA adapters, exposed via local endpoints as well.

---

## 2. High‑Level Architecture Overview

### 2.1 Layers

The system is organized into four logical layers:

1. **Control / Coordination Layer**
   - Executive Orchestrator
   - Planner Agent
   - Evaluator Agent
   - Collaboration Bus (inter‑agent messaging)

2. **Knowledge / Brain Layer**
   - Knowledge Hub
   - Memory Agent
   - Obsidian Brain
   - Retrieval Agent (vector + keyword)

3. **Action / Execution Layer**
   - Action Hub
   - Code Agent
   - Automation Agent
   - Background Runtime (job queue + workers)

4. **Platform / Governance Layer**
   - Creative Studio Agent
   - Agent Factory (new agent creator)
   - Model Router
   - Local Model Trainer
   - Guardian Agent (policy/safety)
   - Deployment Agent
   - Observability Agent

### 2.2 Data Flow Examples

#### 2.2.1 Simple Question (Local Only)

1. User asks a question via web UI.
2. Orchestrator receives the request.
3. Model Router chooses **Hermes local**.
4. Orchestrator sends messages to Hermes and returns answer.
5. Memory Agent optionally stores a summary.

#### 2.2.2 Complex Research + Coding Task

1. User gives a complex goal: e.g., “Build a script that scrapes a site and logs into Obsidian.”
2. Orchestrator → Planner:
   - Planner decomposes into subtasks (research, design, code, test, docs).
3. Orchestrator → Collaboration Bus:
   - Knowledge Hub (Perplexity + Retrieval + Obsidian Brain) gathers requirements and context.
   - Code Agent designs and implements the script.
   - Creative Studio produces any docs/diagrams.
4. Evaluator reviews outputs, suggests fixes.
5. Automation Agent hooks script into a scheduled job via Background Runtime.
6. Memory Agent + Obsidian Brain store project notes, decisions, and final code references.

#### 2.2.3 Long‑Running Automation

1. User defines an automation: “Every day, fetch sales data and update an Obsidian note and a CSV.”
2. Planner defines a recurrent plan.
3. Action Hub + Automation Agent emit a **job** into Background Runtime.
4. Worker executes task daily, writing back to Obsidian and local files.
5. Observability Agent tracks runs, failures, and durations.
6. User can pause/stop from web UI.

---

## 3. Repository Structure

### 3.1 Top‑Level Layout

```txt
agent-atlas/
  backend/
    app/
      __init__.py
      main.py
      api/
      agents/
      models/
      services/
      storage/
      config/
      utils/
  frontend/
    src/
    public/
    vite.config.ts
    package.json
  config/
    models.yml
    agents/
      orchestrator.yml
      planner.yml
      ...
  data/
    db/
      agent_atlas.sqlite
    embeddings/
      obsidian/
      docs/
      code/
    traces/
    models/
      hermes/
      local_specialists/
  docs/
    agent-atlas-spec.md
  scripts/
    dev.sh
    dev.ps1
  .env.example
  README.md
```

### 3.2 Backend Modules

- `app/main.py` – FastAPI entrypoint.
- `app/api/` – HTTP routes (jobs, agents, obsidian, etc.).
- `app/agents/` – agent implementations (orchestrator, planner, etc.).
- `app/models/` – Pydantic models / schemas.
- `app/services/` – business services (LLM clients, Obsidian, vector store, runtime).
- `app/storage/` – DB layer (SQLite wrapper), migrations.
- `app/config/` – config loading (YAML + env).
- `app/utils/` – misc helpers (logging, IDs, etc.).

### 3.3 Frontend Modules

- `src/components/` – UI components.
- `src/pages/` – View pages (Tree, Jobs, Factory, Logs).
- `src/api/` – Frontend API client.
- `src/state/` – global state (Zustand/Redux or minimal custom store).

---

## 4. Configuration System (Models and Agents)

### 4.1 Model Config (`config/models.yml`)

```yaml
models:
  hermes_local:
    provider: local
    type: chat
    endpoint: http://localhost:11434/v1/chat/completions
    model: hermes-2
    capabilities:
      - general
      - private
      - cheap
    max_tokens: 4096
    temperature: 0.7

  claude_pro:
    provider: claude
    type: chat
    api_key_env: CLAUDE_API_KEY
    model: claude-3-opus
    capabilities:
      - deep_reasoning
      - coding
      - complex_writing
    max_tokens: 8192
    temperature: 0.4

  perplexity_pro:
    provider: perplexity
    type: chat
    api_key_env: PERPLEXITY_API_KEY
    model: sonar
    capabilities:
      - web_research
      - up_to_date
    max_tokens: 4096
    temperature: 0.3

  local_specialist_fallback:
    provider: local
    type: chat
    endpoint: http://localhost:11435/v1/chat/completions
    model: agent-atlas-specialist
    capabilities:
      - fallback
      - specialist
    max_tokens: 4096
    temperature: 0.5

routing:
  allow_remote_models: true
  allow_remote_search: true
  default_model: hermes_local
  privacy_first: true
```

> Claude: implement a config loader that reads this YAML into Python dataclasses and exposes a `ModelRegistry`.

### 4.2 Agent Config Example (`config/agents/orchestrator.yml`)

```yaml
id: orchestrator
display_name: Executive Orchestrator
layer: control
role: root_router

model_preference:
  - claude_pro
  - hermes_local

inputs:
  - user_goal
  - permissions
  - context_snapshot

outputs:
  - task_graph
  - branch_assignments
  - final_response

tools:
  - planner.run
  - evaluator.run
  - knowledge_hub.run
  - action_hub.run
  - background_runtime.enqueue

memory_scopes:
  - profile
  - project
  - episodic

policies:
  - no_direct_side_effects
  - must_use_guardian_for_risky_tools

system_prompt: |
  You are the Executive Orchestrator of a local-first agent mesh.
  Your job is to:
  - Understand the user goal and constraints.
  - Decide whether this is a quick direct answer or a multi-agent plan.
  - Delegate work to specialists, not do everything yourself.
  - Prefer local models and data where possible.
  - Respect privacy and safety rules.

  Always:
  - Keep reasoning compact but clear.
  - Record key decisions for memory.
```

> Claude: create similar YAML files for all named agents, including a short role description, model preferences, tools, memory scopes, and a starter `system_prompt`.

---

## 5. Model Abstraction and Router

### 5.1 `ModelClient` Interface

Back‑end pseudo‑code:

```python
from typing import Protocol, List, Dict, Any

Message = Dict[str, Any]

class ModelClient(Protocol):
    async def chat(self, messages: List[Message], **kwargs: Any) -> Dict[str, Any]:
        """Send a chat-style request and return a structured response.

        Response format should include at minimum:
        {"content": str, "raw": ...}.
        """
        ...
```

### 5.2 Concrete Clients

Implement at least:

- `HermesLocalClient(ModelClient)` – uses local HTTP endpoint.
- `ClaudeClient(ModelClient)` – uses Claude API.
- `PerplexityClient(ModelClient)` – uses Perplexity API.

Each client must:

- Read config from `models.yml` + environment variables.
- Normalize responses into a standard internal format.

### 5.3 Model Router

Implement a `ModelRouter` service with a method:

```python
async def choose_model(task: "TaskDescriptor") -> ModelClient:
    ...
```

Where `TaskDescriptor` includes:

```python
class TaskDescriptor(BaseModel):
    privacy_level: Literal["private", "mixed", "public"]
    difficulty: Literal["trivial", "normal", "hard"]
    requires_fresh_web: bool
    budget_importance: Literal["low", "medium", "high"]
    latency_importance: Literal["low", "medium", "high"]
    preferred_models: list[str] | None
```

Routing rules (initial):

- If `privacy_level == "private"` and `allow_remote_models == false` → **Hermes local** or `local_specialist_fallback` only.
- If `requires_fresh_web == true` and `allow_remote_search == true` → **Perplexity Pro**.
- If `difficulty == "hard"` and remote allowed → **Claude Pro**, otherwise Hermes.
- Always fall back to a local model if remote provider not reachable.

---

## 6. Agents: Contracts and Responsibilities

### 6.1 Shared AgentDefinition Type

Define in TypeScript (frontend) and Pydantic (backend):

```ts
export type AgentLayer = "control" | "knowledge" | "action" | "platform";

export interface AgentDefinition {
  id: string;
  displayName: string;
  layer: AgentLayer;
  description: string;
  inputs: string[];
  outputs: string[];
  tools: string[];
  modelPreference: string[];
  memoryScopes: string[];
  policies: string[];
}
```

```python
class AgentDefinition(BaseModel):
    id: str
    display_name: str
    layer: Literal["control", "knowledge", "action", "platform"]
    description: str
    inputs: list[str]
    outputs: list[str]
    tools: list[str]
    model_preference: list[str]
    memory_scopes: list[str]
    policies: list[str]
```

### 6.2 Core Agents (Outline)

For each agent, Claude should:

- Implement a handler function `run_<agent>(payload)`.
- Describe input/output schema.
- Provide a default prompt template for LLM‑driven logic.

#### 6.2.1 Executive Orchestrator

- Role: entrypoint and overall coordinator.
- Inputs: user goal, context, permissions.
- Outputs: plan, branch calls, final response.
- Tools:
  - Planner, Evaluator, Knowledge Hub, Action Hub, Background Runtime.
- Behavior:
  - Classify request (`trivial`, `normal`, `hard`).
  - Decide whether to call Planner.
  - Decide which branches to activate.
  - Decide whether to run synchronously or enqueue to background runtime.

#### 6.2.2 Planner

- Role: turn goals into a DAG of tasks.
- Outputs include:
  - Ordered subtasks.
  - Dependencies between agents.
  - Budget allocations.

#### 6.2.3 Evaluator

- Role: critique and score outputs.
- Can request retries from other agents via Collaboration Bus.
- Uses rubrics tailored to task types.

#### 6.2.4 Collaboration Bus

See Section 7 for details; it is not a “thinking” agent, but a **fabric**.

#### 6.2.5 Knowledge Hub

- Role: decide when to use:
  - Web search (Perplexity).
  - Obsidian Brain.
  - Vector store.
- Returns a compact evidence pack.

#### 6.2.6 Memory Agent

- Role: persist:
  - User profile.
  - Project facts.
  - Session summaries.

#### 6.2.7 Obsidian Brain

- Role: treat Obsidian vault as knowledge graph.
- Capabilities:
  - Search notes.
  - Summarize clusters.
  - Append updates.

#### 6.2.8 Retrieval Agent

- Role: perform hybrid semantic + keyword retrieval.

#### 6.2.9 Action Hub

- Role: manage tool calls with side effects.
- Only executes tools that pass Guardian policy.

#### 6.2.10 Code Agent

- Role: code generation and editing.
- Needs:
  - Repo map.
  - File search.
  - Test runner.

#### 6.2.11 Automation Agent

- Role: schedule and orchestrate repetitive workflows.

#### 6.2.12 Background Runtime

- Role: job queue + workers (see Section 9).

#### 6.2.13 Creative Studio

- Role: generate images, docs, UI mocks, slides.

#### 6.2.14 Agent Factory

- Role: create new agents from templates and persist them as config.

#### 6.2.15 Model Router / Local Trainer / Guardian / Deployment / Observability

Already outlined; implement as backend services with agent interfaces where needed.

---

## 7. Inter‑Agent Messaging and Collaboration Bus

### 7.1 Message Schema

Use a normalized JSON object for messages:

```json
{
  "message_id": "uuid",
  "conversation_id": "uuid",
  "room_id": "uuid",
  "from_agent": "orchestrator",
  "to_agent": "knowledge_hub",
  "role": "request",
  "type": "research_request",
  "payload": {"goal": "...", "context": {"project_id": "..."}},
  "created_at": "2026-06-22T20:22:00Z",
  "metadata": {
    "priority": "normal",
    "runtime_mode": "sync",
    "user_visible": true
  }
}
```

### 7.2 Collaboration Bus Implementation Plan

1. **Phase 1**: In‑process router (Python):
   - A function `dispatch_message(msg)` that:
     - Looks up `to_agent` in registry.
     - Calls corresponding handler.
   - For now, messages live in memory.

2. **Phase 2**: Persistent log:
   - `messages` table in SQLite.
   - `rooms` table for collaboration rooms.
   - Each new message appended; bus can replay a conversation.

3. **Phase 3**: Background workers:
   - Allow messages to create jobs in Background Runtime.
   - Workers process messages asynchronously.

### 7.3 Collaboration Patterns

- **Research swarm**: multiple knowledge agents respond; Evaluator merges.
- **Coder + critic**: Code Agent and Evaluator exchange messages until tests pass.
- **Meta‑coordination**: Orchestrator may ask Observability for stats to change routing decisions.

---

## 8. Memory, Storage, and Obsidian Integration

### 8.1 Database Schema (SQLite)

Core tables (high‑level):

- `memory_profile(user_id, key, value, created_at, updated_at)`
- `memory_projects(project_id, key, value, created_at, updated_at)`
- `memory_episodes(id, project_id, summary, created_at)`
- `agent_traces(id, task_id, agent_id, input_json, output_json, created_at)`
- `jobs(id, type, status, payload_json, result_json, progress, error, created_at, updated_at)`
- `messages(id, room_id, from_agent, to_agent, role, type, payload_json, created_at)`
- `metrics(id, agent_id, metric, value, timestamp)`

### 8.2 Obsidian Vault

Config example in `.env`:

```env
OBSIDIAN_VAULT_PATH=/home/USER/Obsidian/MainVault
```

Indexer behavior:

- On startup or manual trigger:
  - Walk vault directory.
  - Parse Markdown files.
  - Extract:
    - Frontmatter (`---` block): type, tags, status.
    - Links (`[[Note Name]]`).
  - Store metadata to DB.
  - Compute embeddings (for selected notes) and store in vector store.

Obsidian Brain agent operations:

- `search_notes(query)` – returns note IDs.
- `summarize_notes(note_ids)` – uses LLM to summarize.
- `append_to_note(path, content)` – safe append to file.

### 8.3 Vector Store

Use a self‑hosted vector store library:

- Option A: FAISS + SQLite.
- Option B: ChromaDB embedded.

Capabilities:

- `add_documents(collection, docs)`.
- `query(collection, query_text, top_k)` → returns doc IDs + scores.

Retrieval Agent uses both:

- Vector store for semantic similarity.
- Keyword search (SQLite FTS or a simple BM25 library) for lexical recall.

---

## 9. Background Runtime and Jobs

### 9.1 Job Table Schema

```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  status TEXT NOT NULL, -- queued | running | paused | done | failed | stopped
  payload_json TEXT NOT NULL,
  result_json TEXT,
  progress REAL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 9.2 Worker Design

- Single worker process at first:
  - Poll `jobs` where `status = 'queued'`.
  - Lock job (set status to `running`).
  - Execute corresponding agent/tool.
  - Update progress, result, status.

- Later extension:
  - Multiple workers (processes/threads).
  - Priority support via `priority` column.

### 9.3 Job API

- `GET /jobs` – list jobs.
- `GET /jobs/{id}` – job details.
- `POST /jobs` – create job.
- `POST /jobs/{id}/pause` – set `status = 'paused'` if running/queued.
- `POST /jobs/{id}/resume` – set back to `queued`.
- `POST /jobs/{id}/stop` – set `status = 'stopped'` and cancel.

Background Runtime agent uses these APIs plus DB.

---

## 10. Web UI / Control Plane

### 10.1 Views

1. **Architecture Tree**
   - Fetches `/agents` from backend.
   - Renders tree structure similar to the HTML diagram.
   - Node click → shows details from `AgentDefinition` and live metrics.

2. **Jobs & Runtime**
   - Shows list of jobs with filters (status, type).
   - Buttons for start, pause, stop.
   - Shows recent activity (log of operations).

3. **Agent Factory**
   - Form for new agent:
     - Name, layer, role.
     - Model preferences (checklist).
     - Tools (multi‑select from registry).
     - Memory scopes.
     - Policies.
   - On submit:
     - POST to backend `/agents/factory` → writes YAML to `config/agents/`.
     - Optionally reloads agent registry.

4. **Logs & Observability**
   - Simple charts (e.g., using lightweight chart library) for:
     - Calls per agent.
     - Model usage counts.
     - Average latency.
   - Table of recent errors.

### 10.2 Frontend Stack

- **React + Vite + TypeScript** (or SvelteKit if preferred):
  - Use one of them consistently.
- Styling:
  - Tailwind or minimal CSS modules.
- API client:
  - Simple fetch wrappers in `src/api/`.

---

## 11. Implementation Phases (Detailed)

Claude, follow these phases in order when generating code.

### Phase 1 – Initial Repo and Config Skeleton

- Create directory structure (backend, frontend, config, data).
- Initialize Python backend with FastAPI.
- Add `.env.example` with placeholders:

```env
CLAUDE_API_KEY=
PERPLEXITY_API_KEY=
OBSIDIAN_VAULT_PATH=/home/USER/Obsidian/MainVault
LOCAL_ONLY=false
```

- Implement `/health` endpoint.
- Implement config loader for `models.yml` and at least one agent YAML (orchestrator).

### Phase 2 – Model Abstraction and Hermes Client

- Implement `ModelClient` interface and `HermesLocalClient`.
- Implement `ModelRegistry` and `ModelRouter` with basic routing.
- Add `/llm/test` endpoint to send a test prompt through Hermes.

### Phase 3 – Core Control Agents

- Implement:
  - Orchestrator agent class and handler.
  - Planner agent.
  - Evaluator agent.
  - In‑process Collaboration Bus.
- Ensure:
  - Simple end‑to‑end flow: user request → orchestrator → planner → orchestrator → Hermes → response.

### Phase 4 – Knowledge Layer and Local Memory

- Implement SQLite DB and migration script.
- Implement Memory Agent for profile + episodic memory.
- Implement vector store integration (FAISS/Chroma).
- Implement Retrieval Agent (vector + simple keyword search).
- Implement Knowledge Hub agent that:
  - Chooses between Retrieval + Obsidian vs Perplexity (when allowed).

### Phase 5 – Obsidian Brain Integration

- Implement Obsidian indexer:
  - CLI or background task to scan vault.
  - Map notes into DB + embeddings.
- Implement Obsidian Brain agent:
  - `search_notes` and `summarize_notes` operations.
  - `append_to_note` safely.

### Phase 6 – Action Layer and Background Runtime

- Implement Action Hub:
  - Tool registry pattern.
  - Tools for local shell execution (sandboxed), file system manipulation, HTTP calls (optional), and Obsidian writing.
- Implement Code Agent:
  - Repo map builder.
  - Basic code editing strategy (LLM‑driven patches).
- Implement Automation Agent:
  - Basic scheduled tasks (e.g., using cron‑like scheduling or simple polling loop).
- Implement Background Runtime:
  - Job table.
  - Worker loop.
  - APIs for creating and controlling jobs.

### Phase 7 – Remote Providers and Local Trainer

- Implement ClaudeClient and PerplexityClient.
- Extend ModelRouter with full routing logic.
- Implement Local Model Trainer stub:
  - Collect traces tagged as “successful”.
  - Export dataset in a standard format (e.g., JSONL conversations).
  - Provide CLI commands to kick off training (even if placeholder initially).

### Phase 8 – Governance and Observability

- Implement Guardian Agent:
  - Policy rules (e.g., which tools require approval).
  - Simple rule engine (YAML policies + evaluation code).
- Implement Deployment Agent (basic):
  - Manage loading/unloading agent configs.
  - Show current “version” info from Git.
- Implement Observability Agent:
  - Capture metrics into `metrics` table.
  - Provide endpoints for frontend to consume.

### Phase 9 – Frontend Control Plane

- Build SPA with:
  - Architecture Tree view.
  - Jobs view.
  - Agent Factory.
  - Observability dashboards.
- Bind all views to backend APIs.

### Phase 10 – Local‑Only Mode and Docs

- Implement `LOCAL_ONLY` behavior in ModelRouter and Knowledge Hub:
  - When true, disallow remote models and search.
- Write documentation in README:
  - Setup steps.
  - How to run backend + frontend.
  - How to integrate Hermes, Claude, Perplexity.
  - How to add a new agent via Agent Factory.

---

## 12. Additional Notes for Claude

When implementing from this spec, you should:

1. **Be explicit**:
   - Show full file paths and code when possible.
   - Avoid pseudo‑code once you start building a phase.

2. **Keep everything optional but wired**:
   - Remote models and web search always optional.
   - Core system remains functional with only Hermes (or any local OpenAI‑compatible model).

3. **Prioritize clear boundaries**:
   - Control, Knowledge, Action, and Platform layers separated.
   - Agents do not directly manipulate each others’ internals; they communicate via messages.

4. **Think about future you**:
   - This is meant for a single developer who will keep extending it.
   - Prefer simple, boring tech and patterns over complex magic.

5. **Use this spec as a contract**:
   - Do not skip phases.
   - Implement tests for critical logic (ModelRouter, Collaboration Bus, Job queue).
   - Keep the system consistent with the architecture and constraints described above.

---

_End of extended Agent Atlas spec._