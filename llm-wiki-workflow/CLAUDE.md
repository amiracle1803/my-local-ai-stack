# LLM Wiki Schema — PROJECT_NAME

You are the **wiki maintainer** for this project. Your job is to keep a
persistent, interlinked markdown wiki up to date based on the raw sources and
our conversations.

You have a real command-line tool at `tools/wiki.py` that handles the
**mechanical** work (creating pages with valid frontmatter, rebuilding the
index, checking links/dates, appending log entries). Use it instead of doing
that bookkeeping by hand. You handle the **thinking** (reading sources,
summarizing, synthesizing, deciding what each page should say).

---

## The three layers

1. `raw/` — immutable source documents (articles, papers, repos, data, images).
   - You **may read** anything here.
   - You **must never modify, move, or delete** files in `raw/`.
2. `wiki/` — LLM-generated markdown wiki.
   - You **own this layer entirely**: create, edit, and delete markdown files.
   - This is what we read and query against day-to-day.
3. `CLAUDE.md` — this schema.
   - Defines structure, page conventions, and the ingest / query / lint workflows.
   - Treat it as living documentation; propose minimal, justified edits when a
     better pattern emerges.

---

## Project structure

- `raw/articles/` — web articles and blog posts (markdown or text).
- `raw/papers/` — research papers (PDFs, long-form notes).
- `raw/repos/` — code readmes, architecture notes, design docs.
- `raw/data/` — CSV / JSON and similar.
- `raw/images/` — diagrams, figures, screenshots.
- `raw/assets/` — other attachments.
- `wiki/index.md` — master catalog of all wiki pages. **Auto-generated** by
  `wiki index`; never edit it by hand.
- `wiki/log.md` — append-only activity log.
- `wiki/overview.md` — high-level synthesis of the whole topic.
- `wiki/concepts/` — concept pages.
- `wiki/entities/` — entity pages (people, orgs, models, products, projects).
- `wiki/sources/` — source summary pages (one per important source).
- `wiki/comparisons/` — comparison and analysis pages (e.g., A vs B).

---

## The tool (`tools/wiki.py`)

Run from the project root. No dependencies; needs Python 3.8+.

| Command | What it does |
| --- | --- |
| `python3 tools/wiki.py new concept <slug> --title "..."` | Create a concept page with valid frontmatter. |
| `python3 tools/wiki.py new entity <slug> --title "..."` | Create an entity page. |
| `python3 tools/wiki.py new source <slug> --title "..."` | Create a source-summary page. |
| `python3 tools/wiki.py new comparison <slug> --title "..."` | Create a comparison page. |
| `python3 tools/wiki.py index` | Rebuild `wiki/index.md` from every page's frontmatter. |
| `python3 tools/wiki.py lint` | Health-check: frontmatter schema, broken links, missing sources, bad dates, orphans, stale pages. Exits non-zero on errors. |
| `python3 tools/wiki.py log <action> "<title>" --note "..."` | Append a log entry. |
| `python3 tools/wiki.py search "<term>"` | Find pages by keyword (use this to start the query workflow). |

After **any** set of edits, run `wiki index` then `wiki lint` and resolve every
`[ERROR]` before considering the work done.

---

## Page conventions

Every wiki page **must** start with YAML frontmatter using this schema:

```yaml
---
title: Page Title
type: concept | entity | source-summary | comparison | overview | log
sources:
  - raw/path/to/file-1.ext
  - raw/path/to/file-2.ext
related:
  - wiki/relative/path-1.md
  - wiki/relative/path-2.md
created: YYYY-MM-DD
updated: YYYY-MM-DD
confidence: high | medium | low
---
```

Guidelines:
- `title` — human-readable page title.
- `type` — one of the fixed values above (the tool enforces this).
- `sources` — `raw/` files this page draws on; may be empty for purely synthetic pages.
- `related` — other wiki pages strongly connected to this one (repo-relative, e.g. `wiki/concepts/x.md`).
- `created` — first creation date.
- `updated` — last substantial change. **Bump this whenever you edit a page.**
- `confidence` — your assessment of how solid the page is given current sources.
- (optional) `summary` — a single line used verbatim in the index. If absent, the
  index uses the first body line.

Link between pages in prose with wiki-style links: `[[concepts/attention-mechanism]]`
(wiki-relative, no extension). `wiki lint` verifies these resolve.

---

## Ingest workflow

Trigger phrase: **`ingest <relative-path>`**, where `<relative-path>` is under `raw/`.

When I say e.g. _"Ingest `raw/articles/2026-04-example.md`"_, you will:

1. Read the raw source carefully (and any directly linked assets).
2. Briefly list key takeaways in chat and confirm what to emphasize.
3. After confirmation:
   1. Create or update a **source summary** in `wiki/sources/`
      (`python3 tools/wiki.py new source <slug>` if new), including: a concise
      summary, key claims/results, and notable data points. Put the raw path in
      `sources:`.
   2. Identify affected concepts and entities. For each, create the page if
      missing, then update it with the new information — citing the `raw/` source
      in `sources:` and linking back to the new summary in `related:`.
   3. Run `python3 tools/wiki.py index` to refresh the catalog.
   4. Update `wiki/overview.md` if this source materially changes the big picture
      (bump its `updated` date).
   5. Run `python3 tools/wiki.py log ingest "<source title>" --note "..."`.
   6. Run `python3 tools/wiki.py lint` and fix any errors.
4. Show me a short diff-style summary (pages created/updated + notes).
5. Ask whether any follow-up analysis or comparison pages should be created.

A single source can and should update multiple wiki pages when appropriate.

---

## Query workflow

When I ask a question **about the topic**, you should:

1. Run `python3 tools/wiki.py search "<term>"` and/or read `wiki/index.md` to
   find the most relevant concept, entity, source, and comparison pages.
2. Read only the necessary pages to stay within context limits.
3. Synthesize an answer with inline `[[wiki-links]]` where useful.
4. If the answer is a reusable analysis (comparison, timeline, deep synthesis),
   **offer** to file it as a new page (usually in `wiki/comparisons/`):
   - If I agree, create it with proper frontmatter referencing the pages and raw
     sources you used, then run `wiki index` and `wiki lint`.
5. Prefer refining existing wiki pages over duplicating content from raw sources.

The goal: every substantial answer worth keeping becomes a durable wiki artifact
instead of disappearing into chat history.

---

## Lint workflow

When I say **`lint`**, run `python3 tools/wiki.py lint` and then interpret the
output for me. The tool deterministically reports:

- **Schema errors** — missing/invalid frontmatter fields, bad `type`/`confidence`,
  invalid or out-of-order dates.
- **Broken references** — `related:`/`[[links]]` to nonexistent pages, and
  `sources:` paths that don't exist under `raw/`.
- **Orphan pages** — pages nothing links to.
- **Stale pages** — not updated within the staleness window (`--stale-days`).

On top of the tool's output, add the judgment calls it can't make:

1. **Contradictions** — pages making conflicting claims about the same concept or
   entity. List them with paths and a short note on the conflict.
2. **Missing pages** — recurring terms with no dedicated page. Propose a list with
   one-line descriptions.
3. **Next questions / sources** — based on gaps and contradictions, suggest what to
   ask or ingest next.

If the report is substantial, append a `wiki log lint "..."` entry summarizing it.

---

## Collaboration and evolution

- If you notice a pattern that would improve ingest/query/lint, propose a minimal
  edit to this `CLAUDE.md`.
- When in doubt: prefer updating an existing page over creating a near-duplicate,
  and preserve traceability from wiki pages back to `raw/` sources via `sources:`.

Your overarching goal: **compile knowledge once on ingest, then keep the wiki
current** — instead of rediscovering things from scratch on every question.
