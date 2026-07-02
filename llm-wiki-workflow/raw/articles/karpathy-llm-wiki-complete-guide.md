# Karpathy's LLM Wiki: The Complete Guide

**Source:** Agentpedia — AI Deep Dive  
**Published:** April 4, 2026  
**Author:** Agentpedia editorial team  
**Original file:** long guide.txt (project root)

---

## 1. The Viral Moment

On April 3, 2026, Andrej Karpathy — co-founder of OpenAI, former AI lead at Tesla, and the person who coined "vibe coding" — posted a tweet titled "LLM Knowledge Bases" describing how he now uses LLMs to build personal knowledge wikis instead of just generating code. That tweet went massively viral. The next day, he followed up with an "idea file" — a GitHub gist that lays out the complete architecture, philosophy, and tooling behind the concept.

---

## 2. Idea Files: A New Format for the Agent Era

Karpathy's definition:

> "The idea of the idea file is that in this era of LLM agents, there is less of a point/need of sharing the specific code/app, you just share the idea, then the other person's agent customizes & builds it for your specific needs."

Instead of sharing a GitHub repo (implementation-specific), you share a structured description of the pattern, designed to be interpreted by an LLM agent. The agent adapts it to the user's environment, tools, and preferences. This is **open ideas rather than open source**.

Karpathy says the gist is "intentionally kept a little bit abstract/vague because there are so many directions to take this in." The document's last line: "The document's only job is to communicate the pattern. Your LLM can figure out the rest."

### How to Use the Idea File

1. Copy the gist content (the full `llm-wiki.md` file)
2. Paste it into your LLM agent's context (Claude Code, Codex, OpenCode, or any agentic IDE)
3. Tell the agent: "Set up an LLM Wiki based on this idea file for [your topic]"
4. The agent will create the directory structure, write the schema file, and guide you through first ingestion

---

## 3. The Core Idea: Wiki Beats RAG

### The RAG Problem

Karpathy writes: "Most people's experience with LLMs and documents looks like RAG: you upload a collection of files, the LLM retrieves relevant chunks at query time, and generates an answer."

The problem: "The LLM is rediscovering knowledge from scratch on every question. There's no accumulation."

### The Wiki Solution

"Instead of just retrieving from raw documents at query time, the LLM incrementally builds and maintains a persistent wiki — a structured, interlinked collection of markdown files that sits between you and the raw sources."

The key line: **"The knowledge is compiled once and then kept current, not re-derived on every query."**

### Comparison Table

| Dimension | Traditional RAG | LLM Wiki |
|-----------|----------------|----------|
| When knowledge is processed | At query time (every question) | At ingest time (once per source) |
| Cross-references | Discovered ad-hoc per query | Pre-built and maintained |
| Contradictions | May not be noticed | Flagged during ingestion |
| Knowledge accumulation | None — starts fresh each query | Compounds with every source |
| Output format | Chat responses (ephemeral) | Persistent markdown files (durable) |
| Who maintains it | The system (black box) | The LLM (transparent, editable) |
| Human role | Upload and query | Curate, explore, and question |
| Examples | NotebookLM, ChatGPT uploads | Karpathy's LLM Wiki pattern |

### The Human-LLM Division of Labor

Karpathy: "You never (or rarely) write the wiki yourself — the LLM writes and maintains all of it. You're in charge of sourcing, exploration, and asking the right questions."

His daily setup: "I have the LLM agent open on one side and Obsidian open on the other."

The analogy: **"Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase."**

---

## 4. The Three-Layer Architecture

### Layer 1: Raw Sources

"Your curated collection of source documents. Articles, papers, images, data files. These are **immutable** — the LLM reads from them but never modifies them. This is your source of truth."

```
raw/
  articles/   web articles and blog posts
  papers/     research papers (PDFs, long-form notes)
  repos/      code readmes, architecture notes
  data/       CSV/JSON and similar
  images/     diagrams, figures, screenshots
  assets/     downloaded image attachments
```

### Layer 2: The Wiki

"A directory of LLM-generated markdown files. Summaries, entity pages, concept pages, comparisons, an overview, a synthesis. **The LLM owns this layer entirely.**"

```
wiki/
  index.md         Master catalog of all pages
  log.md           Chronological activity record
  overview.md      High-level synthesis
  concepts/        One page per concept
  entities/        People, orgs, models, products
  sources/         One summary page per source
  comparisons/     Comparison and analysis pages
```

### Layer 3: The Schema

"A document (e.g. CLAUDE.md for Claude Code or AGENTS.md for Codex) that tells the LLM how the wiki is structured, what the conventions are, and what workflows to follow."

Karpathy adds: "You and the LLM co-evolve this over time as you figure out what works for your domain."

**Why the Schema Matters:** Without a schema, every session starts from zero. With it, the LLM becomes a systematic wiki maintainer that follows consistent rules across sessions.

---

## 5. Operations: Ingest, Query, Lint

### Operation 1: Ingest

"You drop a new source into the raw collection and tell the LLM to process it. A single source might touch 10-15 wiki pages."

A single ingest might:
- Create a new summary page for the paper
- Update concept pages with new information or variants
- Update scaling/benchmark pages with new data
- Update entity pages for authors/organizations
- Flag contradictions with existing claims
- Add links from existing pages
- Update the index
- Log the ingest

Karpathy: "I prefer to ingest sources one at a time and stay involved — I read the summaries, check the updates, and guide the LLM on what to emphasize."

### Operation 2: Query

"You ask questions against the wiki. The LLM searches for relevant pages, reads them, and synthesizes an answer with citations."

Key insight: **"Good answers can be filed back into the wiki as new pages."** This way explorations compound in the knowledge base just like ingested sources do.

The compounding loop: sources get ingested → queries generate insights → best insights are filed back as wiki pages.

### Operation 3: Lint

"Periodically, ask the LLM to health-check the wiki. Look for: contradictions between pages, stale claims, orphan pages, important concepts lacking their own page, missing cross-references."

He adds: "The LLM is good at suggesting new questions to investigate and new sources to look for."

---

## 6. Indexing and Logging

### index.md: The Content Catalog

"index.md is content-oriented. It's a catalog of everything in the wiki — each page listed with a link, a one-line summary, and optionally metadata. Organized by category."

Key insight: "When answering a query, the LLM reads the index first to find relevant pages, then drills into them. This works surprisingly well at moderate scale (~100 sources, ~hundreds of pages) and **avoids the need for embedding-based RAG infrastructure.**"

### log.md: The Activity Timeline

"log.md is chronological. It's an append-only record of what happened and when — ingests, queries, lint passes."

Practical tip: "If each entry starts with a consistent prefix (e.g. `## [2026-04-02] ingest | Article Title`), the log becomes parseable with simple unix tools."

---

## 7. The Tool Stack

| Tool | Role | Required? |
|------|------|-----------|
| Obsidian | IDE / viewer for browsing the wiki | Recommended (any markdown viewer works) |
| Obsidian Web Clipper | Ingestion: clip web articles to markdown | Recommended for web sources |
| qmd | Local markdown search engine (BM25 + vector + LLM re-ranking) | Optional (index.md works at small scale) |
| Marp | Output: generate slide decks from wiki | Optional |
| Dataview | Query frontmatter for dashboards | Optional |
| Git | Version control for the wiki | Recommended |
| LLM Agent | Wiki maintainer (Claude Code, Codex, etc.) | Required |

### qmd (by Tobi Lutke, CEO of Shopify)

Local search engine for markdown files with hybrid BM25/vector search and LLM re-ranking, all on-device via node-llama-cpp with GGUF models. Has both a CLI and an MCP server.

```bash
npm install -g @tobilu/qmd
qmd collection add ./wiki --name my-research
qmd search "mixture of experts routing"       # BM25
qmd vsearch "how do sparse models handle X"  # semantic
qmd query "tradeoffs of top-k routing"       # hybrid + LLM re-rank
qmd mcp                                       # start as MCP server
```

### Obsidian Web Clipper
Browser extension that converts web articles to markdown with YAML frontmatter (author, date, source URL, tags).

**Image tip:** In Settings → Files and links, set attachment folder to `raw/assets/`. Bind "Download attachments" to a hotkey to download all images locally.

### Marp
Markdown-based slide deck format. Useful for generating presentations directly from wiki content.

### Dataview
Obsidian plugin that runs SQL-like queries over page frontmatter.

```sql
TABLE length(sources) AS "Sources", confidence
FROM "wiki/concepts"
SORT length(sources) DESC
```

---

## 8. Use Cases

1. **Personal Knowledge Base** — goals, health, psychology, reading notes. Build up a structured picture of yourself over time.
2. **Research** — going deep on a topic over weeks or months, ~100 articles, evolving thesis.
3. **Reading a Book** — file each chapter, build pages for characters, themes, plot threads. Like a fan wiki (e.g. Tolkien Gateway) built personally.
4. **Business / Team** — fed by Slack threads, meeting transcripts, project documents, customer calls.
5. **Everything Else** — competitive analysis, due diligence, trip planning, course notes, hobby deep-dives.

---

## 9. Step-by-Step Implementation Guide

### Stage 0: Tooling Choice
- **Editor:** Obsidian (ideal for graph view) or VS Code
- **LLM runtime:** Local (Ollama, KoboldCpp, vLLM) or Cloud (OpenAI, Claude, Gemini)
- **Orchestration:** Manual (paste into IDE-like LLM), Semi-automated (Python CLI), Full (file watcher + cron)

### Stage 1: Scaffolding the Wiki
Create directory structure, schema file, skeleton index.md and log.md, hook into editor.

### Stage 2: Manual Workflows with an IDE LLM
Before writing code, stabilize the workflow: ingest a sample source, test query-with-save, test lint pass. Effectively dogfooding the design by hand before automating.

### Stage 3: Build a Local CLI Agent
Core idea: Python CLI that knows the wiki root, reads schema+index+log, calls the LLM with filesystem context, and applies suggested patches safely.

High-level modules:
- `config.py` — load env vars (WIKI_ROOT, model endpoint, API keys)
- `fs.py` — read/write markdown files, restrict writes to `wiki/**, index.md, log.md`
- `prompts.py` — template prompts for ingest, query-with-save, lint
- `agent.py` — core functions: `run_ingest(path)`, `run_query_save(question)`, `run_lint()`
- `main.py` / CLI — commands: `llmwiki ingest raw/papers/sample.pdf`, `llmwiki query "..." --save`, `llmwiki lint`

### Stage 4: Automation (Watcher + Cron)
- File watcher (Python `watchdog`) monitors `raw/` and auto-runs ingest on new files
- Scheduled lint passes via cron or Windows Task Scheduler
- Optional minimal local web panel or TUI

### Stage 5: Browser and Workflow Integration
- Web clipper → `raw/articles/` or a staging folder like `00-inbox/`
- Tag conventions in schema (e.g. `#anime-gen`, `#stats2`, `#ecom`)
- Graph-based review in Obsidian

---

## 10. The Memex Connection (1945)

Karpathy closes with a historical reference:

> "The idea is related in spirit to Vannevar Bush's Memex (1945) — a personal, curated knowledge store with associative trails between documents. Bush's vision was closer to this than to what the web became: private, actively curated, with the connections between documents as valuable as the documents themselves. **The part he couldn't solve was who does the maintenance. The LLM handles that.**"

Vannevar Bush's 1945 Atlantic article "As We May Think" described the Memex: a desk-sized machine where an individual could store all their books and records on microfilm, search them rapidly, and create associative trails.

Bush's insight: the human mind works by association, not alphabetical order. The Memex would let you create your own paths through knowledge.

Memex inspired: Douglas Engelbart (mouse + personal computing), Ted Nelson (coined "hypertext"), Tim Berners-Lee (World Wide Web).

Why wikis maintained by LLMs succeed where human-maintained wikis fail: "The tedious part of maintaining a knowledge base is not the reading or the thinking — it's the bookkeeping. Humans abandon wikis because the maintenance burden grows faster than the value. **LLMs don't get bored, don't forget to update a cross-reference, and can touch 15 files in one pass.**"

---

## 11. Community Ideas from the Gist

**The .brain Folder Pattern:** A `.brain` folder at project root with `index.md`, `architecture.md`, `decisions.md`, `changelog.md`, `deployment.md` as persistent memory across AI sessions. Rule: "Read .brain before making changes. Update .brain after making changes. Never commit it to git."

**Inter-Agent Communication via Gists:** Using GitHub gists as communication channels between different AI agents — mid-development, push gists with diagrams and context, then pass between different AI frontends.

**Append-and-Review Note:** Karpathy's 2025 blog post on `karpathy.bearblog.dev` described an append-only notes file that gets periodically reviewed and reorganized. The LLM Wiki is the evolved version.

**Team Knowledge Sharing:** The wiki is just a git repo — push to shared repository, team members browse in Obsidian.

---

## 12. What This Means

The "Idea File" as a New Open Source Format: instead of sharing code (implementation-specific), share a structured description of the pattern designed to be interpreted by an LLM agent.

Karpathy's call to action: "Don't overthink the setup. Don't wait for someone to build the perfect tool. Copy the gist, paste it to your agent, and start with one topic and 10 sources. The LLM will figure out the directory structure, the page formats, the frontmatter schema. You provide the sources and the questions. The wiki builds itself."

---

## Agent Platform Schema File Names

| Platform | Schema Filename |
|----------|----------------|
| Claude Code | CLAUDE.md |
| OpenAI Codex | AGENTS.md |
| OpenCode | OPENCODE.md |
| Cursor, Windsurf, etc. | Each has its own convention |
