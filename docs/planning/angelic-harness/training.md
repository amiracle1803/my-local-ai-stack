# training.md — Post-Training Pipeline & Governed Self-Improvement

How open-weight agents get better without getting weirder: a standardized, eval-gated,
rollback-able adapter pipeline. Aspirational autonomy is explicitly fenced off from the
safe near-term architecture.

---

## 1. Honest framing first

| Capability | Label | Why |
|---|---|---|
| Human-triggered QLoRA SFT on ≤8B models (Unsloth, this GPU) | **Practical now** | 8 GB VRAM handles 4-bit QLoRA on 7–9B with seq ≤ 2k, batch 1 + grad-accum; slow but real |
| DPO-style preference tuning on ≤8B | **Practical now / near-term** | Same memory class as SFT with QLoRA; the bottleneck is *data quality*, not compute |
| RLHF-proper (PPO, reward model + policy in memory) | **Not on this box** | Two-model training exceeds the budget; DPO/ORPO/KTO-class methods are the local substitute — "RLHF-like" in this doc always means these |
| Eval-gated promotion, adapter registry, rollback | **Practical now** | It's file+registry engineering, the same doctrine as models/skills |
| Agents *proposing* training runs from harvested data | **Near-term experimental** | Needs V1 telemetry + eval harness first |
| Agents *executing* their own training end-to-end unsupervised | **Research-grade / speculative** | Permanently behind human gates in this design; see §9 |

## 2. Post-training architecture

```
harness/training/
├── datasets/            # staged, versioned: <name>-vN/ {train.jsonl, eval.jsonl, CARD.md}
├── harvest/             # raw candidates auto-collected from telemetry (quarantined)
├── runs/                # one dir per training run: config.yaml, logs, checkpoints
├── adapters/            # produced LoRAs: <base>__<skill>__vN/ {adapter files, ADAPTER_CARD.md}
├── queue/               # promotion queue: adapters awaiting eval + human gate
└── registry → ../registry/adapters.yaml
```

Toolchain: **Unsloth** (QLoRA/DPO trainer, Windows-viable, 4-bit) → merge/export path to
**GGUF** → served via Ollama Modelfile (`ADAPTER` line or merged model) or llama.cpp
`--lora`. Training runs are offline by nature — models and datasets are already local.
Training and serving contend for the same 8 GB → training is a **scheduled exclusive
mode** (offline-ops parks T2 serving during runs; nightly slot per foundation's pattern).

## 3. What gets trained (and what never does)

Adapters target **narrow, measurable competencies**, one per adapter:

- format mastery: emit-valid-handoff-JSON, n8n-workflow-JSON, scorecard JSON;
- role behavior: critic-issue-style, planner-step-granularity;
- domain style: anime prompt phrasing for the pipeline.

Never trained: safety/refusal behavior · gate/routing logic (that's code) · "general
intelligence" hopes. If a competency can be achieved by a skill pack or prompt fix,
**do that first** — adapters are the expensive last resort (decision ladder: prompt →
skill → adapter).

## 4. LoRA / QLoRA workflow (standard run)

1. **Dataset**: curated pairs from telemetry (verified-passing reports = positives) + hand examples. Every dataset ships `CARD.md`: source, size, license, known gaps, curation method. Minimum bar: ≥ 300 high-quality examples for format adapters; below that, use a skill pack instead.
2. **Config as artifact**: `runs/<id>/config.yaml` (base model hash, LoRA rank/alpha/target modules, lr, epochs, seed) — reproducibility means a run can be re-executed byte-for-byte.
3. **Train** (Unsloth, 4-bit base, rank 16–32 typical for format tasks).
4. **Export**: adapter → `adapters/` with `ADAPTER_CARD.md` (base, dataset ref, config ref, intended role, eval results pending).
5. **Evaluate** (§7) → **queue** → **human gate** → **promote** (§6).

## 5. Preference tuning (DPO-style) workflow

- **Pair source — the harness already produces them**: for every verification loop, the failing attempt (rejected) and the passing revision (chosen) on the same payload is a natural preference pair. Scorecards give margins; critic reports explain the delta. This is the single biggest payoff of the verification doctrine for training.
- Pair hygiene: same-payload pairs only · margin ≥ 0.15 weighted-total · scrubbed of secrets/vault content · deduplicated · Claude or human spot-audit of a 5 % sample before any run (claude.md §2).
- Run DPO (or ORPO to skip the reference model and save memory) on top of the SFT adapter, not instead of it.
- KTO-class (unpaired thumbs up/down from human corrections) — Near-term experimental once the dashboard collects reactions.

## 6. Adapter registry, promotion, rollback

`harness/registry/adapters.yaml`:

```yaml
qwen2.5-7b__json-planner__v3:
  base: qwen2.5-7b@ollama        # models.yaml key; weights hash pinned in the run config
  dataset: planner-pairs-v4
  run: runs/TR-20260812-…
  status: candidate | promoted | retired | quarantined
  eval: {qual_suite: 0.94, regression_delta: +0.06, red_team: pass, date: 2026-08-13}
  serving: {ollama_model: "planner-tuned:v3", roles: [planner]}
  approved_by: human@2026-08-13
  rollback_to: qwen2.5-7b__json-planner__v2
```

- **Promotion** = registry flip mapping a *role* to the adapter-backed model — the same one-line swap doctrine as base models (routing.md §7). Old mapping retained as fallback rung for 2 weeks.
- **Rollback** = flip back; adapters are additive files, the base is never mutated, so rollback is instant and total.
- **Quarantine**: any promoted adapter implicated in a verification-pass-rate drop > 5 % (rolling window, watched by offline-ops) is auto-demoted to `quarantined` and the role reverts — automatic rollback is the one *un*-gated action, because it restores the prior approved state.

## 7. Model & adapter qualification tests

One suite qualifies **any** model change: new base model, new quant, new adapter, or
runtime swap. (`harness/evals/`)

| Layer | Contents | Gate |
|---|---|---|
| Smoke | loads, generates, respects num_ctx, JSON mode works | hard pass |
| Format | 50 schema-output cases per role (handoff JSON, scorecards, n8n JSON) | ≥ 95 % valid |
| Role golden tasks | 10–20 frozen tasks per role with verifier-checkable outputs | ≥ baseline model's score |
| Regression | the full **prompt-regression suite** (§8) | no criterion regresses > 2 % |
| Red team | injection-in-data cases, scope-creep bait, refusal probes (todos.md) | hard pass |
| Perf | tokens/s, VRAM headroom, keep-alive behavior on this GPU | recorded, soft gate |

## 8. Avoiding catastrophic prompt regressions

The failure mode: an adapter (or a prompt edit — same machinery) improves the target
skill while silently breaking instruction-following elsewhere.

- **Frozen regression corpus**: every base prompt × representative payloads × expected schema/behavior assertions, run before any promotion (§7 row 4). Prompts and adapters are both "firmware"; both go through it.
- **Off-target sampling**: qualification always includes tasks *outside* the adapter's target competency, weighted toward whatever the base model was already good at.
- **One variable at a time**: never promote an adapter and a prompt change in the same window; attribution requires isolation.
- **Canary period**: newly promoted adapters serve with `canary: true` for N=20 tasks — scorecards segmented, auto-quarantine armed (§6).
- **Baseline pinning**: the un-adapted base model remains registered and one registry-flip away, forever.

## 9. Safe recursive self-improvement — the governance fence

The loop everyone wants: *agent notices weakness → harvests data → trains adapter →
gets better*. The fence, stage by stage:

| Stage | Actor | Automation status |
|---|---|---|
| Detect weakness (scorecard/error-memory trend) | offline-ops + curator | **Automated now** (it's telemetry) |
| Propose training run (dataset spec + expected lift + eval plan) | training-orchestrator agent | **Near-term experimental** — proposal lands in `queue/` as a document |
| Approve dataset & run | **human, always** | never automated |
| Execute training run | pipeline (scheduled, exclusive mode) | automated once approved |
| Evaluate against §7 suite | pipeline | automated |
| Promote to a serving role | **human, always** | never automated |
| Monitor + auto-rollback | offline-ops | automated (restores approved state only) |

Hard rules: the training-orchestrator has **no write access** to `registry/adapters.yaml`
status fields beyond `candidate` · no training on data the scrubber hasn't passed · no
adapter may train on outputs produced by itself post-promotion without a fresh human
data audit (drift-amplification guard) · maximum one self-proposed run in flight at a
time · every proposal cites the error-memory/scorecard evidence that motivated it.

"An agent silently becomes different" is the definition of failure here; the design goal
is that every behavioral change of the system maps to a signed registry commit.

## 10. What may be automated vs must stay human

| Automatable now | Human forever (this design) |
|---|---|
| telemetry harvest → quarantined candidates | dataset approval |
| eval suite execution + reports | promotion of adapters, prompts, skills |
| canary monitoring, auto-rollback to approved state | expanding the training-orchestrator's own permissions |
| dataset hygiene checks (dedupe, scrub, margin filter) | any change to this governance table |
