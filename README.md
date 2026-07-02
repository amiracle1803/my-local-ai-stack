# My Local AI Stack

A private, **100% free** personal AI system you run on your own Windows PC. No
subscriptions, no per-token bills, no cloud. Three projects that fit together
into one "second brain":

1. **Project 1 — Ops Hub (Task Dropbox):** type a task in plain English, a local
   agent does it (plans, drafts, summaries, code).
2. **Project 2 — Second Brain over Obsidian:** every night it extracts your
   tasks/decisions/insights and writes you a review; chat with your notes via
   AnythingLLM.
3. **Project 3 — Always-On Automation:** a research digest from your feeds, a
   read-only digest of your code repos, and optional hourly email triage.

Everything runs on **Ollama** (a free local model runner). The only thing that
ever leaves your machine is fetching web pages/RSS you point it at and reading
your own mailbox — never your prompts, notes, or emails.

---

## What you install (all free)

| Tool | Why | Required? |
|---|---|---|
| **Ollama** | Runs the AI models locally | Yes |
| **Python 3.11+** | Runs the project scripts | Yes |
| **AnythingLLM Desktop** | "Chat with your notes" (Project 2) | Recommended |
| **Docker Desktop + n8n** | Email triage only (Project 3) | Optional |
| **Tailscale** | Reach it from your phone | Optional |

---

## Install order (do this once)

1. **Install Ollama** → <https://ollama.com/download>. Launch it once so it's running.
2. **Install Python 3.11+** → <https://www.python.org/downloads/> — tick
   *"Add python.exe to PATH"* during install.
3. **Run `setup.bat`** (double-click). It builds the environment, installs the
   lean Python packages, and pulls the models (a few GB the first time).
4. **Point it at your notes:** open `config.json`, set `"vault_path"` to your
   Obsidian vault folder. (Leave it to use the bundled sample vault first.)

Then start whichever project you like:

```
project1-ops-hub\start.bat        →  http://localhost:8750  (task dropbox)
project2-second-brain\start.bat   →  runs a brain review now
project3-automation\start.bat     →  research / repo digest menu
```

New here? Read **`docs/GUIDE.md`** — it walks through everything piece by piece.
Stuck? **`docs/TROUBLESHOOTING.md`** has a fix for almost anything.

---

## Folder map

```
my-local-ai-stack/
├── setup.bat                 ← run once
├── config.json               ← your settings (created by setup)
├── docs/
│   ├── GUIDE.md              ← the full manual
│   └── TROUBLESHOOTING.md    ← every known problem + fix
├── shared/                   ← code + prompt template shared by all projects
│   ├── lib/                  ← config, llm, notes, passes, state, webfetch
│   └── prompts/system-template.md
├── vault/                    ← sample Obsidian vault (point config at your real one)
├── project1-ops-hub/         ← Task Dropbox (web form + folder)
├── project2-second-brain/    ← nightly extraction + reviews
├── project3-automation/      ← research + repo digests + n8n email triage
└── foundation/               ← optional Docker layer (n8n)
```

---

## Design choices (the short version)

- **Ollama, not llama.cpp/vLLM** — it's the one that installs and "just works"
  on Windows.
- **Two planes:** plain Python + Windows Task Scheduler for all the real work
  (easy to run and inspect); Docker/n8n is an *optional* add-on for email.
- **Lean by default, heavy by choice:** light tools (trafilatura, LanceDB) are
  the defaults; the heavyweight ones from the plan (Marker, Crawl4AI, Qdrant,
  Langfuse, Unsloth) are documented as opt-in upgrades so nothing fragile is in
  your way on day one.
- **Your notes are sacred:** agents only ever write into `<vault>/_generated/`.

Full reasoning and the upgrade paths are in `docs/GUIDE.md`.
