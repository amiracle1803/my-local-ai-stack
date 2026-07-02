---
title: LLM Wiki Workflow
type: concept
sources:
  - raw/articles/build-this-workflow-notes.md
  - raw/articles/karpathy-llm-wiki-complete-guide.md
related:
  - wiki/concepts/retrieval-augmented-generation.md
  - wiki/concepts/idea-file.md
  - wiki/concepts/memex.md
  - wiki/sources/summary-build-this-workflow.md
  - wiki/sources/karpathy-llm-wiki-complete-guide.md
  - wiki/comparisons/wiki-vs-rag.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Three-layer knowledge system — immutable raw sources, a generated markdown wiki, and a schema that governs ingest/query/lint. Knowledge is compiled once on ingest, not re-derived on every query.
---

# LLM Wiki Workflow

A three-layer knowledge system: immutable raw sources, an LLM-generated markdown wiki, and a schema file (`CLAUDE.md`) that governs how the wiki is maintained across sessions.

Introduced by Andrej Karpathy (April 2026). Core claim: traditional RAG re-derives knowledge from scratch on every question; a wiki compiles it once and keeps it current. See [[comparisons/wiki-vs-rag]] for the full tradeoff breakdown.

## The Three Layers

**Layer 1 — Raw sources (`raw/`):** Your curated, immutable source documents — articles, papers, repos, data, images. The LLM may read anything here but must never modify, move, or delete files.

**Layer 2 — The wiki (`wiki/`):** LLM-generated markdown pages — summaries, concept pages, entity pages, comparisons, an overview, an index, and a log. The LLM owns this layer entirely. It creates pages, updates them when new sources arrive, and maintains cross-references.

**Layer 3 — The schema (`CLAUDE.md`):** A document that tells the LLM how the wiki is structured, what the conventions are, and what workflows to follow. Without a schema, every session starts from zero. With one, the LLM becomes a disciplined wiki maintainer that follows consistent rules across sessions.

Karpathy: "You and the LLM co-evolve this over time as you figure out what works for your domain."

## The Three Operations

### Ingest
Trigger: `ingest raw/path/to/file`.

The LLM reads the raw source, discusses key takeaways, then: creates/updates a source summary in `wiki/sources/`; identifies and updates all affected concept and entity pages; updates `wiki/index.md`; updates `wiki/overview.md` if the big picture changed; appends to `wiki/log.md`.

A single ingest can touch 10–15 wiki pages. Karpathy: "I prefer to ingest sources one at a time and stay involved."

### Query
Trigger: any question about the topic.

The LLM reads `wiki/index.md`, drills into relevant pages, and synthesizes an answer. Key insight: **good answers are filed back into the wiki as new pages** (usually in `wiki/comparisons/`). This way explorations compound in the knowledge base just like ingested sources do.

### Lint
Trigger: `lint`.

Periodic health check: broken links, missing frontmatter, orphan pages, stale pages, contradictions, missing concept pages for recurring terms.

## Special Files

**`wiki/index.md`** — content-oriented catalog. Each page listed with a one-line summary. The LLM reads this first when answering queries. At moderate scale (~100 sources, ~hundreds of pages), a well-maintained index file replaces the need for a vector database.

**`wiki/log.md`** — append-only chronological record of every ingest, query, and lint pass. Consistent format (e.g. `## [YYYY-MM-DD] ingest | title`) makes it parseable with simple tools.

## Why It Matters

Knowledge is compiled once and kept current, instead of being re-derived from raw sources on every question.

The analogy: **"Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase."**

LLMs succeed where human-maintained wikis fail because maintenance cost is near zero: "LLMs don't get bored, don't forget to update a cross-reference, and can touch 15 files in one pass."

Related concepts: [[concepts/idea-file]] (the pattern of sharing this as a portable document) and [[concepts/memex]] (the 1945 predecessor that solved everything except maintenance).

## Use Cases

- Personal knowledge base (goals, health, reading notes, self-improvement)
- Deep research over weeks or months with an evolving thesis
- Reading a book chapter-by-chapter, building a companion wiki
- Business team wiki fed by Slack threads, meeting transcripts, customer calls
- Competitive analysis, due diligence, course notes, hobby deep-dives
