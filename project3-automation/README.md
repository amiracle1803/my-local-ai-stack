# Project 3 — Always-On Automation

**Goal:** things that run on their own — a research digest from your feeds, a
daily digest of what changed in your code repos, and (optionally) hourly email
triage. All local, all free.

Three independent pieces — use any subset:

| Piece | File | Needs | Runs via |
|---|---|---|---|
| Research digest | `research.py` | feeds.txt | Task Scheduler (Python) |
| Repo digest | `repo_digest.py` | `repos` in config.json | Task Scheduler (Python) |
| Email triage | `n8n/` | Docker + n8n | n8n (see `n8n/README-email.md`) |

The first two are plain Python (nothing to babysit). Email triage is the only
part that uses Docker, and it's optional.

---

## Piece by piece

### Research digest (`research.py`)
```
feeds.txt ──► feedparser finds NEW entries ──► fetch each page (trafilatura)
          ──► local model summarises ──► append to _generated/Research/<date> Digest.md
```
- New-entry tracking lives in state `research`, so you never re-summarise the
  same article. Capped per run so a firehose feed can't hang it.
- Fetching uses `shared/lib/webfetch.py` (trafilatura by default; optional
  `crawl4ai` for JS-heavy sites).

### Repo digest (`repo_digest.py`)
```
for each repo in config.json "repos":
    git log since last run  +  scan changed files for TODO/FIXME
    ──► local model writes a short "what changed / needs attention" note
    ──► _generated/Repos/<repo> Digest.md
```
- **Read-only.** It runs `git log` and reads file text. It never edits code.
- Remembers the last commit per repo in state `repos`.

### Email triage (`n8n/`)
Watches your inbox, classifies each mail with the local model, pings you about
important ones. Full walkthrough in **`n8n/README-email.md`** (manual steps are
authoritative; `email-triage.workflow.json` is an importable starting point).

---

## Set it up

1. Run `setup.bat` in the main folder (once).
2. **Research:** copy `feeds.example.txt` → `feeds.txt`, add your RSS URLs.
3. **Repos:** in `config.json` set e.g. `"repos": ["C:/code/my-project"]`.
4. Test now: run `start.bat` → pick a job.
5. Automate: run `install-schedule.bat` (research every 3h, repo digest daily 6 PM).
6. Email triage (optional): follow `n8n/README-email.md`.

---

## Coding tasks: use OpenCode interactively (don't automate edits)

Letting an AI rewrite your code unattended is a great way to wake up to a broken
repo. So repo work is split:

- **Automated + safe:** the read-only repo *digest* above.
- **Interactive:** for actual changes, use **OpenCode** (free, MIT). Install it,
  point it at your local model with `opencode-config.example.json`, and it edits
  files locally and shows you a **diff to approve** before anything lands. Ask it
  things like *"find and fix the failing test in this repo."*

OpenCode install + docs: <https://opencode.ai> · <https://github.com/sst/opencode>

---

## What could go wrong → the fix

| Symptom | Cause | Fix |
|---|---|---|
| "No feeds configured" | No `feeds.txt` | Copy `feeds.example.txt` → `feeds.txt` |
| A feed returns nothing | Bad/renamed feed URL | Open the URL in a browser; fix or remove it |
| "could not fetch article body" | Site blocks bots / JS-only | Different source, or install optional `crawl4ai` + `playwright install chromium` |
| Repo digest: "not a git repo" | Path has no `.git` | Point at the repo root; run `git status` there to confirm |
| Repo digest empty | No new commits since last run | Expected. Make a commit and re-run |
| Duplicate research entries | State cleared | Tracking is in `_generated/.state/research.json` — keep it |
| Scheduled jobs didn't run | Logged out / PC asleep | Task Scheduler → "Run whether logged on or not" + "Wake to run" |
| Email triage: connection refused | Ollama unreachable from Docker | `OLLAMA_HOST=0.0.0.0` + `host.docker.internal` (see n8n guide) |

**Redundancy:** research and repo digests are fully independent — one failing
never affects the other, and neither depends on n8n. Every result is written to
your vault, and all runs log to `*.log` next to the scripts.
