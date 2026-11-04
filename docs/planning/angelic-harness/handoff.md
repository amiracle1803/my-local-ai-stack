# handoff.md — Inter-Agent Handoff Contract

How work moves between agents without context bleed, drift, or lost evidence.
Small local models make discipline here load-bearing: schemas, not vibes.

---

## 1. Principles

1. **A handoff is a contract, not a conversation.** Structured input in, structured report out; both schema-validated at the port layer before the receiving/returning agent's output is accepted.
2. **Scoped context, fresh every time.** A subagent never sees the Manager's transcript, other subagents' transcripts, or the whole run. It sees: its system prompt, the handoff payload, and files it explicitly reads.
3. **Artifacts by reference, never by value.** Content moves as `runs/<id>/...` paths + hashes; only *excerpts needed for the decision* are inlined, under the compression budget.
4. **Claims require evidence.** A report asserting "tests pass" without the test output artifact is rejected mechanically.
5. **Compact returns.** Subagents return a bounded final report + references. Raw transcripts stay in the subagent's own log file and never re-enter anyone's context.

## 2. The handoff lifecycle

```
Manager                     Subagent
  │ build payload (schema)     │
  │──── dispatch ─────────────▶│  fresh context: prompt + payload (+ skill packs)
  │                            │  work loop (ReAct), writes artifacts/ + own log
  │◀─── report (schema) ───────│  compact report + artifact refs + evidence
  │ validate schema            │
  │ verify evidence exists     │
  │ route to critic/scorer     │
  │ accept | revise | reassign │
```

## 3. Handoff payload schema (`harness/schemas/handoff.json`)

Sample payload (Manager → coder):

```json
{
  "handoff_id": "H-20260707-a3f1-04",
  "task_id": "T-20260707-wiki-index-a3f1",
  "step": 4,
  "state": "EXECUTION",
  "from": "manager", "to": "coder",
  "objective": "Implement incremental indexer per plan step 4. One sentence. Imperative.",
  "acceptance_criteria": [
    "reindex of unchanged vault touches 0 files (evidence: run log)",
    "unit tests in tests/test_indexer.py pass (evidence: pytest output artifact)"
  ],
  "inputs": {
    "plan_ref": "plan/plan.md#step-4",
    "artifacts": [{"path": "artifacts/03-schema.py", "sha256": "…", "why": "data model to build on"}],
    "evidence_bundle": "reports/evidence-04.md",
    "error_memory": ["memory/errors/err-20260630-indexer-oom.md"]
  },
  "constraints": {"side_effects": ["write-scoped"], "offline_ok": true, "language": "python"},
  "budget": {"max_tokens": 40000, "max_wall_minutes": 15, "max_tool_calls": 30},
  "route": {"tier": "T1", "model": "ornith-9b@ollama"},
  "return_schema": "schemas/report.json"
}
```

Required in every payload: objective (one sentence) · acceptance criteria (testable, each
naming its evidence form) · scoped inputs by reference · relevant error-memory refs ·
budget · side-effect allowlist. Anything absent → the port refuses dispatch. An empty
`error_memory` array is legal only when the evidence bundle's header records that
retrieval found no matching entries (memory.md §5).

## 4. Context compression rules

The Manager (helped by the retriever) compresses context *into* the payload:

| Rule | Detail |
|---|---|
| Budget | payload ≤ 4k tokens for T0/T1 receivers, ≤ 8k for T2; evidence bundle counted |
| Inline vs ref | inline only excerpts the agent needs to *decide*; whole files always by ref (the agent reads what it chooses within its tool budget) |
| Summarize upstream | prior step outcomes enter as their **report summaries**, never their transcripts |
| Error memory | max 3 most-relevant `err-` entries, each pre-summarized to ≤ 5 lines |
| No transitive context | payloads must not embed prior payloads; re-derive from artifacts |
| Compression is lossy on purpose | if the receiver needs more, it reads files — pull beats push |

## 5. Report schema (subagent → Manager)

```json
{
  "handoff_id": "H-20260707-a3f1-04",
  "status": "done | partial | blocked | failed",
  "summary": "≤ 10 lines, plain language, what was done and what changed",
  "artifacts": [{"path": "artifacts/04-indexer.py", "sha256": "…", "kind": "code"}],
  "evidence": [{"claim": "unit tests pass", "ref": "logs/04-pytest.txt", "kind": "test-output"}],
  "acceptance_self_check": [{"criterion": 0, "met": true, "evidence_idx": 0}],
  "confidence": 0.85,
  "concerns": ["indexer untested against vault >10k notes"],
  "suggested_memory": [{"type": "procedural", "note": "…"}],   // curator decides, agent only suggests
  "usage": {"tokens": 31200, "tool_calls": 18, "wall_seconds": 410}
}
```

Mechanical validation before any model judges it: schema-valid · every artifact path
exists and hash matches · every criterion maps to an evidence ref · budget not exceeded.
Failures here are *format* failures (routing.md §5 rung 1), not quality failures.

## 6. Artifact passing rules

- Artifacts are written once by their producing step, then immutable; revisions are new files (`04b-indexer.py`) with the manifest recording lineage.
- `runs/<id>/manifest.json` is the ledger: every artifact's path, hash, producer handoff_id, and superseded-by link.
- Cross-task artifact reuse goes through memory (curator promotes an artifact to `memory/procedural/` or a skill pack) — never by pathing into another run dir.
- Plans are readable by everyone, writable only in PLANNING by the planner (agent.md §5).

## 7. Review & signoff chain

Every step passes through, in order:

1. **Mechanical validation** (port layer — free).
2. **Critic** (model ≠ author's when the registry allows): flaws vs. acceptance criteria; output = blocking / non-blocking issue list. Never edits.
3. **Revise** (author agent, same scoped context pattern, critique attached) — only if blocking issues and loop budget remains.
4. **Scorer**: rubric → scorecard. Sample scorecard (`scores/scorecard-04.json`):

```json
{
  "handoff_id": "H-20260707-a3f1-04", "loop": 2,
  "rubric": "rubrics/code-step.yaml",
  "scores": {"correctness": 0.9, "criteria_coverage": 1.0, "evidence_quality": 0.8,
              "simplicity": 0.7, "constraint_compliance": 1.0},
  "weighted_total": 0.88,
  "gate": {"threshold": 0.80, "passed": true}
}
```

   Rubric dimensions are fixed per artifact kind (code / prose / plan / workflow / research),
   weights in `harness/evals/rubrics/*.yaml`. Scorer sees artifact + criteria + evidence,
   **not** the author's confidence (anchoring).
5. **Verifier**: binary verdict. Runs actual checks where possible (pytest, JSON schema, n8n lint, ffprobe) — *execution beats opinion*; falls back to model judgment only for unrunnable claims. Writes `scores/verdict-04.json` with pass/fail + reasons.

Whole-task signoff repeats 2–5 at task level against the plan's overall acceptance criteria.

## 8. Retry / reassign policy

Two failure classes take two different paths (aligned with routing.md §5/§9):

- **Quality collapse** (scorer weighted total < 0.50 hard floor): don't polish garbage —
  skip attempts 1–2 below and escalate directly (attempt 3 / ladder rung 3).
- **Verifier fail above the floor**: work the chain from attempt 1.
- Runtime/format failures never reach this table — they are handled by the fallback
  ladder rungs 1–2 (routing.md §5) before any quality judgment happens.

On a verifier-failed step above the hard floor:

| Attempt | Action | Requirement |
|---|---|---|
| 1 | same agent+model, critique + error-memory entry attached | error entry written first (doctrine invariant 5) |
| 2 | same tier, sibling model (diversity) | fresh scoped context; previous attempt enters as a *summarized negative example*, not a transcript |
| 3 | tier escalation (routing.md §8) | manager logs escalation reason |
| — | still failing | manager decides: decompose (replan, bounded) or park for human with evidence bundle |

Reassign, not retry, when: failure mode is capability-shaped (consistent conceptual error) ·
error memory shows this agent+model+task-class failing ≥ 2 times · budget nearly exhausted
(skip straight to escalation).

Anti-repetition guarantee: the port refuses a retry dispatch whose payload lacks an
`error_memory` reference to the just-logged failure.

## 9. Communication media & formats — who speaks what

Agents don't negotiate formats ad hoc; the medium is fixed by traffic type, and
producers emit what the consumer parses best.

| Traffic | Format | Why |
|---|---|---|
| Control-plane messages (payloads, reports, scorecards, verdicts, route records) | **strict JSON**, schema-validated | machines parse it, small models emit it reliably with `json_mode`/grammar constraints, and validation is free |
| Configs & registries | **YAML** | human-edited, comment-friendly, diff-reviewable |
| Plans, critiques, evidence bundles, memory entries, final reports | **Markdown** (+ YAML frontmatter) | read by both humans and models; greppable; vault-compatible |
| Code artifacts | language chosen per §below | the artifact *is* the deliverable |
| Media artifacts | native binary + a JSON sidecar (`<name>.meta.json`: params, source, hash) | binaries are opaque; the sidecar is what agents and verifiers read |

**Language policy for code artifacts** — the rule is *verifiability on this box*:

1. **Python first** (repo standard): pytest, debugpy, and the whole toolchain are registered — full verify loop available.
2. **JS/TS second** (Node present) for web/frontend steps.
3. **PowerShell/batch** for Windows glue (start scripts, service control).
4. **Rust / C++ / other compiled targets**: allowed **only if the toolchain is registered in `tools.yaml`** (cargo, MSVC) so the verifier can actually compile and run tests. The binding rule: **if the verifier cannot execute it, the coder may not emit it** — unverifiable code fails the plan gate, not the code review.

**Capability declarations** drive routing of format-sensitive work. `models.yaml`
already declares `capabilities: {json_mode, tools, thinking, ctx_max}`; agent entries
add an `io` block:

```yaml
coder:
  io:
    consumes_best: [json, markdown, python]
    produces: [python, javascript, powershell, json]
    needs_examples: true        # small models: include a few-shot exemplar for new formats
scorer:
  io: {consumes_best: [markdown, json], produces: [json]}   # never freeform prose out
```

Rules:

1. **Producer adapts to consumer.** The Manager checks the receiving agent's `consumes_best` when assembling payloads; default is JSON + markdown refs.
2. **JSON at every boundary, freedom inside.** Within its own working loop an agent may think in whatever medium helps; the moment data crosses an agent boundary it must be one of the table's media, schema-validated where JSON.
3. **Grammar-constrained decoding** (llama.cpp GBNF / Ollama structured outputs) is the enforcement backstop for weak JSON emitters — declared per model in the registry, applied automatically by the ModelPort when `structure: schema` (routing.md §2).
4. **No format invention.** New interchange formats require a schema in `harness/schemas/` first — an agent emitting an undeclared format is a format failure (ladder rung 1).
