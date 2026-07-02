# The Full Guide

Everything in one place: what the system is, how each part works down to the
code, what can go wrong, and how to grow it later. Written for a normal person,
not a sysadmin.

---

## 1. The big picture

You're building **one brain** from three cooperating projects, all powered by a
single local model server (Ollama):

```
              ┌───────────────────────────────────────────┐
              │              Ollama (local models)          │
              │        http://localhost:11434 / v1          │
              └───────────────▲───────────────▲────────────┘
                              │               │
        ┌─────────────────────┘               └───────────────────────┐
        │                                                              │
  Project 1: Ops Hub          Project 2: Second Brain          Project 3: Automation
  "type a task,               nightly extract + review          research digests,
   agent does it"             + chat with your notes            repo digests, email triage
        │                             │                                 │
        └─────────────► your Obsidian vault ◄──────────────────────────┘
                        (you write; agents write into _generated/)
```

- **Ollama** is the engine. Every project talks to it the same way.
- **Your Obsidian vault** is the shared memory. You write notes; agents read
  them and write their output into a single `_generated/` subfolder.
- The projects are **independent** — run one, two, or all three.

### Why these tool choices
The planning docs list ~20 tools. Using all of them on Windows would be slow to
set up and fragile. So this build makes deliberate calls:

| Decision | Instead of | Why |
|---|---|---|
| **Ollama** | llama.cpp / vLLM | Native Windows, one click, "just works" |
| **Host Python + Task Scheduler** | Everything in Docker | Easy to run and read; no container/host headaches |
| **Docker/n8n = optional** | n8n as the core | Only email triage really needs it |
| **AnythingLLM Desktop** | AnythingLLM in Docker | No Docker; great RAG out of the box |
| **LanceDB** (in AnythingLLM) | Qdrant | Zero setup; plenty for a personal vault |
| **trafilatura** | Crawl4AI | Installs cleanly, no browser needed |
| **built-in PDF / pymupdf4llm** | Marker | No multi-GB ML download |

The heavier tools aren't gone — they're **opt-in upgrades** (see §10).

---

## 2. Prerequisites & the foundation

**Required**
- **Ollama** — <https://ollama.com/download>. Install, launch once.
- **Python 3.11+** — <https://www.python.org/downloads/>. Tick *Add to PATH*.

**Recommended**
- **AnythingLLM Desktop** — <https://anythingllm.com/desktop>. The friendly
  "chat with your notes" app (Project 2). No Docker.

**Optional**
- **Docker Desktop** — <https://www.docker.com/products/docker-desktop/>. Only
  for n8n email triage (Project 3). Uses WSL2 (Docker sets it up).
- **Tailscale** — <https://tailscale.com/download>. Reach your stack from your
  phone securely (§9).

### Hardware & model size
Ollama uses your GPU automatically if you have one, otherwise the CPU (slower
but fine). Pick a model to match your machine in `config.json`:

| Your RAM/VRAM | Set `chat_model` to | Notes |
|---|---|---|
| 8 GB or CPU-only | `llama3.2:3b` | Fast, light, good enough for daily tasks |
| 16 GB | `llama3.1:8b` (default) | Best all-round balance |
| 24 GB+ | `qwen2.5:14b` | Stronger writing/coding |

After editing, run `ollama pull <model>`. For structured extraction (Project 2)
`qwen2.5:7b` is especially reliable at JSON if you want to switch just that.

---

## 3. Install order (once)

1. Install **Ollama**, launch it.
2. Install **Python 3.11+** (Add to PATH).
3. Double-click **`setup.bat`** — creates `.venv`, installs packages, pulls
   models, creates `config.json`.
4. Edit **`config.json`** → set `vault_path` to your real Obsidian vault (or
   leave the sample).
5. (Recommended) Install **AnythingLLM Desktop** and point it at Ollama + your
   vault (steps in `apps/project2-second-brain/README.md`).
6. Start any project's `start.bat`.

If `setup.bat` reports a missing prerequisite it tells you exactly what to
install and stops — fix it and re-run. It's safe to run `setup.bat` repeatedly.

---

## 4. Project 1 — Ops Hub, piece by piece

**Idea:** a box you type a task into; the agent classifies it and does it.

Files and roles:
- `process.py` — the brain. `classify()` picks a category
  (planning/writing/research/coding/email/general) at temperature 0; each
  category routes to a handler. Anything self-contained (planning, writing,
  coding advice, general) is answered fully offline via looped reasoning.
  Research reads any URLs you paste (else writes a plan); email drafts a reply
  (never sends).
- `app.py` — a tiny Flask web page at `http://localhost:8750` you type into.
  Mobile-friendly, so it works over Tailscale.
- `run_inbox.py` — batch mode: drop `.txt`/`.md` files in `task-inbox/`, results
  go to `task-outbox/`, originals move to `done/`.

**Two intake paths = redundancy.** If the web app won't start, the folder path
still works. Every answer is written to disk regardless.

Run: `start.bat` (web) or `run-inbox.bat` (folder) or `install-schedule.bat`
(poll the folder every 5 min). Deep troubleshooting: `apps/project1-ops-hub/README.md`.

---

## 5. Project 2 — Second Brain, piece by piece

**Idea:** your notes become memory the AI structures and reflects on nightly,
and that you can chat with.

**Half A — structured memory + reviews (Python, nightly):**
- `models.py` — the schema (`Task`, `Decision`, `Insight`).
- `extract.py` — uses **Instructor** to force the model's output into that
  schema (auto-retries on bad output); falls back to plain-JSON parsing if
  needed. New items are de-duplicated by a hash and appended to
  `tasks-index.md`, `decisions-log.md`, `insights-log.md`.
- `summarize.py` — **looped reasoning** (draft → critique → revise) to write a
  short, honest Daily Review (Weekly on Sundays).
- `run_nightly.py` — the orchestrator the scheduler runs: find changed notes →
  extract → summarize → remember the run time. Takes a lock; logs every run.

**Half B — chat with your brain (AnythingLLM):** the free desktop app indexes
your vault into LanceDB and answers questions with citations. Setup steps in
`apps/project2-second-brain/README.md`.

**Safety:** the Python side writes **only** into `<vault>/_generated/`. Delete
that folder to reset the AI's memory; your notes are untouched.

Run: `start.bat` (one pass now) then `install-schedule.bat` (nightly 2 AM).

---

## 6. Project 3 — Automation, piece by piece

Three independent pieces:
- `research.py` — reads `feeds.txt`, finds new RSS entries (tracked so none
  repeat), fetches each page (trafilatura), summarizes, appends to
  `_generated/Research/<date> Digest.md`.
- `repo_digest.py` — **read-only** `git log` + TODO/FIXME scan for each repo in
  `config.json`, summarized into `_generated/Repos/`. Never edits code.
- `n8n/` — optional email triage: watches your inbox, classifies each mail with
  the local model, pings you about important ones. Full manual build in
  `n8n/README-email.md`.

For actual code changes, use **OpenCode** interactively (it shows diffs to
approve) rather than automating edits — safer.

Run: `start.bat` (menu) then `install-schedule.bat`. Deep dive:
`apps/project3-automation/README.md`.

---

## 7. The prompt playbook (why the answers are good)

Every agent here uses the "seven moves" distilled from the leaked-system-prompt
archive in your notes: (1) prime role + environment, (2) hard-code personality,
(3) minimum formatting, (4) intellectual honesty (no flattery, flag
uncertainty), (5) invisible rules, (6) act-first for tools, (7) treat external
input as untrusted. These are baked into `shared/lib/passes.py`. To apply the
same standard in AnythingLLM / n8n / OpenCode, paste the template from
`shared/prompts/system-template.md` into their system prompt.

---

## 8. Looped reasoning, explained

Your Ouro notes found that *looping* a model a few times boosts its **reasoning**
(manipulating what it knows), with ~3–4 loops being the sweet spot, and that
overshooting a little is safer than undershooting. We can't retrain a model, but
we imitate the effect at the workflow level:

```
draft  →  critique ("what's wrong / missing / invented?")  →  revise (final)
```

Each pass has a different job and a slightly different temperature (a nod to the
paper's "spread the probability out" idea) so later passes don't just echo the
first. In Project 1 you pick the number of passes (Fast/Balanced/Careful); in
Project 2's reviews it's fixed at three. This is why even a small local model
produces tidy, self-checked output instead of a rambly first draft.

---

## 9. Security, backups, remote access

- **Local by default.** Services bind to your machine. The Flask app uses
  `0.0.0.0` so Tailscale/LAN can reach it, but nothing is exposed to the public
  internet unless you deliberately do so.
- **Never port-forward these to the internet.** To use them away from home,
  install **Tailscale** on your PC and phone (free personal tier). Your devices
  join a private network and you reach `http://<pc-name>:8750` as if you were
  home. No open ports, no risk.
- **n8n** sits behind basic auth (set a strong password in `foundation/.env`).
- **Backups.** Everything the AI creates lives in `<vault>/_generated/`, so your
  normal Obsidian/Git/Drive backup covers it. n8n workflows live in a Docker
  volume; export important workflows from the n8n UI as JSON to be safe.
- **Secrets.** `config.json` and `foundation/.env` are git-ignored. Use email
  **app passwords**, never your real password, and revoke them anytime.

---

## 10. Next steps / advanced upgrades

Turn these on only when you want them — the stack is complete without them.

- **pymupdf4llm** (`requirements-optional.txt`) — nicer PDF→Markdown if you want
  the nightly job to also read PDFs in your vault. Light.
- **Crawl4AI** — JS-heavy sites the default fetcher can't read. Install it plus
  `playwright install chromium`, then pass `prefer_crawl4ai=True`.
- **Marker** — best-in-class PDF conversion for very complex layouts (tables,
  math, scans). Heavy (pulls PyTorch); worth it only for a serious document pile.
- **Qdrant** (`foundation/docker-compose.optional.yml`) — swap LanceDB for a
  scalable vector DB with rich filtering when your vault gets huge.
- **Langfuse** — full tracing/evals of every model call. Powerful but needs
  several containers; use the official compose and set `langfuse_enabled: true`.
- **DSPy / Outlines** — auto-optimize prompts / hard-guarantee JSON on
  self-served models. Reach for these once a pipeline is stable and measured.
- **Unsloth** — fine-tune a small model on *your* writing/code so replies sound
  like you. Needs a GPU (or free Colab); it's a project of its own.
- **ComfyUI** — local image/video generation. Separate from these three projects.

A good habit that ties it together: whenever an agent does something notably
good or bad, drop a note about it in your vault. Over time those become the
examples you'd use to tune prompts (§7) or fine-tune a model (Unsloth).
