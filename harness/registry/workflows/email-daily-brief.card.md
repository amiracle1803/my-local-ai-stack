# Workflow card — Olympus · Email Daily Brief

**Purpose:** every morning, read the last 24 h of email, extract action items /
FYI / suggested top-3 todos via local LLM, and write the brief into the Obsidian
vault at `_generated/email-brief-YYYY-MM-DD.md`.

**Template lineage:** `tpl-scheduled-harness-task` variant (n8n.md §6).
**Repo copy:** `harness/registry/workflows/email-daily-brief.json` (source of truth; n8n DB is a mirror).

| Field | Value |
|---|---|
| Trigger | Schedule, daily 07:15 local |
| Model | `qwen2.5:7b` via Ollama (`host.docker.internal:11434`), temp 0.3 |
| External nodes | `EXT-Gmail fetch last 24h` — the only node leaving the machine (Google Gmail API, read-only scope) |
| Side effects | read Gmail; write ONE note into vault `_generated/` (free write area per vault-write policy) |
| Failure policy | any node error fails the execution visibly in n8n Executions; no partial writes (write is the last node) |
| Idempotency | re-run same day overwrites the same `email-brief-YYYY-MM-DD.md` — safe |
| Lifetime | permanent until deactivated |

## Assumptions (approve these, not just the JSON — n8n.md §3)

1. 07:15 daily is the right time (before the 07:30 morning brief schedule in `olympus.toml`).
2. Gmail query `newer_than:1d -category:promotions -category:social`, capped at 25 emails.
3. Prompt sections fixed: Action needed / Waiting-FYI / Top-3 todos; model may use only email content.
4. Output goes to the **canonical vault** `_generated/`, frontmatter `ai: true` + 🤖 marker.
5. Obsidian must be running with the Local REST API plugin at 07:15, else the run fails visibly (acceptable v1).

## Before activation (human steps — one time)

1. n8n UI → Credentials → **Gmail OAuth2** → sign in with kpossible201@gmail.com → attach to the `EXT-Gmail fetch last 24h` node. (Google Cloud OAuth client needed; alternatively swap the node for an Outlook/IMAP-based source later.)
2. n8n UI → Credentials → **Header Auth**: Name `Authorization`, Value `Bearer <Obsidian Local REST API key>` (Obsidian → plugin settings) → attach to `Write brief to Obsidian`.
3. Run once manually (Execute workflow) → check `_generated/email-brief-….md` appears and reads well.
4. Activate the toggle. **The workflow was imported inactive and never self-activates.**

## v1.1 backlog

- Error branch → notification sink (doctrine requires it; v1 relies on n8n's execution-failure visibility).
- Feed the same brief into the LifeOS daily note (append via lifeos bridge).
- Delete the abandoned stub workflow "ai checking emails" (`HzafDCVbUlSxO6oL`) after this replaces it.
