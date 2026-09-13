# Pipeline Redesign

## Decision

The anime pipeline remains a modular monolith. Stage boundaries are explicit
contracts; deployment boundaries are not needed for the current local-first
workload.

```text
input
  -> intake/dossier
  -> world bible
  -> references
  -> storyboard
  -> screenplay + prompt ledger
  -> panels
  -> audio + alignment
  -> optional animation
  -> optional VLM review
  -> final assembly
```

The canonical runtime workflow source is:

```text
olympus/engines/pipeline/workflows/
```

Experimental/UI workflows remain in `workflows_active/` and are never loaded
implicitly by runtime code.

## Run Profiles

### Smoke

The smoke profile proves stage connectivity and artifact contracts quickly:

- bounded reference count
- 512x288 panel generation
- no optional character-refinement rerender
- animation off by default
- VLM review skipped explicitly when no multimodal provider is available
- existing sidecars and ComfyUI outputs are resumed, not regenerated

### Production

The production profile preserves quality settings:

- configured production panel resolution
- identity-refinement pass enabled
- full reference set
- animation only when explicitly enabled
- VLM review required when a multimodal provider is selected

## Run Contract

Every `run.py all` invocation writes:

```text
projects/<slug>/run_contract.json
```

The contract records:

- selected profile
- animation mode
- required capabilities
- provider/model availability
- prompt file fingerprints
- expected stage artifacts
- explicit warnings/deviations

This makes a run reproducible and explains why a stage was skipped or degraded.

## Prompt Adherence

Prompt provenance is preserved at panel sidecars:

```text
panels/<block>/<shot>.json
```

Each sidecar records the assembled prompt, seed, model, attempt, and visual
review result. Prompt construction remains deterministic and prioritizes:

1. shot composition and camera intent
2. location/environment anchor
3. canonical character appearance
4. reference identifiers
5. style and no-text constraints

The system never reports visual adherence as reviewed when no multimodal model
is available. It records `vision_judge_unavailable` instead.

## Recovery Rules

- A canonical panel plus sidecar is reusable even if the storyboard ledger was
  not written before a worker died.
- Matching ComfyUI output files are promoted into canonical project paths after
  interruption.
- LLM JSON extraction accepts trailing prose only after extracting the first
  complete JSON value; schema validation still applies.
- Narration failures retain a beat-grounded fallback rather than silently
  producing dead air.
- Voice Studio falls back to local `espeak-ng` when optional Kokoro imports fail.

## Provider Rules

- Ollama and ComfyUI are local defaults.
- NVIDIA NIM is opt-in per capability.
- Hosted/provider absence is detected in preflight, not halfway through a GPU
  stage.
- Future T2I/I2I/I2V providers must implement the generic provider registry;
  stages must not call vendor APIs directly.
