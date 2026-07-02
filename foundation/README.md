# Foundation (optional Docker layer)

**You do not need this to use the stack.** Projects 1 and 2, and most of
Project 3, run with just Ollama + Python. This folder exists for the one thing
that benefits from a always-on background service: **n8n** (email triage).

## What's here

| File | Purpose |
|---|---|
| `docker-compose.yml` | Runs **n8n** at <http://localhost:5678> |
| `docker-compose.optional.yml` | Advanced extras: Qdrant, Portainer (see notes inside) |
| `.env.example` | Copy to `.env`; set timezone + n8n login |
| `start-n8n.bat` / `stop-n8n.bat` | Start/stop n8n |

## Use it

1. Install Docker Desktop (free): <https://www.docker.com/products/docker-desktop/>
   — on Windows it sets up WSL2 for you.
2. `copy .env.example .env` and set a strong `N8N_PASSWORD`.
3. Run `start-n8n.bat`.
4. Follow `../project3-automation/n8n/README-email.md` to build the email flow.

## The one gotcha: Docker → Ollama

Containers can't see `localhost`. So Ollama must accept outside connections and
be addressed by a special hostname:

1. Set Windows env var `OLLAMA_HOST` = `0.0.0.0`, then restart the Ollama app.
2. Inside n8n, call Ollama at **`http://host.docker.internal:11434`**.

That's it. Everything else about the stack stays exactly the same.
