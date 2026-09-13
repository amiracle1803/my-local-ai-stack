# Implementation Plan: Script-First Audio-Driven Pipeline

## Overview

Redesign the anime recap pipeline so the source script controls the editorial
spine. The pipeline will extract the story, write narration/dialogue, render
and align audio, then design shots and generate visuals against the timed
screenplay. Existing stage IDs and artifact paths remain stable where possible,
but orchestration order and contracts become explicit.

## Architecture Decisions

- Keep the pipeline as a modular monolith; current failures are contract and
  fidelity failures, not service-boundary failures.
- Add a faithful-source intake mode (`0s`) for scripts that must not be
  transformed or originalized.
- Canonical execution order becomes:

  ```text
  stage0 → stage0_dossier → stage1 → stage1_world → stage2
  → stage4 → stage3 → stage1r → stage3b → stage3c
  → stage_vlm_review → stage5
  ```

- Stage 2 owns the story/narration/dialogue structure before visual planning.
- Stage 4 owns the timed editorial spine before visual shot design.
- Stage 3 enriches the existing screenplay with camera, composition, blocks,
  prompts, and motion. It must not regenerate story beats already written by
  stage 2.
- T2I/I2I/I2V remain provider-capability stages. ComfyUI is the local default;
  NIM/cloud providers remain opt-in.
- Source fidelity is generic. Project-specific anchors belong in an optional
  `fidelity_rules.json`, never in pipeline code.
- Visual quality must never be reported as reviewed when no multimodal VLM is
  installed. The run records an explicit unavailable/degraded state.

## Task List

### Phase 1: Contract Foundation

- [ ] Task 1: Change canonical `STAGE_ORDER` to stage2-before-stage4-before-stage3.
  - Acceptance: `Scores.require_stage()` enforces the new order.
  - Verification: score gate tests cover stage2 → stage4 → stage3 → stage1r.
  - Files: `pipeline/blueprint.py`, `tests/test_scores.py`.

- [ ] Task 2: Add faithful source intake mode `0s`.
  - Acceptance: source is copied/read verbatim; no transformation map is run.
  - Verification: source hash and scene index tests.
  - Files: `pipeline/stage0_source.py`, `run.py`, blueprint tests.

- [ ] Task 3: Stabilize source-fidelity gate.
  - Acceptance: generic scripts are evaluated from source entities/anchors;
    optional project rules can be strict; no Bloodline-specific assumptions in
    pipeline code.
  - Verification: generic faithful story, transformed story, and unrelated
    substitution fixtures.
  - Files: `pipeline/source_fidelity.py`, `tests/test_source_fidelity.py`.

### Checkpoint: Contracts

- [ ] Full unit suite passes.
- [ ] A source project stops before TTS when screenplay fidelity fails.
- [ ] A faithful source project proceeds past stage 2.

### Phase 2: Audio-First Editorial Spine

- [ ] Task 4: Make stage 2 self-sufficient before storyboard exists.
  - Acceptance: stage2 creates scene/shot structure from source/dossier when no
    storyboard exists, then writes narration/dialogue and screenplay JSON.
  - Verification: stage2 test with no storyboard directory.
  - Files: `pipeline/stage2_screenplay.py`, tests.

- [ ] Task 5: Make stage 4 consume screenplay-only inputs.
  - Acceptance: voices are assigned locally if `voices.json` is absent; audio
    and alignment are written before references/panels.
  - Verification: stage4 test with generated screenplay and no references.
  - Files: `pipeline/stage4_audio.py`, voice config/client, tests.

- [ ] Task 6: Add local TTS provider choices.
  - Acceptance: `auto`, `kokoro`, and `espeak-ng` are visible/configurable;
    Kokoro failure falls back to espeak-ng without losing audio coverage.
  - Verification: `/api/voice/config`, WAV smoke, provider UI smoke.
  - Files: `stack.toml`, `stack/config.py`, `olympus/engines/voice/app.py`,
    `olympus/kernel/app.py`, `olympus/web/*`.

### Phase 3: Visual Planning After Audio

- [ ] Task 7: Change stage 3 from story generation to screenplay enrichment.
  - Acceptance: if screenplay exists, stage3 preserves shot beats, narration,
    dialogue, and IDs; it adds camera/composition/blocks/motion/prompts only.
  - Verification: before/after JSON assertions for beat/narration/dialogue
    preservation.
  - Files: `pipeline/stage3_storyboard.py`, tests.

- [ ] Task 8: Make stage1R depend on stage3 and stage3B depend on both stage1R
  and stage4.
  - Acceptance: visual generation cannot start without timed screenplay and
    references; prompt sidecars include source beat IDs and timing metadata.
  - Verification: score gate tests and panel sidecar tests.
  - Files: `pipeline/run_contract.py`, `stage3b_images.py`, tests.

- [ ] Task 9: Add a prompt ledger.
  - Acceptance: every shot has source text span/beat, narration, dialogue,
    visual prompt, negative prompt, seed, provider, and artifact path.
  - Verification: ledger completeness report for the Bloodline smoke run.
  - Files: new `pipeline/prompt_ledger.py`, stage2/stage3/stage3b tests.

### Checkpoint: Audio-First Smoke

- [ ] Faithful Bloodline source reaches stage4 before any panel generation.
- [ ] Audio files have alignment coverage.
- [ ] Storyboard preserves screenplay beat/narration/dialogue IDs.
- [ ] Prompt ledger has 100% shot coverage.

### Phase 4: Visual/Video Execution

- [ ] Task 10: Keep canonical native ComfyUI API workflows and add runtime
  capability preflight.
  - Acceptance: workflow node contracts validate before queueing; imported UI
    workflows remain reference-only unless converted and validated.
  - Verification: 333 patchable keys and live `/object_info` checks.

- [ ] Task 11: Implement bounded smoke and production profiles.
  - Acceptance: smoke uses low resolution/no optional refinement; production
    preserves quality settings; both are resumable.
  - Verification: interrupted-run recovery test and one-panel ComfyUI smoke.

- [ ] Task 12: Make I2V optional but explicit.
  - Acceptance: animation off produces panels-mode final video; animation on
    requires a validated I2V workflow/model before stage3C starts.
  - Verification: both modes produce truthful scorecard metrics.

### Phase 5: Movie-Grade Evaluation

- [ ] Task 13: Add generic local-vs-NIM evaluation for full stories.
  - Acceptance: grade source fidelity, structure, arcs, pacing, dialogue,
    visual adherence, continuity, audio, and technical finish.
  - Verification: report saved under `comparisons/` and includes model IDs.

- [ ] Task 14: Add a hard source-fidelity repair loop.
  - Acceptance: failed fidelity report blocks audio/visual generation and points
    to missing/contradictory beats; repair can rerun stage2 onward.
  - Verification: unrelated substitution fixture fails; faithful fixture passes.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Reordering stage IDs breaks old projects | High | Preserve artifacts and require migration/backfill; do not rename IDs |
| Stage3 overwrites screenplay fields | High | Snapshot and assert beat/narration/dialogue preservation |
| TTS engine unavailable | Medium | Local espeak-ng fallback and explicit QC flags |
| No local VLM installed | Medium | Preflight and truthful degraded review; no retry loops |
| 8 GB GPU makes full production slow | High | Smoke/production profiles, resume sidecars, one-panel preflight |
| Generic fidelity heuristics produce false positives | Medium | Strict rules only through project-owned `fidelity_rules.json`; default gate uses substitution detection plus warnings |

## Open Questions

- Should the final production profile require a real multimodal VLM, or allow an explicit human-review waiver?
- Should audio-first story timing control shot duration strictly, or should visual beats be allowed to extend within a configured tolerance?
