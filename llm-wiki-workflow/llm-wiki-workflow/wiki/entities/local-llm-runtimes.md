---
title: Local LLM Runtimes
type: entity
sources: []
related:
  - wiki/concepts/llm-wiki-workflow.md
created: 2026-06-23
updated: 2026-06-23
confidence: medium
summary: Tools that run language models on local hardware (e.g. Ollama, llama.cpp, LM Studio).
---

# Local LLM Runtimes

Tools that run language models on local hardware — for example Ollama, llama.cpp, and LM Studio — without sending data to a hosted API.

## Background

These runtimes make it practical to keep an entire knowledge workflow on-device, which pairs naturally with a file-based [[concepts/llm-wiki-workflow]].

## Relevance

Running locally keeps `raw/` sources and the generated `wiki/` private, and avoids per-token API cost for routine ingest and query operations.
