# routing.md — Task Classification & Model Routing Policy

How every task/step gets a model: classify → tier → concrete model → fallback ladder.
Code and prompts reference **tiers/roles only**; the registry maps them to models.

---

## 1. Principles

1. **Local first, remote only by explicit policy.** Remote (Claude API etc.) is a tier, disabled by default, enabled per-task-class in the routing table — never chosen ad hoc by an agent.
2. **Cheapest tier that passes verification.** Routing optimizes for verified output per watt, not for first-draft eloquence; the verifier loop is the safety net that makes cheap-first viable.
3. **Deterministic where possible.** Classification is rules + a T0 model vote; tier selection is a lookup; only ambiguous cases consume model judgment.
4. **One resident large model.** On 8 GB VRAM the router is also a **scheduler**: T2 requests queue; the router prefers reusing the loaded model (keep-alive) over swapping.

## 2. Task classification policy

Every task (and every plan step) gets a classification record:

```yaml
class:
  domain: coding | research | writing | analysis | media | ops | workflow | memory
  difficulty: trivial | easy | standard | hard | frontier
  risk: low | medium | high            # side-effect class of worst step
  offline_ok: true | false             # can complete with zero network
  structure: freeform | schema         # is output machine-validated?
  context_need: small | medium | large # estimated evidence size
```

Classification procedure (Practical now):

1. **Rules first**: keyword/tool heuristics (mentions of files → coding; "why/compare" → research; recurring trigger → workflow). Risk from requested side-effect classes.
2. **T0 vote**: triage model (qwen2.5:3b-class) emits the record as JSON; schema-validated.
3. **Disagreement or `frontier`** → advisor (T2) classifies, may ask the user clarifying questions.
4. Difficulty calibrates from history: if this task-class's first-attempt verification pass rate < 60 %, bump difficulty one level (data from scorecards, agent.md §8).

## 3. Capability tiers (grounded in this machine)

| Tier | Role | Current mapping (registry, editable) | Fits in | Notes |
|---|---|---|---|---|
| **T0** | triage, extraction, scoring, embeddings-adjacent | `qwen2.5-3b@ollama` | VRAM, instant | always resident; also the "is it JSON" fixer |
| **T1** | workhorse: execution, research, critique | `qwen2.5-7b@ollama`, `ornith-9b@ollama` | VRAM | default for most steps |
| **T2** | planner/advisor/coder-hard: strong reasoning | `qwen3-8b@ollama` (thinking mode), `qwen2.5-14b-q4@llamacpp` (CPU-offload) | partial offload | serialized; queue depth 1 |
| **T3** | frontier escalation | Claude API (see claude.md) — **disabled by default, never offline** | remote | explicit policy + user-visible flag only |
| **F** | fallback rung | `hermes` OpenAI-compatible server :8642 (existing) | — | last local resort when Ollama is down |

Model swap = edit `harness/registry/models.yaml`; zero code changes. That file is the
single source of truth; `olympus.toml [models]` becomes a consumer of it in V1 (todos.md).

Sample routing table (`harness/registry/routing.yaml`):

```yaml
defaults: {trivial: T0, easy: T1, standard: T1, hard: T2, frontier: T2}
overrides:
  - {domain: workflow, difficulty: standard, tier: T2}   # n8n JSON demands structure
  - {domain: memory, tier: T0}
  - {agent: planner, min_tier: T2}                       # planning never below T2
  - {agent: critic, rule: prefer_model_diversity}        # judge ≠ author model when possible
escalation:
  frontier_to_T3: {enabled: false, requires: human_flag, only_domains: [coding, analysis]}
offline_mode:
  T3: forbidden
  T2: allowed (llamacpp pinned GGUF must exist on disk — offline-ops verifies)
```

## 4. Latency / cost / offline tradeoffs

| Factor | T0 | T1 | T2 | T3 |
|---|---|---|---|---|
| Latency (typical) | <2 s | 5–30 s | 30 s–5 min (offload) | 5–60 s (network) |
| Cost | ~0 | electricity | electricity + occupies GPU | $ + privacy egress |
| Offline | ✅ | ✅ | ✅ if GGUF present | ❌ |
| Use when | classify, score, extract | 80 % of steps | plans, hard code, workflow synthesis | verified-stuck + human flag |

Inference optimizations the router assumes (offline-ops maintains them):

- **KV-cache quantization** q8_0 default (halves KV memory, negligible quality loss); q4_0 only for long-context T1 jobs.
- **Keep-alive scheduling**: batch same-model steps together; `keep_alive` tuned so the workhorse stays warm between steps.
- **Context budgeting**: default `num_ctx` 8k (T0/T1) / 16k (T2); the router *rejects* oversized evidence bundles back to the retriever for compression rather than raising ctx (memory.md §8).
- **Retrieval cache**: query-normalized embedding + result cache keyed by corpus version — repeated retrieval is free.
- **Prompt prefix stability**: system prompts are frozen artifacts so llama.cpp prompt-cache/prefix reuse actually hits.

## 5. Fallback policy when a model fails

Failure = timeout, runtime error, OOM, or schema-invalid output after 1 in-place repair
attempt (T0 JSON fixer). Quality failures are handled separately: a scorer weighted
total below the hard floor (< 0.50, §9) enters the ladder directly at rung 3 — never
rungs 1–2, which exist for runtime/format failures only. A verifier fail *above* the
floor follows the quality retry chain in handoff.md §8 instead of this ladder.

Ladder (each rung logged; each retry must cite the error-memory entry of the previous rung):

```
1. same model, repair prompt (once; only for schema/format failures)
2. same tier, sibling model            (ornith-9b ↔ qwen2.5-7b)
3. tier +1 (T1→T2), fresh scoped context, critique of failed attempt attached
4. same-tier different *runtime*       (ollama → llamacpp pinned GGUF → hermes)
5. decompose: manager asks planner to split the step
6. human: structured question with evidence bundle, task parked (not spinning)
```

Rungs 1–4 automatic; rung 5 counts as a replan; rung 6 is a hard stop.
Never: silent retry loops, tier-down retries after quality failures, unlogged rung skips.

## 6. Local vs remote routing policy

- Default posture: **remote forbidden**. `T3.enabled=false` in the table.
- Enabling requires all of: user set the flag (per task or per domain) · task class in the allowlist · data-egress check passed (no vault/secret content in the bundle — a T0 scrubber verifies) · internet actually up (offline-ops).
- Remote results are treated as *advice*: they re-enter the pipeline as evidence for a local executor/verifier pass, so the system never depends on remote availability for its verified state.

## 7. Plug-and-swap model interface standard (`ModelPort`)

Every backend implements one interface; agents see only roles.

```yaml
# harness/registry/models.yaml — one entry per concrete model
qwen3-8b@ollama:
  runtime: ollama                # ollama | llamacpp | openai-compat (hermes, litellm, remote)
  endpoint: http://127.0.0.1:11434
  model: "qwen3:8b"
  capabilities: {tools: true, json_mode: true, thinking: true, ctx_max: 32768}
  defaults: {temperature: 0.6, num_ctx: 16384, kv_quant: q8_0, keep_alive: 10m}
  qualified: true                # passed qualification suite (training.md §7)
  offline_asset: "E:\\models\\qwen3-8b-q4_k_m.gguf"   # for the llamacpp rung
```

`ModelPort` contract (pseudocode-level): `generate(role, messages, schema?, budget) → {text|json, usage, model_id}`.
Requirements: OpenAI-compatible wire format everywhere; structured-output enforcement
(json_schema when runtime supports it, else T0 repair pass); usage accounting mandatory;
`model_id` echoed into logs so every artifact is attributable. LiteLLM is an *optional*
implementation of ModelPort, not an architectural dependency.

Swap procedure: add registry entry → run qualification suite (training.md §7) →
flip role mapping → keep old entry for 1 week as fallback rung 2. No code edits.

## 8. When to escalate to stronger reasoning agents

Escalate a step to T2 (or advisor) when any of:

- verification failed twice at current tier for *quality* (not format) reasons;
- self-reported confidence < 0.6 **and** scorer < 0.7 (thresholds §9);
- the step requires cross-artifact consistency (plan-wide reasoning);
- error memory shows this task-class historically fails at T1 (≥2 prior entries);
- branch exploration is warranted (ToT-style: generate k plan candidates, scorer picks — T2 only, k ≤ 3, one round).

Reasoning-technique placement (from the doctrine's approved list): CoT hidden-by-default
everywhere (systems-prompts.md §9) · ReAct = the executor's tool loop · self-consistency
(k=3 votes) for T0/T1 classification and scoring only · ToT for T2 planning only ·
recursive decomposition = rung 5 · retrieval-while-composing for researcher/writer ·
verification-before-finalization is universal and non-optional.

## 9. Confidence thresholds & score gating

Scores are 0–1 from the scorer's rubric (handoff.md §7). Defaults (per-domain overrides in routing.yaml):

| Gate | Threshold | Below threshold |
|---|---|---|
| Step acceptance | ≥ 0.80 | critique → revise loop (≤ max_loops) |
| Hard floor | < 0.50 | don't revise — fallback ladder rung 3 (escalate) |
| Task delivery | ≥ 0.80 all steps AND verifier verdict = pass | retry/replan per budget |
| Plan approval | critic finds 0 blocking issues | replan (≤ 2) |
| Self-consistency agreement | ≥ 2/3 votes | escalate classification to advisor |
| Memory write | curator confidence ≥ 0.7 | park in memory/inbox for human review |

Calibration loop (Near-term experimental): scorer scores are periodically audited
against human spot-checks; per-model score offsets stored in the registry.

## 10. Routing pseudocode

```python
def route(step, task, registry, history):
    cls = classify(step, task)                       # §2: rules → T0 vote → advisor
    tier = lookup(registry.routing, cls, step.agent) # table + overrides
    if offline() and tier == "T3": tier = "T2"
    tier = max(tier, escalation_floor(history, cls)) # §8: error-memory bumps
    model = registry.role_model(tier, prefer_loaded=True,
                                diversity_from=step.author_model if step.agent=="critic" else None)
    return Route(tier, model, ladder=fallbacks(model, registry), budget=budget_for(cls))

def execute_with_ladder(route, invoke):
    for rung, model in enumerate(route.ladder):
        cite_error_memory_if_retry(rung)
        result = invoke(model, timeout=route.budget.step_timeout)
        if result.ok and valid_schema(result): return result
        log_failure(rung, model, result); write_error_memory(result)
    return park_for_human(evidence_bundle())
```
