# Project 1 — Personal AI Ops Hub ("Task Dropbox")

**Goal:** one place where you type "do X for me" in plain English and a local
agent produces finished output — plans, drafts, summaries, code — with no cloud,
no accounts, no bills.

---

## What you get

Two ways to feed it the same brain (`process.py`):

| Interface | File | Best for |
|---|---|---|
| Web form | `app.py` (run `start.bat`) | Interactive use, phone via Tailscale |
| Folder drop | `run_inbox.py` (run `run-inbox.bat`) | Batch, syncing, scheduled runs |

Both classify your task, route it, and save the result to `task-outbox/`.

---

## Piece by piece (the data flow)

```
   you type / drop a task
            │
            ▼
   classify(task)  ──►  one of: planning · writing · research · coding · email · general
            │
            ▼
   route to a handler in process.py
            │
   ┌────────┴───────────────────────────────────────────┐
   │ planning/writing/coding/general → looped_generate() │  (fully offline)
   │ research → URLs? fetch+summarise : write a plan      │
   │ email    → draft reply + suggested labels (no send)  │
   └────────────────────────────────────────────────────┘
            │
            ▼
   result shown + saved to task-outbox/<timestamp>-<category>-<slug>.md
```

- **`classify()`** asks the model for a single category word at temperature 0
  (deterministic). If the reply isn't a known category, it falls back to
  `general`, so a weird answer never crashes anything.
- **`looped_generate()`** (from `shared/lib/passes.py`) runs the task through
  *draft → critique → revise* passes. This is the practical version of the
  "looped reasoning" idea from your Ouro notes: more passes = more refined,
  selectable in the UI (Fast / Balanced / Careful).
- **research** uses `shared/lib/webfetch.py` (trafilatura) to read any URLs you
  paste and answer grounded in them; with no URLs it writes a research plan
  instead of pretending to browse.
- **email** drafts a reply and suggests importance/labels but never sends —
  sending/labelling is Project 3's job.

---

## Run it

1. From the main folder, run `setup.bat` once (if you haven't).
2. Make sure the Ollama app is running.
3. Double-click `start.bat`. Your browser opens `http://localhost:8750`.
4. Type a task, pick effort, hit **Run**.

Prefer files? Drop `.txt`/`.md` into `task-inbox/`, run `run-inbox.bat`.
Want it automatic? Run `install-schedule.bat` (polls the inbox every 5 min).

---

## What could go wrong → the fix

| Symptom | Cause | Fix |
|---|---|---|
| Page says "Ollama OFFLINE" | Ollama app not started | Start Ollama (or `ollama serve`), refresh |
| `start.bat` says "run setup.bat first" | No `.venv` yet | Run `setup.bat` in the main folder |
| Browser can't reach `localhost:8750` | Port in use / firewall | Change `"flask_port"` in `config.json`; allow Python through the firewall |
| First answer takes 30–90s | Model loading / CPU only | Normal on first call; later calls are faster. Use a smaller model (see below) |
| Answers are weak/rambling | Small model + 1 pass | Use "Balanced/Careful", or a bigger model in `config.json` |
| Research says "could not read page" | Site blocks bots / JS-only | Try a different source, or install the optional `crawl4ai` upgrade |
| Inbox file processed twice | Moved-to-done failed (file open) | Close the file; `run_inbox.py` de-dupes by moving to `done/` |
| Two scheduled runs collide | Long task overlapped next run | Handled automatically by a lock in `state.py` |

**Redundancy built in:** two independent intake paths (web + folder). If the
web app won't start, the folder path still works, and vice-versa. Every result
is also written to disk, so nothing is lost if the browser tab closes.

---

## Making it faster on a modest PC

Edit `config.json`:

```json
{ "chat_model": "llama3.2:3b" }
```

then run `ollama pull llama3.2:3b`. The 3B model is much faster on CPU-only
machines with only a small quality drop for everyday tasks. Bigger machine?
Try `qwen2.5:14b` for stronger writing/coding.
