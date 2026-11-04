---
title: "Atlas: Creative Studio Agent"
type: entity
sources: []
related:
  - wiki/entities/agent-atlas-system.md
  - wiki/concepts/layered-agent-architecture.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Generates structured documents — reports, proposals, marketing copy, technical write-ups — using LLM with user-provided template and tone preferences.
---

# Atlas: Creative Studio Agent

**Layer:** Platform | **ID:** `creative_studio`

The Creative Studio agent handles all long-form document generation. Given a brief, it produces structured markdown documents (reports, proposals, README files, write-ups) using a tone and format appropriate to the request.

## Document types

- Technical reports and research summaries
- Project proposals and PRDs
- Marketing and communication copy
- README and documentation files
- Meeting summaries and action items

## Output format

Always returns structured markdown with clear headings, suitable for:
- Direct use in Obsidian
- Export as PDF
- Inclusion in wiki pages

## Inputs / Outputs

| | |
|---|---|
| **Inputs** | `brief`, `doc_type`, `tone`, `length`, `template` (optional) |
| **Outputs** | `document` (markdown), `title`, `suggested_path` |
| **Message type** | `create_doc` |

## Memory integration
Reads from Memory Agent to personalize documents to user's writing style and past project context.

## Connections
- Called by: [[entities/atlas-orchestrator]], [[entities/atlas-background-runtime]]
- Saves output to: Obsidian via [[entities/atlas-obsidian-brain]] (optional)
