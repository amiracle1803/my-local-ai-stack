---
title: "Karpathy's LLM Wiki — Complete Guide (Agentpedia)"
type: source-summary
sources:
  - raw/articles/karpathy-llm-wiki-complete-guide.md
related:
  - wiki/concepts/llm-wiki-workflow.md
  - wiki/concepts/idea-file.md
  - wiki/concepts/memex.md
  - wiki/comparisons/wiki-vs-rag.md
  - wiki/entities/andrej-karpathy.md
  - wiki/entities/obsidian.md
  - wiki/entities/qmd-search.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Deep-dive covering Karpathy's three-layer LLM wiki pattern — raw sources, generated wiki, schema — with tool stack, operations, implementation stages, and Memex connection.
---

# Karpathy's LLM Wiki — Complete Guide (Agentpedia)

Agentpedia's comprehensive breakdown of Andrej Karpathy's April 2026 GitHub gist describing the LLM Wiki pattern: a persistent, compounding knowledge base maintained by an LLM agent rather than re-derived at query time.

## Summary

Karpathy introduced the concept via a viral tweet (April 3, 2026) followed by a GitHub gist "idea file" (April 4, 2026). The core claim: traditional RAG re-discovers knowledge from scratch on every query; an LLM wiki compiles knowledge once on ingest and keeps it current — compound interest for information. The wiki sits between you and raw sources, pre-digested and cross-referenced.

The architecture has three layers: immutable `raw/` sources, LLM-owned `wiki/` markdown pages, and a schema file (CLAUDE.md / AGENTS.md) that governs every session. Three operations drive the system: **ingest** (compile a raw source into wiki pages), **query** (read the wiki and file durable answers), **lint** (health-check for contradictions, orphans, and gaps).

## Key claims / results

- "The knowledge is compiled once and then kept current, not re-derived on every query."
- At moderate scale (~100 sources, ~hundreds of pages) `index.md` + the LLM is enough for retrieval — no vector database needed.
- A single ingest can touch 10–15 wiki pages (summary, concepts, entities, comparisons, index, log).
- LLMs succeed where human-maintained wikis fail: "LLMs don't get bored, don't forget to update a cross-reference, and can touch 15 files in one pass."
- "Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase."
- The "idea file" is a new open-source format: share the pattern, not the implementation.

## Notable data points

- Karpathy's personal research wiki: ~100 articles, ~400,000 words, single ML research topic.
- The GitHub gist accumulated 43,000+ stars in one week.
- `qmd` by Tobi Lutke (Shopify CEO) adds BM25 + vector + LLM re-ranking over markdown, all on-device.
- Vannevar Bush's 1945 Memex concept inspired hypertext and the Web — the missing piece (who does maintenance) is now solved by LLMs.

## Tool stack from this source

| Tool | Role |
|------|------|
| Obsidian | Wiki viewer with graph view |
| Obsidian Web Clipper | Clip articles to markdown in `raw/` |
| qmd | Local markdown search (BM25 + vector + LLM) |
| Marp | Generate slide decks from wiki content |
| Dataview | SQL-like queries over frontmatter |
| Git | Version control for the wiki |

## Implementation stages

1. **Scaffold** — folder structure, schema file, skeleton index and log
2. **Manual workflows** — stabilize ingest/query/lint by hand
3. **Python CLI agent** — `config.py`, `fs.py`, `prompts.py`, `agent.py`, `main.py`
4. **Automation** — file watcher + cron lint
5. **Browser integration** — web clipper to `raw/articles/`, tag taxonomy
