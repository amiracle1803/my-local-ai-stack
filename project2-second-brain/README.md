# Project 2 — Second Brain over Obsidian

**Goal:** your notes become a memory the AI reads from and writes back to. Every
night it pulls out your tasks, decisions, and insights into running lists, and
writes you a short, honest Daily Review — all inside your vault, all local.

This project has **two halves** that work together:

| Half | What it does | Runs |
|---|---|---|
| **Structured memory + reviews** (this folder's Python) | Extracts tasks/decisions/insights, writes daily/weekly reviews | Nightly, via Task Scheduler |
| **"Chat with your brain" (RAG)** | Ask questions across all your notes | AnythingLLM (desktop app) |

You don't have to use both, but together they're the whole loop:
**you write → AI structures + reviews → you chat with it → repeat.**

---

## The golden safety rule

> The Python jobs **only ever write inside `<vault>/_generated/`**. Your own
> notes are never edited, moved, or deleted. If you ever dislike what the AI
> produced, delete `_generated/` and nothing of yours is lost.

Generated layout inside your vault:

```
_generated/
├── tasks-index.md          # running task list (deduped)
├── decisions-log.md        # running decisions log
├── insights-log.md         # running insights log
├── Daily Notes/2026-07-01 Review.md
├── Weekly Notes/…          # created on Sundays
├── logs/…                  # one log file per nightly run
└── .state/second_brain.json# remembers what's been processed
```

---

## Piece by piece

```
run_nightly.py  (orchestrator, scheduled)
     │
     ├─ finds notes changed since last run          (shared/lib/notes.py)
     │
     ├─ extract.py  ── Instructor fills NoteExtraction (models.py)
     │        │        └─ fallback: plain-JSON parse if Instructor errors
     │        └─ files NEW items into the running logs (deduped by hash)
     │
     ├─ summarize.py ── looped draft→critique→revise → Daily Review
     │                  (Weekly Review too, on Sundays)
     │
     └─ saves last-run time  (shared/lib/state.py)  + writes a run log
```

- **`models.py`** defines the schema (`Task`, `Decision`, `Insight`). The model
  is *forced* to return data in this shape.
- **`extract.py`** tries **Instructor** first (schema-validated, auto-retries on
  malformed output). If Instructor isn't installed or errors, it falls back to
  asking for plain JSON and validating that. Either way the run survives a bad
  response. De-dupe is a hash of `type + normalised text`, so re-running never
  makes duplicates.
- **`summarize.py`** is the looped-reasoning "reflect" step: a slightly creative
  draft, a strict critique ("did you invent anything? are these the *right*
  priorities?"), then a calm final. Written to a dated file, overwritten only
  for the same day.
- **`state.py`** tracks the last run time (so only new changes are processed)
  and holds a lock so two runs can't overlap.

---

## Set it up

1. Run `setup.bat` in the main folder (once).
2. Point the stack at your real vault: open `config.json`, set
   `"vault_path": "C:/Users/you/Documents/MyVault"` (forward slashes are fine).
   Leave it as-is to use the bundled sample vault first.
3. Test immediately: run `start.bat`. Then open your vault's `_generated/`
   folder and read the freshly written review + logs.
4. Automate it: run `install-schedule.bat` (nightly at 2 AM).

---

## The other half: "chat with your brain" (AnythingLLM)

The nightly job gives you structure; AnythingLLM gives you conversation. It's a
free desktop app — no Docker, no accounts.

1. Install **AnythingLLM Desktop**: <https://anythingllm.com/desktop>
2. First-run settings:
   - **LLM Provider** → *Ollama*, Base URL `http://localhost:11434`, model =
     your chat model (e.g. `llama3.1:8b`).
   - **Embedding** → the built-in AnythingLLM embedder is fine, or *Ollama* with
     `nomic-embed-text`.
   - **Vector Database** → leave as the built-in **LanceDB** (zero setup).
3. Create a workspace called e.g. "Brain", then **upload / point it at your
   vault folder**. It chunks + embeds your notes locally into LanceDB.
4. Ask things like *"What did I decide about my finances this month?"* or
   *"Summarise all my notes on sleep."* Answers cite the source notes.

> Paste the template in `shared/prompts/system-template.md` into the workspace's
> system prompt for cleaner, more honest answers.

Keeping it fresh: re-upload changed notes periodically, or explore AnythingLLM's
folder-watch / API features. The nightly Python job is independent of this — it
reads the raw files directly, so your structured memory stays current regardless.

---

## What could go wrong → the fix

| Symptom | Cause | Fix |
|---|---|---|
| "Ollama does not seem to be running" | Ollama app off | Start Ollama, run `start.bat` again |
| Review invented things | Small model over-eager | Use a bigger model, or trust the critique pass (it catches most). Re-run |
| Duplicated tasks in the index | State file deleted/moved | Dedupe uses `_generated/.state/second_brain.json`; keep it. Safe to clear logs and re-run |
| Nightly task didn't run overnight | PC asleep / logged out | In Task Scheduler tick "Run whether logged on or not" + "Wake to run" |
| Extraction is slow | Many notes on first run | First run processes everything once; later runs only touch changed notes |
| `instructor`/JSON parse warnings | Model returned odd JSON | Harmless — it falls back automatically. Persistent? try `qwen2.5:7b` (great at JSON) |
| Nothing extracted from a note | Note had no clear tasks/etc. | Working as intended — it won't invent items |
| Two runs overlapped | Long run + scheduler fired again | Prevented automatically by the lock in `state.py` |

**Backups:** because everything the AI makes lives in `_generated/`, your normal
Obsidian/Git/Drive backup already covers it. To reset the AI's memory entirely,
delete `_generated/` — your notes are untouched and it rebuilds on the next run.
