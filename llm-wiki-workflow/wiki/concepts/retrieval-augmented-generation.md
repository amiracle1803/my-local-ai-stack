---
title: Retrieval-Augmented Generation
type: concept
sources: []
related:
  - wiki/concepts/llm-wiki-workflow.md
  - wiki/comparisons/wiki-vs-rag.md
created: 2026-06-23
updated: 2026-06-23
confidence: medium
summary: Pattern where a model retrieves relevant documents at query time and conditions its answer on them.
---

# Retrieval-Augmented Generation

A pattern where a model retrieves relevant documents at query time and conditions its generated answer on them, rather than relying only on parametric memory.

## Details

RAG keeps knowledge in an external store and fetches the most relevant chunks per query. The [[concepts/llm-wiki-workflow]] is a lightweight, human-readable cousin: instead of a vector index, it uses a curated markdown wiki that the agent reads via the index.

## Why it matters

It decouples knowledge from model weights, so facts can be updated without retraining. Tradeoffs against a maintained wiki are discussed in [[comparisons/wiki-vs-rag]].
