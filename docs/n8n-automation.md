# n8n Automation Plane

Additive integration (2026-09-26). The n8n stack is a **separate compose project**
at `/home/amire/n8n-stack` — intentionally not moved into this repo. This doc is
the contract; `stack.toml [automation]` is the config source of truth.

## What it is
| Piece | Where | Notes |
|---|---|---|
| n8n UI/API | http://127.0.0.1:5679 | health: `/healthz` |
| Compose project | `/home/amire/n8n-stack` | containers: `n8n-stack-n8n-1`, `-postgres-1`, `-qdrant-1` |
| Secrets | `/home/amire/n8n-stack/.env` | API key, CHAT_USER/CHAT_PASS, HOOK_KEY — gitignored |
| Vault mount | vault → `/home/node/vault` in container | `N8N_RESTRICT_FILE_ACCESS_TO` confines file nodes |
| Web dashboard | http://127.0.0.1:8790 | read-only stack browser (`~/bin/stack-dashboard.py`, user unit `stack-dashboard`) |
| SGW relay | http://127.0.0.1:8787 | user unit `sgw-proxy` (paced ShopGoodwill API proxy) |

## Workloads (29 workflows, 28 active)
Jarvis command center chat, RAG knowledge base + upload form, morning briefing,
AI digest, product-research pipeline + sourcing radar + niche discovery,
ShopGoodwill hardware hunt, MCP toolbox (`/mcp/toolbox`), daily vault backup,
LLM provider doctor, weekly vault health, error self-repair.

## Lifecycle
- `start-all.sh` starts it (compose up) — additive block added.
- `status.sh` reports it (healthz + 3 containers).
- `stop-all.sh` leaves it running by default (commented block to stop),
  same pattern as Ollama.
- Manual: `docker compose --project-directory /home/amire/n8n-stack -f /home/amire/n8n-stack/docker-compose.yml up -d`

## Rules
- Do not move the compose project without updating `compose_dir` in stack.toml.
- n8n 2.x gotchas that apply: risky nodes need `NODES_EXCLUDE: "[]"`;
  readWriteFile read op uses `fileSelector`; binary data must be read via
  `this.helpers.getBinaryDataBuffer()` in Code nodes; errorWorkflow is the
  "Agent repair shop" workflow id `rxOmp0fHtZ2BC8Wr`.
