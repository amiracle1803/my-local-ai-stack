---
title: Memex
type: concept
sources:
  - raw/articles/karpathy-llm-wiki-complete-guide.md
related:
  - wiki/concepts/llm-wiki-workflow.md
  - wiki/sources/karpathy-llm-wiki-complete-guide.md
created: 2026-06-23
updated: 2026-06-23
confidence: high
summary: Vannevar Bush's 1945 hypothetical personal knowledge device with associative trails — the conceptual predecessor to the LLM wiki, hypertext, and the World Wide Web.
---

# Memex

Vannevar Bush's 1945 hypothetical device for storing and navigating personal knowledge via associative trails — the direct conceptual predecessor to the [[concepts/llm-wiki-workflow]], hypertext, and the World Wide Web.

## Details

Described in Bush's 1945 Atlantic article "As We May Think." The Memex was a hypothetical desk-sized machine where an individual could store all their books, records, and communications on microfilm, search them rapidly, and create **associative trails** — linked sequences of documents with personal annotations.

Bush's key insight: **the human mind works by association, not alphabetical order.** Hierarchical filing systems force you into rigid categories. The Memex would let you create your own paths through knowledge, linking a chemistry paper to an economics report to a historical essay.

His quote: "Wholly new forms of encyclopedias will appear, ready-made with a mesh of associative trails running through them."

### Influence

The Memex directly inspired:
- **Douglas Engelbart** — read Bush's article in 1945, "became infected with the idea," invented the computer mouse and personal computing
- **Ted Nelson** — coined the term "hypertext" in 1965, directly inspired by the Memex's associative trails
- **Tim Berners-Lee** — the World Wide Web (1989) implemented hypertext at global scale

The web became public and chaotic rather than the private, curated system Bush imagined. The LLM wiki is closer to Bush's original vision: private, actively curated, with connections between documents as valuable as the documents themselves.

### The missing piece Bush couldn't solve

Creating associative trails, updating connections, keeping everything consistent — that's tedious, manual work. Humans abandon knowledge systems because maintenance burden grows faster than value.

Karpathy: "The part he couldn't solve was who does the maintenance. **The LLM handles that.**"

LLMs don't get bored, don't forget to update a cross-reference, and can touch 15 files in one pass. The Memex vision is finally achievable.

## Why it matters

The Memex frames the LLM wiki as the completion of an 80-year-old idea rather than something new. The technological building blocks (markdown files, git, LLM agents) finally make Bush's private, curated, associative knowledge store practical for individuals.
