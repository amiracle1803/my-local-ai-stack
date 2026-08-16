---
title: Idea File
type: concept
sources:
  - raw/articles/karpathy-llm-wiki-complete-guide.md
related:
  - wiki/concepts/llm-wiki-workflow.md
  - wiki/entities/andrej-karpathy.md
  - wiki/sources/karpathy-llm-wiki-complete-guide.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: A portable natural-language document describing a pattern (not an implementation), designed to be instantiated by an LLM agent for each user's specific environment.
---

# Idea File

A new format for sharing knowledge in the agent era: instead of shipping a GitHub repo, you share a structured natural-language description of a pattern that an LLM agent can instantiate for the recipient's exact setup.

## Details

Coined by [[entities/andrej-karpathy]] when publishing the [[concepts/llm-wiki-workflow]] as a GitHub gist (April 4, 2026).

His definition: "The idea of the idea file is that in this era of LLM agents, there is less of a point/need of sharing the specific code/app, you just share the idea, then the other person's agent customizes & builds it for your specific needs."

### Why idea files beat shared repos

A GitHub repo is tied to the author's stack. An idea file is portable: paste it into your agent's context, describe your environment, and the agent builds a version calibrated to you. Karpathy left the gist "intentionally a little bit abstract/vague" — vagueness is a feature that leaves room for the agent to adapt.

### How to use one

1. Copy the idea file content.
2. Paste into your LLM agent's context (Claude Code, Codex, OpenCode, Cursor, etc.).
3. Tell the agent: "Set up an LLM Wiki based on this idea file for [your topic]."
4. The agent creates the directory structure, schema file, and guides you through first ingestion.

### Open ideas vs. open source

The idea file is a new kind of open source — **open ideas** rather than open code. The gist has a Discussion tab where people propose variations, turning it into a collaborative idea space. The CLAUDE.md in this project is itself an idea file.

## Why it matters

As LLM agents become universal, the bottleneck shifts from "can the AI build this?" to "does anyone have a good description of what to build?" Idea files are that description layer — the format that makes pattern knowledge portable and agent-readable.
