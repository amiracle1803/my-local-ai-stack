# improvement.md — Debugging, Self-Improvement & Benchmark-Gated Switchover

Detailed protocols for (a) debugging code and the harness itself, (b) discovering
improvements from the system's own telemetry, and (c) proving an improvement from all
angles **before** it replaces anything. The prime directive: **no change ships on a
first impression; every switchover is benchmark-gated and reversible.**

---

## 1. What counts as a "change" (unified change classes)

Everything behavioral goes through the same gate discipline, differing only in gate strength:

| Class | Examples | Gate (see §5) | Approver |
|---|---|---|---|
| C1 code | port/graph/tool code, harness scripts | full debug protocol + regression + Golden subset | human PR review |
| C2 prompt | any `*.prompt.md`, preamble | prompt-regression corpus + role golden tasks | human |
| C3 skill | pack add/edit/version bump | skill evals + off-target sample | human (V1), gated curator (V2+) |
| C4 model/quant/runtime | new GGUF, quant change, Ollama→llamacpp | full qualification suite (training.md §7) | human |
| C5 adapter | LoRA/DPO promotion | qualification + canary + quarantine watch | human, always |
| C6 routing/config | routing.yaml, budgets, thresholds | ladder drill + Golden subset | human |
| C7 workflow | n8n deploy/edit | n8n pipeline gates (n8n.md §4) | human |

**One variable at a time** across all classes: never two change classes promoted in the
same window; attribution requires isolation (training.md §8 rule generalized).

## 2. Debugging protocol — agent-written code (the coder's loop)

Embedded in the coder/executor flow; each numbered step leaves a file.

1. **Reproduce first.** No fix without a failing reproduction. Write the minimal repro as a runnable case (`artifacts/<step>-repro.py` / failing test). If it can't be reproduced, the bug report goes to `concerns`, not to a speculative patch.
2. **Reduce.** Shrink input/code until the failure is minimal; the reduced case is what enters the eval suite later.
3. **Localize before hypothesizing.** Narrow by layer with evidence (logs, stack traces, bisection, print/breakpoint instrumentation): which function, which input class, which environment condition (VRAM? path? encoding? Windows-specific?).
4. **Hypothesize in writing.** One-line root-cause hypothesis in the report *before* patching. A patch that works for unexplained reasons is a `concern`, not a fix.
5. **Smallest correct patch** (repo doctrine). Revisions are new artifacts (`03b-…`); no drive-by refactors inside a bugfix step.
6. **Verify from both sides**: the repro now passes AND the pre-existing tests still pass (evidence: both outputs attached). The verifier re-executes both.
7. **Immortalize**: repro case → permanent test; root cause + failed remedies → `err-` entry via curator. A bug fixed without a new test + error entry is not "done."

Debugger tooling available to the coder (registered tools): pytest, language debuggers
(pdb/debugpy), linters, and the opencode analysis tools; on-box only.

## 3. Debugging protocol — the harness itself (meta-debugging)

When the *system* misbehaves (wrong routing, context overflow, drift, stuck loops):

1. **Replay, don't recall.** The run dir is the debugger: `task.json` (state history), `logs/calls.jsonl` (every model call with prompt hashes), manifests, reports. Reconstruct the timeline from files; never from an agent's memory of events.
2. **Layer bisection**, outside-in — at each layer there is a mechanical check:
   - *Runtime*: was the model healthy? (offline-ops status, latency in calls.jsonl)
   - *Port*: did schema validation/side-effect enforcement behave? (port logs)
   - *Routing*: did tier/model match the table? (route records + reasons)
   - *Payload*: was the handoff well-formed and within compression budgets? (stored payload)
   - *Prompt/model behavior*: only if all above are clean does it become a "model did badly" problem — which is a C2/C4/C5 improvement case, not a code bug.
3. **Deterministic re-run**: replay the failing step with the same payload + prompt hash + pinned model (temperature 0 where diagnostic) to separate stochastic flake from systematic fault. Flakes ≥ 2 occurrences get an `err-` entry with `class: flaky` and a watch counter — three strikes promotes them to systematic.
4. Same exit criteria as §2: repro → eval case, root cause → error memory, minimal patch → gated per its change class.

## 4. Finding improvements — where they come from

Improvement candidates are **mined, not mused**. Sources, in trust order:

1. **Error-ledger clustering** (weekly job): recurring `err-` tags = the top of the backlog. ≥ 3 entries sharing a cause → mandatory improvement proposal.
2. **Scorecard telemetry**: per-role/per-model first-pass verification rate, loops-to-pass, ladder engagement rate, token cost per verified step (agent.md §8 dashboards). Any metric trending down 2 weeks → investigation task.
3. **Budget waste audit**: steps that consumed > 2× median tokens for their class; context-overflow checkpoint events; retrieval bundles that got compressed twice.
4. **Human corrections**: every human override of an agent decision is logged and is *presumptively* an improvement case.
5. **Agent suggestions**: `concerns`/`suggested_memory` fields — the lowest-trust source; they seed the list, they never justify a change alone.

Each candidate becomes a one-page **improvement proposal** (in `harness/evals/proposals/`):
current metric, hypothesized change (single class from §1), expected lift, benchmark plan,
rollback plan. Proposals are cheap; switchovers are expensive — that asymmetry is the point.

## 5. Benchmark-before-switchover protocol

No change replaces its predecessor without surviving this sequence:

```
proposal → build candidate → OFFLINE EVAL (frozen benchmarks, candidate vs incumbent)
        → gate check → SHADOW/CANARY (live, limited) → promotion (registry flip)
        → watch window (auto-rollback armed) → incumbent archived, not deleted
```

**Step 1 — Frozen-benchmark A/B.** Candidate and incumbent run the *same* frozen suites
(todos.md): Golden-25 (or the relevant subset), Format-50, Retrieval-20, Offline-10,
plus the change-class-specific suite (§1). Three seeds/replicates for stochastic paths;
report mean and worst case, not best case.

**Step 2 — Gate check.** Promotion requires ALL of:
- target metric improves ≥ the proposal's declared threshold (default ≥ +5 %);
- **no regression > 2 % on any other suite** (the off-target rule — this is what "testing from all angles" means mechanically);
- red-team cases (todos.md) still hard-pass;
- resource envelope respected: latency, VRAM headroom, offline parity all within bounds;
- results written to an evaluation scorecard (`evals/results/<proposal-id>.json`) — the artifact the approver actually reads.

**Step 3 — Shadow or canary.**
- *Shadow* (judgment changes: prompts, models, routing): candidate runs **in parallel** on real payloads, outputs logged and scored but **not used**. N ≥ 20 tasks.
- *Canary* (when shadow is impossible: workflows, code paths): candidate serves a capped slice with `canary: true` stamped on every scorecard; auto-quarantine armed (training.md §6).

**Step 4 — Switchover = registry flip.** One line, one commit, incumbent kept as the
fallback rung for the watch window (1–2 weeks). **Rollback is always one edit** and
restoring a previously approved state is the only ungated automatic action in the system.

**Step 5 — Postmortem either way.** Result (kept or rolled back) → episodic memory +
proposal file updated; a rolled-back change writes an `err-` entry so the same idea
isn't re-proposed blind.

## 6. The all-angles test matrix

Every promotion's evaluation scorecard must have a row per angle — "not applicable"
must be argued, not defaulted:

| Angle | Question | Instrument |
|---|---|---|
| Correctness | does it produce verified-right results? | golden tasks, verifier pass rate |
| Format discipline | still emits valid schemas under pressure? | Format-50 |
| Off-target behavior | what got *worse*? | full regression sweep, worst-case reporting |
| Latency/throughput | tokens/s, wall per task | perf harness on this GPU |
| Memory envelope | VRAM/RAM headroom, KV behavior at max ctx | offline-ops probe |
| Offline parity | same result with network off? | Offline-10 |
| Degraded modes | Qdrant down, Ollama down, mid-task kill | ladder drill |
| Adversarial | injection, scope-bait, gate-circumvention | red-team suite |
| Long-horizon | loop-memory efforts still coherent? | one multi-session effort replayed |
| Reproducibility | same seeds/config → same behavior class? | 3-replicate variance check |

## 7. Who runs this

Mining jobs + suite execution: automated (offline-ops + eval harness). Proposals:
any agent may draft, curator files. Approvals: human per §1 — the improvement loop is
**self-measuring and self-proposing, never self-approving** (training.md §9's fence,
applied to every change class, not just adapters).

Labels: §2–§3, §5, §6 — **Practical now** (they are process + files + the existing eval
plan). §4's automated weekly mining — **Near-term experimental** (needs V1 telemetry).
Agent-drafted proposals auto-filed with pre-written benchmark plans — near-term
experimental; anything self-approving — **out of scope by doctrine**.
