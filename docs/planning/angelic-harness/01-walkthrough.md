# 01-walkthrough.md — One Task, End to End

A concrete trace of the full workflow: every stage, every file written, every rule that
binds — including one runtime failure and one quality failure so the recovery machinery
is visible. Read `agent.md` first; this file shows the doctrine in motion.

**Example task:** *"Add incremental reindexing to the wiki indexer so unchanged notes are skipped."*

---

## Stage 0 — INTAKE

Trigger: user message (could equally be an Olympus schedule or an n8n webhook → intake).

1. Manager mints `T-20260707-wiki-index-a3f1`, scaffolds `runs/T-20260707-wiki-index-a3f1/` with `plan/ artifacts/ reports/ scores/ logs/`, writes `task.json` with `state: INTAKE` and the goal **verbatim**.
2. **Classification** (routing.md §2): rules fire first (mentions code + files → `domain: coding`); the T0 triage model emits the class record as JSON: `{domain: coding, difficulty: hard, risk: low, offline_ok: true, structure: schema, context_need: medium}`. Schema-validated; no disagreement, so the advisor is not engaged and no clarifying questions are needed.
3. **Route** (routing.md §3): difficulty `hard` → tier T2 for planning, T1 default for execution steps. Model-router resolves T2 → `qwen3-8b@ollama` with ladder `[qwen2.5-14b-q4@llamacpp, hermes]`, budget `{max_loops: 3, max_tokens: 200k, max_wall_minutes: 45}`. Written into `task.json`.

*Files so far:* `task.json`, `logs/calls.jsonl` (2 T0 calls logged with prompt hashes).

## Stage 1 — Retrieval-first pass (still pre-PLANNING)

4. Manager dispatches the **retriever** (T0) with the goal + class. It queries Qdrant collections `harness-memory` and `code-repo`, reranks top-20 → top-5, and writes `reports/evidence-01.md`:
   - **Error hits first** (memory.md §5): `err-20260630-indexer-oom.md` — "full reindex OOMs on vaults > 8k notes; batching fixed it."
   - Procedural hit: `proc-qdrant-upsert-batching.md`.
   - Code-corpus chunks: the current indexer's entry points.
   - Header: query, collections, mode `qdrant`, 1 940 tokens (under the 2.5k T1 bundle cap).

If Qdrant were down, the bundle header would say `mode: degraded (faiss+ripgrep)` and the run would continue — never block on the vector store (memory.md §3).

## Stage 2 — PLANNING

5. `task.json → state: PLANNING`. From here the port layer **refuses** any tool call with side effects outside `plan/`, retriever writes to `reports/`, and read-only reads (agent.md §5). This is enforcement, not prompt trust.
6. **Planner** (T2, fresh context: its frozen prompt + preamble + goal + class + evidence bundle) writes `plan/plan.md`:
   - Step 1 — coder/T1: add mtime+hash manifest to the indexer. Criteria: "unchanged vault reindex touches 0 files (evidence: run log)". *Plan explicitly cites `err-20260630`*: batching strategy retained — the plan must state how each cited failure is avoided (planner prompt rule 1).
   - Step 2 — coder/T1: unit tests. Criteria: "pytest green (evidence: pytest output artifact)".
   - Step 3 — executor/T1: run against the sample vault (`vault-sample/`, never the real vault — side-effect class `write-scoped` only). Criteria: "second run reports 0 reindexed (evidence: captured stdout)".
   - Plan-level acceptance criteria + risk note; every step declares agent, tier, tools, `offline_ok: true`.
7. **Plan gate**: critic (T1, model-diverse from the planner) reviews the plan against feasibility/budget/coverage — finds 0 blocking issues → `reports/critique-plan.md`. Risk class is `low`/`write-scoped`, so **no human gate** is required (agent.md §3). Manager records gate approval in the log and flips `state: EXECUTION`. Had the critic found blocking issues: replan, bounded at ≤ 2.

*Files:* `plan/plan.md`, `reports/critique-plan.md`. The plan is now **immutable**.

## Stage 3 — EXECUTION, step 1 (happy path)

8. Manager builds the **handoff payload** `H-…-01` (handoff.md §3): one-sentence objective, the two criteria with evidence forms, inputs by reference (plan section, code paths), the `err-20260630` ref, budget, `side_effects: [write-scoped]`, `return_schema`. Payload = 3.6k tokens, under the 4k T1 cap.
9. **Coder** starts with a *fresh scoped context* — prompt + payload only. It works the ReAct loop: reads the evidence bundle first (retrieval-first, prompt rule 1), reads the cited code, writes `artifacts/01-manifest.py`, runs it. Tool outputs over 1k tokens get a T0 summary before entering its context (memory.md §8).
10. Coder returns the **report** (handoff.md §5): `status: done`, ≤ 10-line summary, artifact refs with hashes, evidence refs, per-criterion self-check, `confidence: 0.85`, one `concern`, usage.
11. **Mechanical validation** (free, no model): schema valid, artifact paths exist, hashes match, every criterion maps to evidence. Passes.
12. **Signoff chain** (handoff.md §7): critic (T1 sibling model) → 1 non-blocking issue → no revise needed; scorer → `scores/scorecard-01.json`, weighted 0.86 ≥ 0.80 gate; verifier → *executes* the run-log check rather than opining (`method: executed`) → `scores/verdict-01.json: pass`.

## Stage 4 — EXECUTION, step 2 (runtime failure → fallback ladder)

13. Mid-generation, Ollama hangs (VRAM fragmentation — a known reality on this GPU). The ModelPort times out. This is a **runtime failure**, so it takes the fallback ladder (routing.md §5), not the quality chain:
    - The failure is logged and an `err-` entry drafted *before* any retry (invariant 5).
    - Rung 2: same-tier sibling `qwen2.5-7b@ollama` — Ollama itself is unresponsive → rung 4 applies instead: same tier, different **runtime** → `llamacpp` pinned GGUF. The retry payload carries the new error-memory ref; the port would refuse it otherwise (handoff.md §8).
    - Offline-ops steward independently notices the unhealthy runtime via its status file and restarts Ollama in the background (its job, not the coder's).
14. Step 2 completes on the llama.cpp rung; pytest output captured to `logs/02-pytest.txt`; chain passes: scorecard 0.91, verdict pass.

## Stage 5 — EXECUTION, step 3 (quality failure → retry chain)

15. Executor runs the indexer against `vault-sample/` twice; second run reports **3 files reindexed, not 0**. It self-checks honestly: `status: partial`, criterion unmet, evidence attached (honest partial beats confident fiction — executor prompt rule 3).
16. Scorer: 0.62 — below the 0.80 gate but **above the 0.50 hard floor**, so this is a verifier-fail-above-floor → quality retry chain from attempt 1 (handoff.md §8), *not* escalation.
17. Curator writes `err-20260707-mtime-precision.md` on the Manager's signal (root-cause hypothesis: Windows mtime precision; remedy to try: compare hashes, not mtimes). **Attempt 1**: same coder+model, fresh context, with the critic's findings and the new error entry attached. The fix lands as `artifacts/03b-indexer-fix.py` (revisions are new files; the manifest records lineage, handoff.md §6).
18. Re-run: 0 reindexed. Scorecard 0.88; verifier executes the check: pass. Loop count 2 of `max_loops` 3 — had it exhausted, the Manager would escalate or fail loudly, never spin (invariant 4).

## Stage 6 — VERIFICATION (task level) and DELIVERY

19. Whole-task chain re-runs against the **plan-level** criteria: critic finds nothing blocking; scorer 0.87; verifier executes the end-to-end check once more → task verdict: pass. Nothing unverified can exit (invariant 3).
20. `state: DELIVERY`. Manager assembles `reports/final-report.md` **from step reports and artifacts only** — never from transcripts (manager prompt rule 7) — and finalizes `manifest.json` (every artifact hashed, lineage recorded).

## Stage 7 — Memory writeback & postmortem

21. **Memory-curator** (the *only* writer to shared memory) runs:
    - dedupe check against near-neighbors, then `epi-20260707-wiki-index.md` (≤ 30 lines, provenance refs);
    - promotes the hash-comparison technique to `proc-hash-based-change-detection.md` (confidence 0.9 ≥ 0.7 gate — otherwise it would land in `inbox/` for human review);
    - finalizes the two `err-` entries from stages 4–5;
    - updates `MEMORY.md` index lines and embeds new entries into Qdrant.
22. Telemetry side effects, free of charge: the failed attempt 3 + passing 3b on the same payload become a **DPO preference pair candidate** in `training/harvest/` (training.md §5); the episode counts toward n8n opportunity mining (n8n.md §2) — one occurrence, so nothing triggers.

## Final state of the run directory

```
runs/T-20260707-wiki-index-a3f1/
├── task.json                    # state: DELIVERED, full route + budget history
├── manifest.json                # hashes + lineage (03 superseded-by 03b)
├── plan/plan.md                 # immutable since the plan gate
├── artifacts/01-manifest.py  02-tests.py  03-indexer.py  03b-indexer-fix.py
├── reports/evidence-01.md  critique-plan.md  critique-01..03.md  final-report.md
├── scores/scorecard-01..03.json  verdict-01..03.json  verdict-task.json
└── logs/calls.jsonl  02-pytest.txt  03-run.txt  …
```

Reproducibility bar (agent.md §8): this directory alone reconstructs the whole run.

## Where each rule bound — stage → doctrine map

| Stage | Binding rules |
|---|---|
| Intake/classify | routing.md §2–§3 (rules → T0 vote; table lookup; ladder attached) |
| Retrieval pass | memory.md §5 (error hits first, bundle caps, degraded mode) |
| Planning | agent.md §5 (state legality at the port), planner prompt rules 1–4 |
| Plan gate | handoff.md §7 chain on the plan; human gate only for external/irreversible risk |
| Execution handoffs | handoff.md §3–§6 (payload contract, compression caps, artifacts by ref) |
| Runtime failure | routing.md §5 ladder; invariant 5 (error entry before retry); offline-ops recovery |
| Quality failure | routing.md §9 gates (0.80 / 0.50) → handoff.md §8 chain; loop caps |
| Verification | critic ≠ scorer ≠ verifier separation; verifier "execution beats opinion" |
| Delivery | manager assembles from reports; manifest finalized |
| Writeback | memory.md §6 single-writer, dedupe, confidence gate; training harvest quarantined |

## Variant traces (what changes, briefly)

- **Offline day**: T3 forbidden by `offline_mode`; researcher uses corpus-only mode; n8n workflows take their declared offline branches; everything above still runs — that is the Checkpoint 1 acceptance test (todos.md).
- **Risky task** (plan contains an `external` step, e.g. deploy an n8n workflow): identical until the plan gate, which **parks for human approval**; the workflow-builder's output ends at validated JSON + card + dry-run evidence; a human activates (n8n.md §4).
- **Frontier-stuck task**: ladder exhausted at T2 → Manager parks with an evidence bundle and a structured question (rung 6). If the user sets the T3 flag, Claude's answer re-enters as *evidence* for a local pass — the verified state is still locally produced (routing.md §6, claude.md §2).
