# agent.md — Architecture & Operating Doctrine

The constitution of the harness: planes, agents, states, lifecycle, failure domains, observability.

---

## 1. Overall architecture

The harness is a **supervised hierarchy**, not a swarm. One Manager owns every task's
state machine; specialized subagents do scoped work and return compact reports. All
durable truth lives on the filesystem; models are stateless workers behind ports.

```
User / schedule / n8n trigger
        │
        ▼
   ┌─────────┐   classify    ┌──────────────┐
   │ Manager │──────────────▶│ Model Router │ (tier decision, routing.md)
   └────┬────┘               └──────────────┘
        │ PLANNING state
        ▼
   ┌─────────┐  plan.md + todos
   │ Planner │─────────────────▶ runs/<id>/plan/
   └────┬────┘
        │ Manager gate: plan approved (auto or human, by risk class)
        ▼ EXECUTION state
   ┌───────────────────────────────┐
   │ Executor(s) / specialist pool │──▶ runs/<id>/artifacts/
   └────┬──────────────────────────┘
        │ per-step
        ▼
   critic ──▶ revise ──▶ scorer ──▶ verifier   (bounded loop, ≤ max_loops)
        │ pass                                  fail → error memory + retry/reassign
        ▼
   DELIVERY: final report + artifacts manifest + memory writes
```

Three planes (overview §3): **control** (LangGraph graphs), **state** (files + Qdrant),
**execution** (Ollama/llama.cpp/tools). No agent talks to a runtime directly — only
through `ports/` adapters. This is what makes every model and tool swappable.

## 2. Design goals & constraints

Goals (ranked): local-first · offline resilience · modularity · swappable models ·
reproducibility · strong verification · long-horizon planning · safe self-improvement ·
low context waste · consistent handoffs.

Hard constraints:

| Constraint | Consequence |
|---|---|
| 8 GB VRAM, 32 GB RAM | One resident large model; tiers top out at ~14B Q4; serialize T2 work; KV-cache quant q8_0 default |
| Windows 11 host | Prefer processes + Docker Desktop services; no OS-level container assumptions in agent logic |
| Internet may be absent | Every agent must have a defined degraded behavior (offline-ops steward, §5); no tool may be "required-online" without a declared fallback |
| Small local models (3–9B) | Schemas over prose in all inter-agent traffic; short scoped contexts; verification is mandatory because worker competence is modest |
| Single user, single box | No multi-tenant/authz complexity; human approval gates are cheap and used liberally |

Doctrine invariants (violations are bugs, not judgment calls):

1. **Planning artifacts never mix with execution artifacts.** Separate directories; executors read plans read-only.
2. **Retrieval before generation** whenever memory could plausibly contain relevant material (memory.md §6).
3. **No unverified delivery.** Every task exits through the verifier or through an explicit human waiver recorded in the run log.
4. **Every loop has a hard stop** (`max_loops`, wall-clock, token budget). On exhaustion: escalate or fail loudly, never spin.
5. **Failures are written before retries.** A retry that doesn't cite the error-memory entry of the previous failure is rejected by the Manager.
6. **Models are roles.** Code and prompts reference tiers/roles; the registry maps roles to concrete models.

## 3. Control plane vs execution plane

**Control plane** (LangGraph): the Manager graph, the planner subgraph, the
verification loop subgraph, the routing policy. Deterministic where possible —
state transitions, gates, and budgets are code, not model output. Model calls
inside the control plane are limited to classification and judgment nodes.

**Execution plane**: everything that touches the world — file writes, shell, ComfyUI,
TTS, n8n deploys, web fetch, training runs. Execution-plane actions are always:
(a) initiated from EXECUTION state, (b) attributed to a task ID, (c) logged with
inputs/outputs to `runs/<id>/logs/`, (d) reversible or gated (side-effect classes below).

Side-effect classes: `read` (free) · `write-scoped` (inside `runs/<id>/`, free) ·
`write-shared` (memory: curator only; vaults: per the second-brain vault-write policy) · `external` (n8n deploy,
network POST, package install — requires gate) · `irreversible` (delete outside run
dir, money, messages to humans — always human-approved).

## 4. Agent taxonomy

All agents = one YAML registry entry + one system prompt file + a scoped toolset.
"Agent" here means a role configuration, not a process; the same base model may serve
several roles at different temperatures/prompts.

| Agent | Plane | Purpose | Default tier (routing.md) | Writes to |
|---|---|---|---|---|
| **manager** | control | owns task state machine, gates, delegation, budgets | T1 | task.json, run log |
| **advisor** | control | pre-planning consultation: clarifying questions, feasibility, risk class | T2 | plan/advice.md |
| **planner** | control | decomposition → plan.md + todo list + acceptance criteria | T2 | plan/ only |
| **executor** | execution | carries out one plan step with scoped context | T1 | artifacts/ |
| **researcher** | execution | multi-hop investigation (SearXNG/Crawl4AI online; corpus offline) | T1 | reports/ |
| **retriever** | execution | memory/vector search, assembles evidence bundles | T0 | reports/evidence-*.md |
| **coder** | execution | code generation/modification + self-test | T1–T2 | artifacts/ |
| **critic** | control | finds flaws vs. acceptance criteria; never fixes | T1 (≠ executor's model when possible) | reports/critique-*.md |
| **scorer** | control | rubric → numeric scorecard (handoff.md §7) | T0–T1 | scores/ |
| **verifier** | control | binary gate: does artifact meet contract? runs checks/tests where possible | T1 | scores/verdict-*.json |
| **memory-curator** | state | the only writer to shared memory; dedupe, summarize, expire | T1 | memory/ |
| **tool-router** | control | selects tools/MCP servers for a step; checks offline availability | T0 | route decisions in log |
| **model-router** | control | tier selection + fallback ladder (routing.md) | T0 (mostly rules) | route decisions in log |
| **workflow-builder** | execution | detects automation patterns → n8n JSON (n8n.md) | T2 | artifacts/workflows/ |
| **training-orchestrator** | execution | governed LoRA/QLoRA/DPO pipeline (training.md) | T2 + human | training/ |
| **offline-ops steward** | control | health checks, model/asset presence, degraded-mode switching, cache warmth | T0 + rules | ops log, status file |

Practical now: all rows except training-orchestrator (near-term experimental as a
human-triggered pipeline; agent-initiated is research-grade).

Sample registry entry (`harness/registry/agents.yaml`):

```yaml
critic:
  version: 3
  prompt: agents/critic.prompt.md
  tier_default: T1
  prefer_model_diversity: true      # avoid scoring own model's output
  tools: [read_run_files, read_memory]
  side_effects: [read]
  context_budget_tokens: 6000
  outputs: {report: "reports/critique-{step}.md", schema: schemas/critique.json}
```

## 5. Planning vs execution — the state machine

Two operating states are **explicit and exclusive**; the Manager enforces them.

```
            ┌────────┐
 intake ───▶│ INTAKE │ classify, route, budget
            └───┬────┘
                ▼
          ┌──────────┐   plan rejected (critic)    ┌─────────┐
          │ PLANNING │◀────────────────────────────│  gate   │
          │          │────────────────────────────▶│ (plan   │──approved──┐
          └──────────┘   plan.md + acceptance      │ review) │            ▼
                ▲                                  └─────────┘      ┌───────────┐
                │ replan (bounded: ≤2)                              │ EXECUTION │
                └───────────────────────────────────────────────────│ step loop │
                          verifier fail + plan-level cause          └─────┬─────┘
                                                                          ▼
                                                                 ┌──────────────┐
                                                                 │ VERIFICATION │
                                                                 └───┬──────┬───┘
                                                              pass ▼      ▼ fail (budget left)
                                                          ┌──────────┐   retry/reassign (handoff.md §8)
                                                          │ DELIVERY │   budget gone → FAILED (error memory)
                                                          └──────────┘
```

Rules:

- In PLANNING, **no side effects** beyond `plan/` writes, retriever evidence bundles into `reports/`, and read-only retrieval. The planner cannot call executors, shell, or n8n.
- In EXECUTION, the plan is **immutable**. Discovering the plan is wrong is a verifier-signaled transition back to PLANNING (a "replan", counted and bounded), never an in-place edit.
- The current state is stored in `task.json` and stamped on every log line; any tool call whose side-effect class is illegal for the current state is refused by the port layer, not by prompt goodwill.
- VERIFICATION is a sub-loop: critique → revise → score → verify, at most `max_loops` iterations (default 3), each iteration logged with its scorecard.

## 6. Lifecycle of a task

1. **Intake** — goal recorded verbatim; task ID minted; run dir scaffolded.
2. **Classification** — domain, difficulty, risk, offline-feasibility (routing.md §2). Advisor engaged if ambiguity score high → clarifying questions *before* planning.
3. **Retrieval-first pass** — retriever pulls prior episodes, relevant semantic notes, and **error-memory entries matching this task class**; bundle attached to planner input.
4. **Planning** — plan.md: numbered steps, per-step agent + tier + tools + acceptance criteria + evidence requirements; todos tracked Deep-Agents-style.
5. **Plan gate** — critic reviews plan (feasibility, budget realism, missing steps). Risk class `external`/`irreversible` anywhere in plan → human approval required.
6. **Execution** — Manager dispatches steps to subagents via handoff contracts; each subagent gets a *fresh scoped context* (handoff.md §4), returns compact report + artifact refs.
7. **Verification loop** — per-step and whole-task: critic → revise → scorer → verifier against acceptance criteria; gates at thresholds (routing.md §9).
8. **Delivery** — final report assembled from step reports (never from raw transcripts); artifacts manifest hashed.
9. **Memory writeback** — memory-curator distills episode → episodic entry; new reusable facts → semantic; new procedures → procedural/skill candidates; failures → error ledger. (memory.md §7)
10. **Postmortem (failures only)** — structured `err-*` entry: symptom, root cause guess, what was tried, what to do differently. Referenced automatically on the next similar task.

## 7. Failure domains

Isolated so one domain's failure degrades, not destroys:

| Domain | Typical failure | Containment | Recovery owner |
|---|---|---|---|
| Model runtime | Ollama OOM/hang, model missing | ModelPort timeout + fallback ladder | model-router → offline-ops |
| Single agent | malformed JSON, drift, loop | schema validation at handoff; per-agent budget | manager (retry/reassign) |
| Verification | critic/verifier disagree or deadlock | loop cap; tie → escalate one tier or human | manager |
| State plane | corrupt/partial writes | atomic write-then-rename; manifests with hashes; runs are append-only | offline-ops |
| Vector store | Qdrant down | degrade to filesystem grep + FAISS snapshot | offline-ops |
| Tools/network | internet off, MCP server dead | tool-router checks offline registry flag first; declared fallbacks | tool-router |
| Side-effect pipelines (n8n, training) | bad deploy, bad adapter | staging + human gates + rollback (n8n.md, training.md) | human |
| Whole harness | process crash | Olympus watchdog pattern; task resumes from task.json + last completed step | offline-ops |

Global rule: **crash > corrupt**. When in doubt, fail the task with a clean error-memory
entry rather than deliver unverified output or write suspect memory.

## 8. Observability expectations

- **Every model call** logged: task ID, agent, state, tier, model ID, prompt hash, token counts, latency, outcome. Sink: Langfuse (existing compose file) when up; always also `runs/<id>/logs/calls.jsonl` (offline-safe, greppable).
- **Every state transition** and gate decision logged with reason string.
- **Run replay**: a run dir must be sufficient to reconstruct what happened without the DB — that's the reproducibility bar.
- **Dashboards** (V2): task throughput, verification pass rate on first attempt, replan rate, fallback-ladder engagement rate, per-model score averages (feeds routing table tuning and training data selection).
- **Error-memory citation rate**: % of retries that referenced a prior error entry — the "are we learning" metric.
