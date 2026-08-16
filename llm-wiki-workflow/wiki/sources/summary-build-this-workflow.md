---
title: "Source: Build This Workflow notes"
type: source-summary
sources:
  - raw/articles/build-this-workflow-notes.md
related:
  - wiki/concepts/llm-wiki-workflow.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Notes describing the three-layer wiki architecture and the ingest/query/lint operations.
---

# Source: Build This Workflow notes

Notes describing the three-layer wiki architecture and its core operations.

## Summary

Defines `raw/` (immutable sources), `wiki/` (generated markdown), and a schema file that tells the agent how to maintain consistency.

## Key claims / results

- Compile knowledge on ingest; keep the wiki current rather than re-deriving.
- Start small (~10 sources on one topic), then scale once the workflow proves useful.

## Notable data points

- Three layers, three core commands: ingest, query, lint. Expanded in [[concepts/llm-wiki-workflow]].
