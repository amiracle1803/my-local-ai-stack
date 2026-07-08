# loop-engineering.md — Engineering Disciplines & The Canonical Loop

The consolidated spec for how the harness's loops are engineered: the nine disciplines,
the anatomy every loop must declare, the three phases, where loops break, and the
guardrails that catch them. Everything here binds; the rest of the package supplies detail.

---

## 1. The nine disciplines and where each lives

| Discipline | What it means here | Binding rule | Spec |
|---|---|---|---|
| **Prompt engineering** | prompts are versioned firmware: skeleton, ≤ 800 tk, NEVER-blocks, schema-terminated | no runtime prompt mutation; regression-gated edits | systems-prompts.md |
| **Context engineering** | budget by role, spend on evidence; compress at boundaries; checkpoint before overflow | payload caps enforced at the port; pull beats push | memory.md §8, handoff.md §4 |
| **Harness engineering** | planes, ports, registries, state machine; the model is a component, the harness is the product | all runtime access through ports; models are roles | agent.md, overview §3/§6 |
| **Loop engineering** | every loop declares Model+Tools+Context+Stop; three phases gather→act→verify | undeclared loops are illegal (this file) | this file |
| **LLMOps** | model lifecycle: bench → qualify → route → observe → canary → rollback; keep-alive/VRAM scheduling; call logs | every model call attributed and logged; registry flips only | routing.md, improvement.md §5, training.md §6 |
| **Evals** | frozen suites, rubrics, scorecards; nothing promotes un-benchmarked | gate check: target lift + no >2 % off-target regression | improvement.md, todos.md benchmarks |
| **Tool calling** | tools are registered contracts with side-effect classes and offline flags | no agent holds endpoints/keys; ReAct is the only tool loop | integration.md §1, agent.md §3 |
| **MCP** | MCP servers are execution-plane services behind the tool registry; gateway for allowlists | discovery ≠ access; registration is the gate | integration.md §3 |
| **RAG** | retrieval-first doctrine: chunk → embed → filter → rerank → bundle, before any generation | non-trivial steps require an evidence bundle or a logged skip reason | memory.md §3/§5 |

## 2. Canonical loop anatomy — Model, Tools, Context, Stop

**No loop may run without declaring all four.** This is checked at dispatch (the handoff
payload and graph node config *are* the declaration):

```yaml
loop:
  model:   role/tier via routing table (never a hardcoded name)     # WHO thinks
  tools:   explicit allowlist + side-effect classes                 # WHAT it may do
  context: system prompt + payload + evidence bundle + budget caps  # WHAT it knows
  stop:    ALL of:                                                  # WHEN it ends
    success:   every requirement checked off AND verifier pass
    iteration: max_loops (default 3) / max_tool_calls
    resource:  max_tokens, max_wall_minutes
    quality:   hard floor < 0.50 → exit to escalation, don't iterate
    external:  human interrupt / state change (offline, budget freeze)
```

A loop that hits any non-success stop **exits loudly**: report with `status: partial|failed`,
error-memory entry, and control returned to the layer above. Loops never self-extend
their own budgets.

## 3. The three phases: GATHER → ACT → VERIFY

Every loop iteration, at every scale, walks the same three phases:

```
        ┌──────────────────────── one iteration ────────────────────────┐
        │  GATHER                 ACT                    VERIFY         │
        │  retrieve evidence      reason → act → observe check against  │
        │  read requirements      (ReAct inner loop,     requirements;  │
        │  read error memory      ≤ max_tool_calls)      score; verdict │
        └──────────────┬─────────────────────────────────────┬──────────┘
                       │            verdict = pass → STOP (success)
                       └── verdict = fail + budget left → next iteration
                            (carrying critique + updated requirement list,
                             never the previous transcript)
```

- **GATHER** — assemble what's true before generating: evidence bundle (error hits first), the requirement list, relevant artifacts. Generation before gathering is a doctrine violation (memory.md §5).
- **ACT** — the **reason → act → observe** inner loop (ReAct): think about the next move (hidden reasoning, contained per systems-prompts.md §9) → call one tool → observe the result (summarized if > 1k tokens) → repeat until the step's work is done or `max_tool_calls` hits. This inner loop is where tool calling lives; it never crosses an agent boundary.
- **VERIFY** — self-check against the requirement list, then the external chain (critic → scorer → verifier). Execution beats opinion: run the test, don't assert it.

## 4. Requirement-list generation, then loop to completion

The task-level pattern the user-facing loop follows:

1. **Generate the requirement list first.** PLANNING produces it: plan steps + per-step acceptance criteria + plan-level criteria (agent.md §6). This *is* the Deep-Agents todo list, made testable — every requirement names its evidence form. A requirement that can't be checked can't be planned (planner prompt rule 2).
2. **Freeze it.** The list is immutable during EXECUTION; discovering it's wrong forces a bounded replan, never an in-place edit.
3. **Loop over unmet requirements**: each iteration picks the next unmet requirement, runs GATHER→ACT→VERIFY for it, and updates the checklist file (`runs/<id>/plan/todos.md`, checked items link to their evidence).
4. **Stop when**: all requirements checked *and* task-level verifier passes (success), or any stop condition from §2 fires (loud exit).

## 5. Loop taxonomy — every loop in the system, declared

| Loop | Model | Tools | Context | Stop |
|---|---|---|---|---|
| **Task loop** (manager) | T1 | dispatch, gates, state transitions | task.json + step reports | all requirements met + verified; or budget/replan cap |
| **Step loop** (executor ReAct) | per route | payload allowlist | payload + evidence + notes.md | criteria self-checked; max_tool_calls; context checkpoint |
| **Verification loop** | critic/scorer/verifier (diverse) | read-only + executable checks | artifact + criteria + rubric | verdict pass; max_loops 3; hard floor short-circuit |
| **Effort loop** (long-horizon) | T2 planner | loop digest read/write via curator | digest.md + error entries, never past transcripts | effort milestone met; human review each cycle |
| **Ops loop** (offline-ops) | T0 + rules | health checks, restarts, status file | status file + service registry | continuous; each tick bounded; escalates, never repairs blindly |
| **Improvement loop** | mixed | eval harness, proposals | telemetry + frozen benchmarks | gate check; human approval; auto-rollback only to approved state |

## 6. Where loops break — failure catalog and the guardrail for each

| # | Break mode | Detection signal | Guardrail |
|---|---|---|---|
| 1 | **Runaway iteration** (model never converges) | loop counter | hard `max_loops`/`max_tool_calls`; exit loud (invariant 4) |
| 2 | **Oscillation** (revise ping-pong: fix A breaks B, fix B breaks A) | same criterion flips pass/fail across iterations | manager detects flip-flop at iteration 2 → escalate tier, don't iterate |
| 3 | **Context overflow / rot** (loop accretes stale tool output) | token accounting near `num_ctx` | summarize-at-1k rule; checkpoint to notes.md + fresh restart (memory.md §8) |
| 4 | **Repetition/degeneration** (small-model output loops) | n-gram repeat detector at the port; timeout | cancel generation → ladder rung 1–2 (runtime failure path) |
| 5 | **Goal drift** (each iteration slightly rewrites the objective) | objective restated verbatim each iteration; diff ≠ 0 | re-anchor rule (systems-prompts.md §10.5); critic checks against *payload* criteria, not current claim |
| 6 | **Unverifiable requirement** (loop can never confirm success) | verifier returns `method: judged` with low confidence twice | plan-gate rejects untestable criteria up front; runtime: park for human (loop bomb red-team case) |
| 7 | **Tool flake inside ACT** (transient failures read as task failures) | port-level error class | retry-once at the port with backoff; ≥ 2 flakes → `err-` entry `class: flaky` (improvement.md §3) |
| 8 | **Infinite decomposition** (replan spawns replans) | replan counter; child-task depth | replans ≤ 2; subtask depth ≤ 2; beyond → human |
| 9 | **Verification theater** (loop "passes" its own weak checks) | scorer/verifier share a model with the author | model-diversity rule; verifier must prefer executed checks; authors never self-certify |
| 10 | **Cross-loop interference** (two loops mutate shared state) | single-writer violations | memory single-writer; artifacts immutable; VRAM scheduler serializes T2 |
| 11 | **Stale gathered context** (evidence outdated mid-loop) | corpus version stamp in bundle header | re-GATHER on every iteration, not just the first; retrieval cache keyed by corpus version |
| 12 | **Silent stop-condition bypass** (loop swallows its own failure) | delivery without verdict file | port blocks DELIVERY transition unless verdict exists (fail-closed) |

## 7. Guardrail stack (defense in depth, bottom-up)

1. **Port layer (mechanical, free)** — schema validation, state legality, budget metering, side-effect allowlists, repetition/timeout kill, fail-closed transitions. Catches breaks 1, 3, 4, 7, 12 without spending a token.
2. **Manager layer (procedural)** — loop caps, flip-flop detection, escalation floors, error-memory-citation-before-retry, replan bounds. Catches 2, 5, 8.
3. **Review layer (model judgment, diversified)** — critic/scorer/verifier separation, executed-over-judged checks. Catches 6, 9.
4. **Human layer (gates)** — external/irreversible side effects, promotions, activations, ladder rung 6. The layer that never automates away (training.md §10).
5. **Audit layer (after the fact)** — calls.jsonl replay, red-team drills at every checkpoint, improvement-loop mining of the error ledger so each break mode's *recurrence* trends to zero.

The design intent in one line: **loops are cheap to run, loud to fail, and impossible
to exit silently.**
