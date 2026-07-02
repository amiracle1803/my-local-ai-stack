# LLM Wiki Workflow

A small, self-contained knowledge-base workflow you run **locally in VS Code**.
You drop sources into `raw/`, and an LLM agent (Claude) maintains an interlinked
markdown wiki under `wiki/` — governed by `CLAUDE.md` and backed by a real
command-line tool that keeps everything valid.

```
raw/    immutable sources you provide        (never edited by the agent)
wiki/   generated, interlinked markdown       (the agent owns this)
CLAUDE.md   the schema + ingest/query/lint workflow the agent follows
tools/wiki.py   deterministic CLI: new, index, lint, log, search
```

The split that makes this reliable: the **agent does the thinking**
(summarizing, synthesizing) and the **tool does the bookkeeping** (valid
frontmatter, the index, link/date/source checks). The bookkeeping is plain
Python with **no dependencies**, so it just runs.

---

## Requirements

- **Python 3.8+** (`python3 --version`). That's it — no `pip install`, no Node.
- **VS Code** (optional but recommended; the project ships with tasks).
- An LLM agent that reads `CLAUDE.md` (e.g. Claude) to run the ingest/query/lint
  *thinking* steps. The CLI works on its own regardless.

---

## Quick start

1. Unzip this folder and open it in VS Code (`File → Open Folder`).
2. When prompted, install the recommended extensions (Markdown All in One, YAML).
3. Open a terminal (`` Ctrl+` ``) and confirm the tool runs:

   ```bash
   python3 tools/wiki.py lint
   ```

   You should see `[OK] 5 page(s) checked, no issues.` — the project ships with a
   small example wiki (it documents *itself*) so everything is live immediately.

4. Look at `wiki/index.md` and the example pages under `wiki/concepts/`,
   `wiki/entities/`, etc. to see the shape of a page.

> The example pages are just a demo. Delete them when you start your own topic,
> then run `python3 tools/wiki.py index` to regenerate the catalog.

---

## The tool

Run from the project root. (`./wiki-cli <cmd>` on macOS/Linux or
`wiki-cli.bat <cmd>` on Windows are shortcuts for `python3 tools/wiki.py <cmd>`.)

| Command | Does |
| --- | --- |
| `python3 tools/wiki.py new concept <slug> --title "..."` | New concept page with valid frontmatter. (`entity` / `source` / `comparison` also work.) |
| `python3 tools/wiki.py index` | Rebuild `wiki/index.md` from every page's frontmatter. |
| `python3 tools/wiki.py lint` | Check the whole wiki; **exits non-zero** if there are errors. |
| `python3 tools/wiki.py log ingest "Title" --note "..."` | Append a timestamped activity-log entry. |
| `python3 tools/wiki.py search "term"` | List pages matching a keyword. |
| `python3 tools/wiki.py init <new-dir>` | Scaffold a *separate* new wiki project elsewhere. |

### What `lint` checks

**Errors** (must fix — these fail the exit code):
- missing or malformed frontmatter
- missing required fields (`title`, `type`, `created`, `updated`)
- invalid `type` or `confidence` value
- dates that aren't real `YYYY-MM-DD`, or `updated` earlier than `created`
- `related:`/`[[links]]` pointing to a page that doesn't exist
- `sources:` pointing to a file that doesn't exist under `raw/`

**Warnings** (worth reviewing — don't fail the build):
- orphan pages (nothing links to them; `index.md` doesn't count, `overview.md` does)
- stale pages (not updated within `--stale-days`, default 90)
- nearly-empty page bodies

---

## Using it in VS Code

Press **`Ctrl/Cmd+Shift+P → Tasks: Run Task`** and pick:

- **Wiki: Lint** — run the health check (also the default *test* task, `Ctrl/Cmd+Shift+P → Run Test Task`).
- **Wiki: Rebuild Index** — regenerate `wiki/index.md`.
- **Wiki: Index + Lint** — both, in order (the default *build* task, `Ctrl/Cmd+Shift+B`).
- **Wiki: New Page** — prompts for type/slug/title and creates the page.
- **Wiki: Search** — prompts for a term.

These are defined in `.vscode/tasks.json` and work on Windows, macOS, and Linux.

---

## The day-to-day loop

1. **Add a source** — drop a file into the right `raw/` subfolder (it stays untouched).
2. **Ingest** — tell the agent: `ingest raw/articles/your-file.md`. Following
   `CLAUDE.md`, it summarizes the source, updates the affected concept/entity
   pages, rebuilds the index, logs the change, and lints.
3. **Query** — ask the agent a question about your topic. It reads the wiki first
   and offers to file reusable answers as new pages.
4. **Lint** — run **Wiki: Lint** (or `lint`) regularly and fix anything flagged.

Start small — about 10 sources on a single topic — then scale once the loop is
proving useful.

---

## Optional: run lint automatically before each commit

If you keep this in git, add a pre-commit hook so a broken wiki can't be committed:

```bash
printf '#!/usr/bin/env sh\npython3 tools/wiki.py lint\n' > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

---

## Layout

```
.
├── CLAUDE.md                 # schema + workflow the agent follows
├── README.md                 # this file
├── wiki-cli / wiki-cli.bat   # shortcuts for python3 tools/wiki.py
├── .vscode/                  # tasks + recommended extensions
├── tools/
│   └── wiki.py               # the CLI (zero dependencies)
├── raw/                      # immutable sources (articles, papers, repos, data, images, assets)
└── wiki/
    ├── index.md              # auto-generated catalog (don't hand-edit)
    ├── log.md                # append-only activity log
    ├── overview.md           # high-level synthesis / hub
    ├── concepts/  entities/  sources/  comparisons/
```
