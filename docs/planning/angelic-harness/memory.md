# memory.md — Memory Architecture & Retrieval Doctrine

Files are the memory; vectors are the index. Everything recallable is also greppable.

---

## 1. Memory strata

| Stratum | Lives | Lifetime | Examples |
|---|---|---|---|
| **Working** | model context + `runs/<id>/` | one task | current payload, step artifacts |
| **Short-term** | `runs/<id>/` after delivery | 30 days then archived | full run record |
| **Long-term** | `harness/memory/` + Qdrant | curated, versioned | everything below |

Long-term types (all: markdown + YAML frontmatter, embedded into Qdrant by the curator):

- **Episodic** (`epi-`): distilled task episodes — goal, route, outcome, score, links. *What happened.*
- **Semantic** (`sem-`): durable facts about the world/user/stack — "vault has ~4k notes", "user prefers Pydantic". *What is true.*
- **Procedural** (`proc-`): how-to knowledge that worked — verified command sequences, prompt patterns, tool recipes. Graduation path to skill packs (skills.md §7). *What works.*
- **Error** (`err-`): the failure ledger — symptom, context, root cause, failed remedies, recommended alternative. *What doesn't work, and why.* First-class, not an afterthought: consulted before planning and before every retry (doctrine invariant 5).

## 2. Second-brain integration

The Obsidian/LifeOS vaults (existing, `olympus.toml [paths]`) are the **human's** memory;
`harness/memory/` is the **system's**. Concept:

- Read: vaults are a retrieval corpus (separate Qdrant collections, read-only to agents).
- Write: governed by the **vault-write policy** in `../second-brain/DESIGN.md` §3–§5 (the authoritative spec): frontmatter edits are additive and open to pipeline agents; note *bodies* only on `ai: true` notes; moves/merges/deletes only by the curator from a human-approved checklist; `_generated/` is the free write area. All writes use Obsidian-flavored markdown (the installed obsidian-skills define the syntax) and are marked machine-written.
- Never: agents writing ad hoc into human notes, or system memory depending on vault availability (vault offline ⇒ degraded corpus, not broken memory).

## 3. Vector store & retrieval stack

- **Qdrant** (docker, foundation compose) — collections: `harness-memory`, `vault-obsidian`, `vault-lifeos`, `code-repo`, `docs-corpus`. Snapshots to disk weekly (offline durability).
- **Embeddings**: local via Ollama (`nomic-embed-text` or `bge-m3`-class, registry-mapped like any model role). **Reranker**: local bge-reranker-class model, T0-cost, applied to top-20 → top-5.
- **Chunking**: structure-aware ("chonkie-style"): markdown by heading, code by symbol, transcripts by turn; chunk 256–512 tokens, 15 % overlap; every chunk carries source path + type + date payload fields for filtered search.
- **Degraded mode** (Qdrant down): FAISS snapshot fallback + ripgrep over `memory/` — retriever declares which mode produced the bundle.
- Ingestion of PDFs/web: Marker (PDF→md) and Crawl4AI/defuddle (web→md) feed `docs-corpus` — ingestion is an offline-ops maintenance job, not an inline task step.

## 4. Filesystem layout

```
harness/memory/
├── MEMORY.md                     # index: one line per entry (name, type, hook) — the recall map
├── episodic/    epi-20260707-wiki-index.md
├── semantic/    sem-vault-structure.md
├── procedural/  proc-comfyui-restart-between-chars.md
├── errors/      err-20260630-indexer-oom.md
├── inbox/                        # curator-parked candidates awaiting review (low confidence)
├── loops/                        # recursive-context digests for long-horizon efforts (§9)
│   └── L-anime-pipeline/  digest.md  history/
└── snapshots/                    # qdrant + faiss exports for offline resilience
```

Entry frontmatter (uniform):

```yaml
---
id: err-20260630-indexer-oom
type: error                # episodic|semantic|procedural|error
title: Indexer OOM on vaults >8k notes
tags: [indexer, qdrant, oom]
task_refs: [T-20260630-…]
confidence: 0.9
supersedes: null
expires: null              # semantic entries may carry review-by dates
---
```

## 5. Retrieval-first doctrine

**No agent generates before the retriever has been consulted**, except for steps classified
`trivial` with `context_need: small`. Enforced structurally: the planner's and executor's
payloads *contain* an evidence bundle field; an empty bundle must say why
(`"retrieval_skipped": "trivial-class"`).

Standard evidence bundle (`reports/evidence-<step>.md`, built by the retriever):

1. Error-memory hits for this task class (always first — up to 3).
2. Procedural hits (verified recipes) — up to 3.
3. Semantic/episodic hits — up to 5 chunks post-rerank.
4. Corpus hits (vaults, docs, code) — up to 5 chunks.
5. Bundle header: query used, collections searched, mode (qdrant|degraded), total tokens.

Bundle budget: ≤ 2.5k tokens (T1 receivers) / ≤ 5k (T2). Over budget → rerank harder and
summarize hits, never raise `num_ctx` first (routing.md §4).

**Retrieval-while-composing** (researcher/writer): long compositions interleave
section-scoped retrieval calls rather than front-loading one giant bundle — each section's
queries derived from the plan outline. Practical now with ReAct; keeps context small.

## 6. Memory write rules

1. **Single writer**: only the memory-curator writes long-term memory. Other agents *suggest* (`suggested_memory` in reports).
2. **Write at delivery/failure**, not mid-task (except error entries, written at failure time by the curator on the Manager's signal).
3. **Distill, don't dump**: episodic entries ≤ 30 lines; no transcripts in memory, ever.
4. **Dedupe before write**: curator retrieves near-neighbors first; updates/supersedes instead of duplicating (`supersedes:` link).
5. **Confidence gate**: < 0.7 → `inbox/` for human review (routing.md §9).
6. **Provenance mandatory**: every entry cites task/artifact refs; unprovenanced claims are not memory.
7. **Contradiction handling**: new evidence contradicting a semantic entry → curator flags both, writes a reconciliation note, and lowers confidence rather than silently overwriting.
8. **Expiry & review**: semantic entries may carry `expires:`; monthly curator pass re-scores stale entries (Near-term experimental as an automated job; Practical now as a human-triggered one).

## 7. Error memory (the anti-repetition organ)

Written on: any failed handoff, any fallback-ladder rung ≥ 2, any human correction, any
verifier rejection at task level. Format: symptom → context (task class, model, tier) →
root-cause hypothesis → remedies tried (each with outcome) → recommended next approach.

Consumption is mechanical, not optional: payload dispatch for planning and for every
retry **requires** matching `err-` refs (handoff.md §3, §8); the retriever always ranks
error hits first (§5). The learning metric is the citation rate (agent.md §8).

## 8. Context window budgeting

Global rule: **budget by role, spend on evidence.**

| Slot (T1 executor, num_ctx 8k) | Budget |
|---|---|
| System prompt (frozen, prefix-cache friendly) | ≤ 800 tk |
| Skill packs loaded this step | ≤ 1.2k tk |
| Handoff payload incl. evidence bundle | ≤ 4k tk |
| Working room (tool results, generation) | remainder ≥ 2k tk |

- Tool results > 1k tokens are summarized by a T0 pass before entering context (executor sees summary + path to full output).
- Mid-task compaction: when a subagent's own loop nears its window, it writes a `notes.md` checkpoint into the run dir and the port restarts it with payload + notes — the Deep-Agents virtual-FS pattern; nothing important lives only in context.
- KV-cache quantization and prefix stability per routing.md §4.

## 9. Loop memory & recursive context retention

For long-horizon, multi-run efforts (e.g. the anime pipeline), single-task episodic
entries are too granular. **Loop memories** (`memory/loops/L-<effort>/`) hold:

- `digest.md` — the rolling state of the effort: current best approach, open problems, decisions with reasons (≤ 100 lines, rewritten — not appended — by the curator after each related task).
- `history/` — superseded digests (auditable evolution).

Recursive improvement loops (TRM-inspired critique→revise cycles across sessions) read
the digest as their carried-over latent state: each iteration = fresh context + digest +
error entries, never the previous iteration's transcript. This gives recursion **without
context accretion** and with a human-readable state between every cycle.

Labels: strata/types/bundles/error ledger — **Practical now**. Automated monthly curation
and contradiction reconciliation — **Near-term experimental**. Fully autonomous memory
schema evolution — **Research-grade / speculative** (curator proposing new memory *types*
requires human signoff).
