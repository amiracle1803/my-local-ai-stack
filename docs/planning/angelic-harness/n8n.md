# n8n.md — Workflow Synthesis Pipeline

Agents notice repeatable patterns, ask before building, synthesize n8n JSON, and stop
at a human deploy gate. n8n owns the *recurring, side-effectful edges* of the system;
the harness owns reasoning. (n8n is already running locally with an API key configured —
`foundation/`, `olympus.toml [n8n]` — so the deploy bridge exists today.)

---

## 1. Division of labor: harness vs n8n

| Belongs in n8n | Stays in the harness |
|---|---|
| time/webhook/file-watch triggers | anything needing judgment or multi-step reasoning |
| fixed ETL: fetch → transform → store | planning, critique, verification loops |
| notification fan-out, retries, queues | memory writes (single-writer rule) |
| glue between local services (Olympus, voice, ComfyUI) | model routing decisions |

An n8n workflow may *call* the harness (webhook → task intake) for judgment mid-flow;
the harness may *trigger* n8n workflows as tools. Neither embeds the other's job.

## 2. How agents detect workflow opportunities

Signals (collected passively, evaluated by the workflow-builder on a weekly pass and
opportunistically by the Manager at delivery time):

1. **Repetition**: episodic memory shows ≥ 3 near-identical task episodes (same class, same tool sequence, high first-pass verification rate) → automation candidate.
2. **Schedule shape**: user phrases like "every morning / whenever X lands" at intake → immediate candidate, flagged during PLANNING.
3. **Procedural maturity**: a `proc-` memory entry stable across ≥ 3 uses with zero judgment steps ("zero branches taken on model output") → candidate.
4. **Explicit request**: user asks for an automation.

Candidates are recorded as `runs/<id>/artifacts/automation-candidate.md` (pattern,
evidence links, estimated frequency, side effects) — never built on the spot from
signal 1–3; detection and construction are separate decisions.

## 3. Question-asking policy before generating

The workflow-builder must not synthesize from an underspecified pattern. Before building,
it needs answers (from the user, or from the candidate evidence when unambiguous) to:

1. **Trigger**: exact condition — schedule (cron), webhook (from what), file event (which path)?
2. **Idempotency**: what happens if it fires twice / on the same input again?
3. **Failure policy**: retry (how many), alert (where), or halt?
4. **Side-effect bounds**: what may it write/send, and what must it never touch?
5. **Lifetime**: permanent, or until a condition/date?

Policy: **max 5 questions, one round** (AskUser-style at intake, or a parked "blocked"
report otherwise). Unanswerable + non-inferable ⇒ the candidate stays a candidate.
Inferred answers are recorded as assumptions in the workflow card and shown at the
approval gate — the human approves the *assumptions*, not just the JSON.

## 4. Workflow synthesis pipeline

```
candidate ──▶ spec ──▶ template match ──▶ synthesis ──▶ static verify ──▶ dry run ──▶ HUMAN GATE ──▶ deploy ──▶ watch
```

1. **Spec** (`plan/workflow-spec.yaml`): trigger, inputs, steps, outputs, failure policy, side-effect list, assumptions. A PLANNING artifact — synthesis (step 3) runs in EXECUTION and reads it read-only.
2. **Template match**: reuse from `harness/skills/n8n-workflow-json/examples/` + a template library (§6) at ≥ 70 % fit; parameterize rather than regenerate.
3. **Synthesis** (T2 + `n8n-workflow-json` skill): emit workflow JSON. Structure rules: every workflow has an error branch wired to the notification sink; no inline secrets (n8n credential refs only); nodes that leave the machine are name-prefixed `EXT-`.
4. **Static verification**: JSON schema valid → import into n8n **inactive** via API → n8n's own validation passes → node inventory diffed against the spec's side-effect list (any `EXT-` node not in spec = fail).
5. **Dry run**: execute manually via API against sample/sandbox inputs; verifier checks outputs against spec expectations. Workflows with irreversible externals dry-run with those nodes stubbed (n8n "NoOp" swap), stated on the card.
6. **Human approval gate**: card + assumptions + dry-run evidence presented; human activates in the n8n UI (or approves and the bridge flips `active`). **No workflow self-activates. Ever.**
7. **Watch**: execution stats polled by offline-ops; failure-rate > threshold → auto-deactivate + error-memory entry (deactivation restores the approved-inactive state, so it's un-gated, mirroring adapter quarantine).

## 5. Local execution assumptions

- n8n runs in Docker on this machine (`foundation/start-n8n.bat`), reachable at `127.0.0.1:5678`; workflows must function with zero internet — any node needing the net is `EXT-` and the workflow must define its offline behavior (skip + log, or queue).
- Callable local services for nodes: Olympus API (:4600), Ollama (:11434) for LLM nodes (cheap fixed prompts only — judgment belongs in the harness), voice studio, ComfyUI (:8188), Qdrant, harness intake webhook.
- Credentials live in n8n's credential store; the harness never sees or emits them.
- Backup: workflow JSONs exported nightly to `harness/registry/workflows/` (git-tracked) — n8n's DB is not the source of truth, the exported JSON is.

## 6. Reusable workflow templates (seed library)

| Template | Trigger | Pattern |
|---|---|---|
| `tpl-scheduled-harness-task` | cron | fire a harness task intake with a fixed goal, notify on delivery |
| `tpl-file-watch-ingest` | file event | new file in watched dir → Marker/defuddle → curator inbox |
| `tpl-service-health` | cron | ping local services → status file → alert on change (feeds offline-ops) |
| `tpl-vault-digest` | cron | query harness memory / vault → render digest note → `_generated/` |
| `tpl-webhook-bridge` | webhook | external event → scrub → harness intake |
| `tpl-pipeline-step` | manual/webhook | wrap one anime-pipeline stage (parse/panels/tts/ffmpeg) with retries + notify |

Templates are versioned like skills (they live inside the skill pack's `examples/` +
`harness/registry/workflows/templates/`), and every deployed workflow's card records
its template lineage.

## 7. Human approval gates — summary

| Gate | When | Approves |
|---|---|---|
| Build gate | before synthesis, if questions unanswered | the spec + assumptions |
| Deploy gate | always, after dry run | activation of the workflow |
| Modify gate | any edit to an active workflow | the diff (re-runs steps 4–6) |
| External-node gate | any workflow containing `EXT-` nodes | explicit acknowledgment of what leaves the machine |

Auto-deactivation on failure is the only unilateral action, and it only ever returns
the system to a previously approved state.

Labels: §1–§7 are **Practical now** (the n8n API bridge already exists). Automated
weekly opportunity mining from episodic memory is **Near-term experimental** (needs V1
telemetry); everything self-activating is **out of scope by doctrine**.
