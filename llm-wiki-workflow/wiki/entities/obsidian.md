---
title: Obsidian
type: entity
sources:
  - raw/articles/karpathy-llm-wiki-complete-guide.md
related:
  - wiki/concepts/llm-wiki-workflow.md
  - wiki/entities/qmd-search.md
  - wiki/sources/karpathy-llm-wiki-complete-guide.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Local-first markdown knowledge management app with bidirectional links, graph view, and a plugin ecosystem — the recommended viewer/IDE for the LLM wiki layer.
---

# Obsidian

Local-first markdown knowledge management application. In the [[concepts/llm-wiki-workflow]], Obsidian serves as the "IDE" — the viewer and navigator for the wiki layer while the LLM acts as the programmer.

## Background

Obsidian stores all notes as plain markdown files in a local folder called a "vault." It supports bidirectional wiki-links, a visual graph view of all page connections, YAML frontmatter, and an extensive plugin ecosystem. All data stays on-device by default.

Key tools relevant to the LLM wiki:

**Obsidian Web Clipper** — a browser extension (Chrome, Firefox, Safari, Edge, Brave, Arc) that converts web articles to clean markdown with YAML frontmatter (author, date, source URL, tags). The primary tool for getting sources into `raw/articles/`.

**Graph view** — renders all wiki pages as nodes and all wiki-links as edges. Hub pages appear large; orphan pages appear isolated. The best way to see the shape of the wiki and spot gaps.

**Marp Slides plugin** — renders markdown files as slide decks (exports to HTML, PDF, PowerPoint). Useful for generating presentations directly from wiki content.

**Dataview plugin** — runs SQL-like queries over page frontmatter, enabling dynamic dashboards (e.g., "list all concept pages with more than 5 sources, sorted by confidence").

**Image download tip:** In Settings → Files and links, set "Attachment folder path" to `raw/assets/`. Bind "Download attachments for current file" to a hotkey (e.g. Ctrl+Shift+D) so all images in a clipped article are saved locally — enabling the LLM to view them directly.

## Relevance

Karpathy's daily setup: "I have the LLM agent open on one side and Obsidian open on the other. The LLM makes edits based on our conversation, and I browse the results in real time — following links, checking the graph view, reading the updated pages."

Obsidian is optional — any markdown viewer works — but its graph view and plugin ecosystem make it the best match for navigating a heavily cross-linked wiki. For teams, the vault is just a git repository of markdown files.
