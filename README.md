# Olympus — Personal AI Stack

A private, **100% free** local AI hub on your Windows PC. No subscriptions, no
cloud, no per-token bills. The stack runs on Ollama and serves a multi-agent
operating system through a unified web dashboard.

## One command to start

Double-click `start.bat`. It brings up:

| Service | Port | Description |
|---|---|---|
| **Ollama** | 11434 | Local LLM runner (must be installed separately) |
| **Olympus** | 4600 | Agent hub — dashboard, API, task routing, scheduler |
| **OpenCode MCP** | 4720 | Intelligence layer — web fetch, search, code tools |
| **Obsidian** | 27123 | Note vault with Local REST API plugin |

Optional (check status only, start manually): Voice Studio, ComfyUI, LM Studio,
AnythingLLM, n8n, MCP Gateway, Langfuse.

Visit `http://127.0.0.1:4600` after startup.

## Install (once)

1. **Ollama** ? https://ollama.com/download — launch it once
2. **Python 3.11+** ? https://www.python.org/downloads/ — tick *"Add python.exe to PATH"*
3. **Run `setup.bat`** — builds `.venv`, installs packages, pulls models
4. **Edit `config.json`** — set `vault_path` to your Obsidian vault

New here? Read **`docs/GUIDE.md`**. Stuck? **`docs/TROUBLESHOOTING.md`**.

## File map

```
my-local-ai-stack/
+-- start.bat                  ? daily boot (one button)
+-- setup.bat                  ? one-time install
+-- olympus.toml               ? hub config (models, paths, API keys)
+-- config.json                ? shared settings
+-- olympus/
¦   +-- kernel/                ? FastAPI app, agents, scheduler, brain
¦   +-- agents/                ? individual agent crafts (.md files)
¦   +-- web/                   ? dashboard frontend
+-- opencode/
¦   +-- mcp_server.py          ? MCP server (web fetch, search, code tools)
¦   +-- crafts/                ? TDD, debugging, verification guides
+-- shared/lib/                ? config, llm, notes, passes, state, webfetch
+-- docs/
¦   +-- GUIDE.md
¦   +-- TROUBLESHOOTING.md
+-- foundation/                ? optional Docker layer (n8n etc.)
+-- LifeOS/                    ? frozen snapshot (live at E:\LifeOS)
+-- voice-studio/              ? TTS engine (Kokoro + F5-TTS)
+-- llm-wiki-workflow/         ? LLM-managed knowledge base
```

## Agents

| Agent | Domain | Role |
|---|---|---|
| Jarvis | chat | Conversational front-end |
| Conductor | system | Morning briefs, evening wraps, life triage |
| Forge | pipeline | Anime pipeline plans, prompts, shot lists |
| Archivist | research | Knowledge base scanning, research |
| Scribe | content | Writing and editing |
| Plutus | commerce | eBay, finance |
| Calliope | creative | YouTube scripts, Aether Echoes |
| Athena | strategy | Planner, verifier, task oversight |
| Sovereign | pipeline | Software development with TDD discipline |

## Design philosophy

- **Ollama-native** — works with any model; upgrade by editing `olympus.toml`
- **One Python venv** — everything shares `.venv`, no venv-per-project overhead
- **MCP mesh** — Olympus, OpenCode, LifeOS, and LLM Wiki speak the Model Context
  Protocol for cross-tool delegation
- **Lean by default** — Docker/n8n, ComfyUI, Langfuse are optional add-ons
- **Your data stays local** — only outbound traffic is web pages/RSS you configure
