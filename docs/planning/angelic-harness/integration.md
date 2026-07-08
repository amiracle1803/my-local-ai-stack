# integration.md — Second Brain, MCP Topology & Service Access Points

How agents reach everything outside the harness: the Obsidian/LifeOS second brain,
MCP servers, n8n, and every local service — through registered ports, never ad hoc.

---

## 1. Access doctrine

1. **Everything is a registered tool.** Agents call tools by name from `registry/tools.yaml`; the tool-port resolves name → transport (MCP / HTTP / CLI / file). No agent holds a URL, path, or API key in its prompt.
2. **Ports carry the permissions.** Each tool entry declares its side-effect class (agent.md §3) and offline behavior; the port enforces both per the task's current state.
3. **Secrets never transit agents.** Keys live in config (`olympus.toml`, n8n credential store, env); the port injects them at call time. A model that has never seen a key cannot leak one.

### 1.1 Secrets inventory & canonical locations (audited 2026-07-07)

Current state on this machine — the repo is **private** on GitHub and no real secret is
git-tracked (only `.env.example` templates are committed); real keys live in untracked files:

| Secret | Location(s) | Status |
|---|---|---|
| n8n API key | `foundation/.env` (`N8N_API_KEY`) is **canonical** (verified live against the API 2026-07-07); `olympus/olympus.toml [n8n].api_key` now carries the same value (stale duplicate replaced) | ✅ resolved — on future rotation update `foundation/.env` first, then re-sync `olympus.toml` |
| n8n basic auth | `foundation/.env` (`N8N_PASSWORD`) | untracked, fine |
| Langfuse Postgres password | `foundation/docker-compose-langfuse.yml` (`langfuse_local_dev`) | committed but dev-grade + localhost-bound — acceptable for a private local stack |
| SearXNG `secret_key` | `foundation/searxng/settings.yml` | instance-local session secret, not a service credential |
| Hermes `api_key` | `olympus.toml [hermes]` | currently commented out / unset |

Rules going forward: **one canonical location per secret** — `foundation/.env` for
docker-side services, `olympus.toml` only for values no other component needs; new
secrets are never added to git-tracked files (compose files pass them via `env_file:`);
the harness `tools.yaml` references secrets as `config:` pointers (see §1 examples),
never as literals; and any key that was ever committed to a tracked file gets rotated,
not just moved.

Sample `registry/tools.yaml` entries:

```yaml
obsidian-rest:
  transport: http
  endpoint: https://127.0.0.1:27124          # Obsidian Local REST API plugin
  auth: config:olympus.toml/obsidian.api_key
  side_effects: write-shared                  # curator-only (memory.md §6)
  offline: full                               # local plugin; needs Obsidian running
  degraded: obsidian-files                    # fall back to direct file read
obsidian-files:
  transport: file
  root: 'C:\Users\amire\Documents\Obsidian Vault'
  side_effects: read                          # read-only by doctrine; writes go via curator
  offline: full
n8n-api:
  transport: http
  endpoint: http://127.0.0.1:5678/api/v1
  auth: config:olympus.toml/n8n.api_key
  side_effects: external                      # import inactive = write-scoped; activate = human gate
  offline: full (service required)
```

## 2. Second brain — Obsidian & LifeOS access

Two vaults, three access paths, one writer.

| Path | Mechanism | Who uses it | Notes |
|---|---|---|---|
| **Read: retrieval** (default) | Qdrant collections `vault-obsidian`, `vault-lifeos`, refreshed by an ingest job (file-watch n8n template or nightly) | retriever, via evidence bundles | Agents should *retrieve* vault knowledge, not browse it — cheaper and ranked |
| **Read: direct** | `obsidian-files` (plain file read) or `obsidian-rest` (Local REST API plugin — the same plugin AnythingLLM already uses per CLAUDE.md); `lifeos` MCP server for `E:\LifeOS` (`lifeos_read_note`, `lifeos_overview`, …) | researcher/executor when a *specific* note is cited | Direct reads are for cited paths, not exploration |
| **Write** | per the **vault-write policy** (`../second-brain/DESIGN.md` §3–§5): frontmatter additive edits by pipeline agents; bodies only on `ai: true` notes; moves/merges via curator + approvals file; `_generated/` and LifeOS daily-note appends (`lifeos_log_daily` / `lifeos_write_note`) are the free areas | pipeline agents (frontmatter), memory-curator (everything else) | Marked as machine-written (🤖 convention already in use); Obsidian-flavored markdown per the installed obsidian-skills packs — the `obsidian-markdown` skill pack is loaded for any vault write |

Storage rules for tasks & information (binding, cross-referenced):

- **Task state** → `runs/<task-id>/` only (agent.md §6); never in a vault.
- **System knowledge** → `harness/memory/` typed entries (memory.md §4); vaults are *the human's* space.
- **Human-facing outputs** (digests, briefs, recap-video reports) → vault `_generated/` via curator, linking back to the run ID for provenance.
- Vault offline/locked ⇒ degraded corpus, never a blocked task (memory.md §2).

## 3. MCP topology

What exists today (from `.mcp.json` and the running config) and how the harness maps it:

| MCP server | Provides | Harness consumer |
|---|---|---|
| `lifeos` | vault notes, tasks, schedule, agent chat at `E:\LifeOS` | curator (writes), retriever/researcher (reads), Manager (task sync) |
| `opencode` | web fetch/search, code search, file read, code analysis | researcher, coder (as registered tools) |
| Obsidian Local REST (via AnythingLLM today) | live vault CRUD | curator |
| `olympus/skills/` MCP server | Olympus-side skills | executor |

Design rules:

- Every MCP tool the harness may call gets a `tools.yaml` entry (side-effect class, offline flag, owning agents) — MCP discovery does **not** auto-grant access; registration is the gate.
- **ProxyMCP / MCP-gateway pattern** (foundation has `start-mcp-gateway.bat`): one aggregator endpoint in front of all MCP servers, so the harness speaks to a single MCP client connection, and per-agent tool *allowlists* are enforced at the gateway, not per-server. Label: **Near-term experimental** — Practical-now fallback is direct per-server connections with port-layer allowlists.
- MCP servers are execution-plane services: offline-ops health-checks them like Ollama; a dead server flips its tools to `degraded` in the registry status file.

## 4. Service access map (this machine)

| Service | Endpoint | Used for | Offline |
|---|---|---|---|
| Ollama | `127.0.0.1:11434` | T0–T2 inference, embeddings | ✅ |
| llama.cpp server | local, registry-pinned port | T2 offload rung, grammar-constrained JSON | ✅ |
| Hermes | `127.0.0.1:8642` | fallback rung F (OpenAI-compatible) | ✅ |
| Olympus kernel | `127.0.0.1:4600` | schedules, voice, dashboard, pipeline triggers | ✅ |
| n8n | `127.0.0.1:5678` (`/api/v1`, webhooks) | workflow import/dry-run/stats; intake webhooks | ✅ |
| Qdrant | `127.0.0.1:6333` | vector retrieval | ✅ (FAISS fallback) |
| ComfyUI | `127.0.0.1:8188` | image/video generation (pipeline tasks) | ✅ |
| Voice studio (Kokoro/F5) | Flask app, `olympus/engines/voice` | TTS artifacts | ✅ |
| whisper.cpp | CLI tool | audio → text intake | ✅ |
| SearXNG | foundation compose | metasearch (researcher, online only) | ❌ → corpus mode |
| Langfuse | foundation compose | trace sink (optional; calls.jsonl is the always-on log) | optional |

n8n ↔ harness connection, concretely (complements n8n.md):

- **Harness → n8n**: `n8n-api` tool — import workflow (inactive), trigger manual/dry runs, read execution stats. Activation is excluded from the tool's surface entirely; it happens in the n8n UI or via an explicitly human-approved bridge call (n8n.md §4 gate).
- **n8n → harness**: one intake webhook (`POST /intake` on the harness server) with a scrub step in front (n8n.md template `tpl-webhook-bridge`); plus `tpl-scheduled-harness-task` for recurring goals.
- **Health loop**: `tpl-service-health` pings every row of the table above and writes the status file offline-ops reads.

## 5. Failure logging integration (pointer)

The full protocol lives in memory.md §7 and handoff.md §8; the integration-relevant part:
every tool-port failure (timeout, HTTP error, dead MCP server) auto-drafts the `err-`
entry skeleton (symptom + context filled from the call record) so the curator finalizes
rather than reconstructs — failures at the *integration* layer are captured even when no
agent was "at fault," and the offline-ops status file links to them.
