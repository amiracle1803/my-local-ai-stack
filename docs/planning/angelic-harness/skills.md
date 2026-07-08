# skills.md — Skills System

Progressive-loading capability packs: the difference between what an agent *is*
(prompt), what it *knows* (memory), and what it *can be taught on demand* (skills).

---

## 1. Role and precedent

Skills are versioned instruction packs loaded into context only when relevant —
the pattern already working in this repo (Claude Code skills, obsidian-skills,
`olympus/skills/`). The harness standardizes the same idea for local agents:
small models especially benefit, because a loaded skill substitutes for capability
the base model lacks.

## 2. Skills taxonomy

| Kind | Contents | Example |
|---|---|---|
| **Procedure** | verified step-by-step recipes | `comfyui-safe-generation` (restart-between-characters flow) |
| **Format** | output syntax/schema mastery | `n8n-workflow-json`, `obsidian-markdown` |
| **Domain** | compressed domain knowledge + heuristics | `anime-prompt-engineering`, `ffmpeg-assembly` |
| **Tool-use** | how to drive a specific tool well | `qdrant-query-patterns`, `whisper-cpp-usage` |
| **Policy** | behavioral overlays for special contexts | `vault-write-etiquette`, `degraded-offline-mode` |

## 3. Skill pack format

One directory per skill under `harness/skills/<name>/`:

```
harness/skills/n8n-workflow-json/
├── SKILL.md            # the pack itself (frontmatter + instructions)
├── references/         # deep material, loaded only on demand (progressive disclosure)
│   └── node-catalog.md
├── examples/           # few-shot exemplars (small models need these)
│   └── webhook-to-vault.json
└── eval/               # golden checks proving the skill works (→ §8)
    └── cases.yaml
```

`SKILL.md` frontmatter:

```yaml
---
name: n8n-workflow-json
version: 2.1.0
kind: format
description: Author valid n8n workflow JSON for local n8n 1.x. Trigger on workflow synthesis steps.
triggers: [n8n, workflow, automation]
agents: [workflow-builder, coder]          # who may load it
min_tier: T1                               # below this tier the skill is refused (won't help)
tokens_core: 900                           # cost of loading SKILL.md body
dependencies: {skills: [], tools: [n8n-api], services: [n8n]}
offline: {self: true, degraded_without: [n8n]}   # pack usable offline; deploy step needs service
provenance: {source: proc-20260615-n8n-recipe, author: human|curator, evals_passed: 2026-07-01}
---
```

Body structure (enforced by lint): *When to use* → *Core instructions* → *Pitfalls
(distilled from error memory)* → *Pointers into references/* (never inline the deep material).

## 4. Loading policy (progressive disclosure)

Three levels, matching how this repo's Claude skills already behave:

1. **Index level** — every agent's context includes only the skills index relevant to it: name + one-line description (~15 tokens/skill). Source: `registry/skills.yaml`.
2. **Core level** — when a step's classification or payload triggers match, the tool-router injects `SKILL.md` body into the payload (counted against the skill budget, memory.md §8: ≤ 1.2k tokens ⇒ practical max 1–2 packs per step).
3. **Reference level** — the agent reads `references/*` files itself, on demand, within its tool budget.

Selection: deterministic trigger match first; T0 relevance vote for ties; the Manager
may pin skills in the handoff payload (`"skills": ["n8n-workflow-json"]`). Over-budget →
highest-relevance pack wins; never truncate a pack mid-body (all-or-nothing).

## 5. Versioning & dependencies

- SemVer. Breaking = changed instructions that alter output format or behavior → major bump.
- The registry maps skill name → active version; old versions retained in git (rollback = registry edit, same doctrine as models/adapters).
- Dependency declarations (frontmatter) are checked at load time by the tool-router: missing tool/service → load the skill in its declared degraded form or refuse with a logged reason.
- A skill may require another skill (`dependencies.skills`); resolution is one level deep by design — deeper chains indicate the skill should be split or promoted to a tool.

## 6. Offline availability requirements

- All packs are plain files — inherently offline.
- Every pack **must** declare `offline:` behavior. Packs whose *purpose* is online (e.g. `crawl4ai-research`) must include a "when offline" section pointing to the local-corpus alternative.
- Offline-ops steward's preflight includes: every registry-active skill exists on disk, lints clean, and its declared service dependencies are flagged with current availability.

## 7. Memory vs skill vs tool — placement decision

| Question | If yes → |
|---|---|
| Is it executable logic with defined I/O? | **Tool** (code/MCP), not prose |
| Is it a fact or account of events? | **Memory** (semantic/episodic) |
| Is it a *way of doing* something, needed only sometimes, expressible as instructions? | **Skill** |
| Is it needed on *every* step by an agent? | **System prompt** (and keep it tiny) |

Graduation pipeline (Practical now as human-triggered, Near-term experimental automated):

```
err-/proc- memory entries ──(curator notices ≥3 uses / recurring pitfall)──▶ skill candidate
 skill candidate ──(human review + eval cases written)──▶ registered skill v1.0.0
 skill used in every step of a domain ──▶ consider tool-ification or prompt absorption
```

The reverse also holds: a skill that is really just one fact gets demoted to a semantic
memory entry; a skill that turned into 300 lines of pseudo-code gets promoted to a tool.

## 8. Skill evaluation & retirement

- **Eval cases** (`eval/cases.yaml`): input payload sketch + expected properties of output (schema-valid, contains X, verifier-passes). Run by the standard eval harness (todos.md) on: skill registration, skill version bump, and base-model swap (a skill tuned to one model's quirks must re-qualify — same rule as adapters, training.md §7).
- **Telemetry**: scorecards record which skills were loaded (handoff payload is logged), so per-skill lift is measurable: verification pass rate with vs. without the pack (Near-term experimental analysis; data collection is Practical now).
- **Retirement triggers**: superseded by tool · zero loads in 90 days · negative/neutral measured lift · dependency permanently gone. Retirement = registry deactivation + move to `skills/_retired/` (git keeps history); never silent deletion.
- **Anti-drift**: skills are frozen artifacts like prompts — agents may *propose* skill edits (as suggested memory), only the human (V1) or a gated curator flow (V2+) may change registered packs.
