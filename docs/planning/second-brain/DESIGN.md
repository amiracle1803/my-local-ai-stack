# Second Brain OS — Autonomous Local Knowledge System

Design for a local-first cognitive operating system: Obsidian is the disk, Ollama is the
CPU, retrieval is the memory bus, and a small set of agents are the daemons. It thinks,
organizes, and acts with minimal manual effort; it never sends your notes anywhere.

**Relationship to existing systems:** this is an *application* of the angelic harness
(`docs/planning/angelic-harness/`) — its agents, loops, error memory, and guardrails are
inherited, not reinvented. It also formalizes what partially exists today: the Obsidian
vault, `E:\LifeOS` (daily notes + conductor), the Obsidian Local REST API plugin, n8n,
Qdrant, and Ollama. Scope discipline: **V1 ships with five scripts and two schedules**
(§10); everything else is labeled and deferred.

---

## 1. System architecture overview

```
                          ┌───────────── SOURCES ─────────────┐
                          │ quick capture · class notes · PDFs │
                          │ web clips · voice memos · ideas    │
                          └───────────────┬────────────────────┘
                                          ▼
┌──────────────────────────── PIPELINE (5 stages) ────────────────────────────┐
│  CAPTURE ──▶ CLEAN ──▶ ENRICH ──▶ RETRIEVE ──▶ ACT                          │
│  inbox drop  normalize  tag/link   embed+index   briefs, reviews, routing,  │
│  watcher     md+meta    summarize  Qdrant        follow-ups, digests        │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  OBSIDIAN VAULT (truth)  │◀── you, editing freely
                    │  + frontmatter contracts │
                    └────┬───────────────┬─────┘
                         │               │ one-way mirror (optional, dashboards only)
                         ▼               ▼
                  Qdrant index      Notion boards (never written back)
                  (rebuildable      
                   cache, not truth)
   Runtimes: Ollama (:11434) · embeddings (nomic/bge) · n8n (:5678 schedules)
   Agents:   harness roles scoped to vault work (§4) · human gates on anything lossy
```

Load-bearing decisions:

1. **The vault is the only source of truth.** Qdrant is a rebuildable cache; Notion is a disposable mirror; every agent output is a markdown file you can read, diff, and delete. If every service dies, the vault still works in plain Obsidian.
2. **Agents propose, files decide.** All automation lands as files (inbox notes, checkable proposals, `_generated/` digests). Nothing destructive (delete, merge, move-out-of-project) happens without an approval mark (§5).
3. **Retrieval over invention.** Questions are answered from vault chunks with citations; a generated sentence without a source link is flagged as inference (§6).
4. **Everything is rebuildable from the vault + git.** Vault under git (private, local); index rebuild is one command; there is no state that can't be regenerated.

**Vault topology (as on disk today):**

| Location | Role | Rules |
|---|---|---|
| `C:\Users\amire\Documents\Obsidian Vault` | **canonical knowledge store** — the vault this design is about | single source of truth; all reads/writes target this |
| `E:\ObsidianVault-backup` | cold mirror of the canonical vault | write-only target of the mirror job; **never opened in Obsidian, never edited, never indexed** — a mirror that gets edited becomes a fork |
| `E:\LifeOS` | separate life/task board (daily notes + conductor) | not part of this vault; consumed read-mostly via the `lifeos` MCP server; the sentinel may read its tasks, the curator may append to daily notes |

## 2. Modular workflow (stage by stage)

| Stage | Trigger | What happens | Output |
|---|---|---|---|
| **CAPTURE** | file appears in `00-inbox/` (watcher or manual drop); voice memo (whisper.cpp → md); PDF (Marker → md); web clip (defuddle → md) | raw material lands untouched, timestamped | `00-inbox/2026-07-07-raw-title.md` |
| **CLEAN** | inbox watcher (batch, every 15 min via n8n) | normalize to markdown, strip cruft, add skeleton frontmatter (`type: unprocessed`), split multi-topic dumps into atomic notes | valid vault notes, still in inbox |
| **ENRICH** | after clean | T0/T1 model: classify type, propose tags (from controlled vocab), 2-line summary into frontmatter, detect entities/projects, propose wikilinks, propose destination folder | frontmatter filled; `route:` proposal |
| **RETRIEVE** | after enrich + nightly full pass | chunk (heading-aware), embed, upsert to Qdrant with metadata payload; duplicate scan (cosine vs existing notes) | searchable index; duplicate/overlap flags |
| **ACT** | schedules + thresholds (§5) | routing (auto below risk threshold, proposed above), daily brief, weekly review, project digests, stale-task surfacing, follow-up generation | `_generated/` notes + inbox proposals |

Each stage is independently runnable and independently skippable — a broken ENRICH
model never blocks CAPTURE (fallback doctrine, §8).

## 3. Folder and data model

Vault layout (PARA-shaped, numbered for sort order; adapt names to the existing vault
rather than mass-moving — migration is incremental, note-by-note as notes get touched):

```
Vault/
├── 00-inbox/            # everything enters here; nothing lives here > 7 days
├── 10-projects/         # active, outcome-driven work
│   └── <project>/
│       ├── _project.md  # dashboard note: status, goal, next action, decision log link
│       ├── decisions.md # append-only decision log (§5)
│       └── notes…
├── 20-areas/            # ongoing responsibilities (courses, health, finances)
├── 30-resources/        # reference: topics, snippets, research threads
├── 40-archive/          # closed projects, superseded notes (moved, never deleted)
├── _generated/          # machine-written: briefs, reviews, digests (🤖, regenerable)
├── _system/             # controlled vocab (tags.md), templates, automation config
└── .obsidian/ …
```

**Frontmatter contract** (the schema agents read and write — Obsidian properties):

```yaml
---
type: note | task | idea | decision | reference | class | meeting | digest
status: unprocessed | active | waiting | stale | done | archived
tags: [ml, coursework]        # from _system/tags.md controlled vocabulary only
project: "[[10-projects/anime-pipeline/_project]]"   # optional
created: 2026-07-07
reviewed: 2026-07-07          # last time human or reviewer agent touched it
source: capture | clip | pdf | voice | manual
summary: "Two-line machine summary lives here, not in the body."
ai: false                     # true on machine-written notes (🤖 convention)
followup: 2026-07-14          # optional; sentinel watches this
---
```

Rules: agents may edit frontmatter on any note; agents may edit the **body** only of
`ai: true` notes. Tasks are `- [ ]` checkboxes with optional `📅 due` (Obsidian Tasks
syntax); the sentinel parses them. Decision log entries are append-only:
`- 2026-07-07 — chose Qdrant over Chroma — reason — links`.

## 4. Agent roles (harness roles, vault-scoped)

Small set. Each is a harness agent config (prompt + tools + tier), not a new codebase.

| Role | Harness base | Does | Never |
|---|---|---|---|
| **Ingestor** | executor (T0/T1) | CLEAN stage: normalize, split, skeleton frontmatter | interprets content beyond splitting |
| **Classifier** | executor (T1) | ENRICH: type/tags/summary/route proposal, entity + wikilink candidates | invents tags outside vocab; moves files |
| **Linker** | retriever + T1 | duplicate/overlap/conflict detection from index; "related notes" sections on `ai: true` notes | merging anything itself |
| **Curator** | memory-curator | executes *approved* routes/merges; maintains project `_project.md` context blocks and decision-log hygiene; the **only agent that moves or merges files** | acting without an approval mark on lossy ops |
| **Sentinel** | offline-ops pattern (T0 + rules) | scans for stale (`status: active` untouched 14 d), overdue follow-ups, tasks with no next action, projects with no `reviewed` in 30 d | nagging more than once per item per week |
| **Reviewer** | writer/planner (T1–T2) | daily brief, weekly review, project digests, context recaps — retrieval-first, citation-linked | unsourced claims; editing human notes |
| **Answerer** | researcher/retriever | question → retrieve → cited answer (§6) | answering from parametric memory when the vault has content |

All inherit harness guardrails: loops declare model/tools/context/stop, failures write
`err-` entries, budgets cap everything, and verification applies to anything that
modifies the vault (curator ops are verified against the approval file before running).

## 5. Automation rules and decision logic

Confidence-gated autonomy — the dial you turn as trust grows (§7):

| Action | Condition | V1 behavior | V3 behavior |
|---|---|---|---|
| Fill frontmatter (tags, summary, type) | classifier confidence ≥ 0.7 | auto | auto |
| Route note to folder | confidence ≥ 0.85 AND destination exists | **propose** (`route:` field + inbox report) | auto, logged |
| Route note, low confidence | < 0.85 | queue in triage report | propose |
| Create wikilinks / related sections | always | auto on `ai: true` notes, propose on human notes | auto everywhere except body of human notes |
| Flag duplicate | cosine ≥ 0.86 + same type | propose merge (side-by-side note) | propose (merging is **never** auto — lossy) |
| Merge / delete / bulk move | — | **human approval, always**: curator executes only items checked in `_generated/approvals-YYYY-MM-DD.md` | same. This row never changes. |
| Stale/overdue surfacing | rule thresholds (14 d / due date / 30 d review) | auto into daily brief | auto + proposed next actions |
| Follow-up generation | note contains commitment language ("will", "todo", "ask X") with no task | propose task line | auto-create task with `ai: true` provenance |
| Daily brief / weekly review / digests | schedule (07:30 / Sun 18:00 / project close or on-demand) | auto (pure `_generated/` writes are always safe) | auto |

**Triage logic (pseudocode):**

```python
def triage(note):
    cls = classify(note)                      # T1, JSON out, schema-validated
    write_frontmatter(note, cls)              # always safe: additive metadata
    if duplicate_score(note) >= 0.86: propose_merge(note); return
    if cls.confidence >= 0.85 and dest_exists(cls.route): propose_or_auto_route(note)
    else: triage_report.add(note)             # human decides in the daily brief
    if commitment_without_task(note): propose_followup(note)
```

## 6. Retrieval-first query flow ("ask the vault")

```
question → embed → Qdrant top-20 (filtered by type/project when stated)
        → local rerank → top-5 chunks → answer composed ONLY from chunks,
          every claim linked [[note#heading]] → unsourced additions marked "⚠ inference"
        → if best score < floor: say "vault has nothing on this", offer web research
          (explicit, separate step — never silently blended)
```

Interface V1: CLI (`brain ask "what did I decide about the indexer?"`) + the existing
AnythingLLM/Obsidian-REST chat as the zero-code alternative. Interface V2: harness
Answerer with conversation memory scoped per session.

## 7. Path from supervision to autonomy

The autonomy dial moves only on evidence, per action class (mirrors harness
benchmark-gated switchover): an action graduates from *propose* to *auto* when its
proposals have ≥ 95 % human acceptance over 4 weeks **and** a rollback exists (git).
Downgrades are automatic: 2 bad autonomous actions in a week demote the class back to
propose and write an `err-` entry. Merge/delete never graduates.

## 8. Failure modes, guardrails, recovery

| Failure | Detection | Behavior | Recovery |
|---|---|---|---|
| Ollama down | health ping | pipeline degrades: CAPTURE/CLEAN continue (no LLM needed), ENRICH queues | offline-ops restarts; queue drains on recovery |
| Qdrant down / index corrupt | health ping / checksum | Answerer degrades to ripgrep + FAISS snapshot; says so in answers | `brain reindex` rebuilds fully from vault |
| Obsidian REST plugin dead | HTTP fail | fall back to direct file I/O (vault is just files) | none needed — file path is the primary path anyway |
| Classifier garbage (bad tags/routes) | acceptance-rate telemetry | additive-only damage (frontmatter); routes were proposals | git revert; demote autonomy dial; err- entry |
| Runaway generation (huge digests) | token budget per job | job killed at cap, partial output marked | budget in `_system/automation.yaml` |
| Watcher misses files | nightly full-scan reconciliation | nightly pass diffs vault vs index | self-healing by design |
| Vault sync/merge conflicts (if user syncs) | conflict files | agents never touch `*.conflict.*`; surfaced in brief | human resolves |
| Notion mirror fails | n8n error branch | mirror is disposable; alert only | re-run mirror job; truth unaffected |

Standing guardrails: vault in git with nightly auto-commit (the universal undo) · nightly
cold mirror to `E:\ObsidianVault-backup` (`robocopy "C:\Users\amire\Documents\Obsidian Vault"
"E:\ObsidianVault-backup" /MIR /R:1 /W:1` as an n8n job — /MIR keeps it an exact replica) ·
agents edit bodies only on `ai: true` notes · lossy ops behind the approvals file · every
agent write logged with provenance (run ID in frontmatter) · dry-run mode for every script
(`--dry-run` prints the plan, writes nothing).

## 9. Example commands & prompts

```powershell
brain capture "idea: use hash manifest for incremental vault indexing"   # → 00-inbox
brain triage            # run CLEAN+ENRICH on inbox now (else 15-min schedule)
brain ask "open questions on the anime pipeline?" --project anime-pipeline
brain brief             # generate today's daily brief now
brain reindex --full    # rebuild Qdrant from vault
brain approve           # open today's approvals note; checked items execute
brain status            # pipeline health, queue depth, index freshness, last brief
```

Classifier prompt core (T1, JSON-schema enforced — full prompt follows harness skeleton):

```
Classify this note for a personal knowledge vault.
Allowed types: note|task|idea|decision|reference|class|meeting.
Allowed tags (choose ≤ 4): {contents of _system/tags.md}.
Existing projects: {list}.
Return JSON: {type, tags[], summary (≤2 lines, factual), project|null,
route (folder path|null), confidence (0-1)}.
Rules: never invent tags; summary states what the note SAYS, not what it implies;
confidence < 0.85 when uncertain — uncertainty is the correct answer.
```

Daily-brief prompt core (Reviewer): *inputs are retrieved, not recalled* — yesterday's
notes, overdue/stale lists from the sentinel, today's calendar note if present, open
approvals. Output sections: `New & routed / Needs your decision (approvals) / Stale &
overdue / Suggested top-3 next actions (each citing its source note)`. Every line links.

## 10. Roadmap and the lean V1 plan

**V0.5 → V1 (2 weeks of evenings, ships value immediately) — Practical now**

Five Python scripts + two n8n schedules; no harness dependency yet (harness plugs in at V2):

1. `watch_inbox.py` — watcher + CLEAN (normalize, frontmatter skeleton). *Days 1–2*
2. `enrich.py` — classifier call via Ollama, frontmatter fill, route proposals. *Days 3–5*
3. `index.py` — chunk/embed/upsert + `reindex`; duplicate scan. *Days 6–8*
4. `sentinel.py` — stale/overdue/follow-up scan → markdown report. *Day 9*
5. `brief.py` — daily brief + weekly review from retrieval + sentinel output. *Days 10–12*

n8n: `every 15 min → triage`, `07:30 → brief`, `Sun 18:00 → review`, nightly reconcile +
git auto-commit. Acceptance test: **one week where the daily brief is genuinely read and
the inbox stays under 10 notes without manual filing.** That, not features, is V1 done.

**V2 — harness integration (after harness Phase 1):** roles move onto harness agents
(verification, error memory, budgets for free); Answerer with citations; approvals
executed by curator; project digests + decision-log maintenance.

**V3 — autonomy + surfaces:** autonomy dial graduations (§7); optional one-way Notion
mirror for dashboard views (n8n job, API key, mirror-only — **off by default**, and the
one deliberate cloud exception); voice capture via whisper.cpp; conflict detection
(notes that *contradict*, not just duplicate — Near-term experimental); idea-cluster
surfacing ("these 4 ideas are one project" — Near-term experimental).

**Anti-scope-creep clause:** nothing from V2/V3 starts until the V1 acceptance test has
passed for two consecutive weeks. The most likely failure mode of this project is
building the Answerer before the inbox works. Don't.
