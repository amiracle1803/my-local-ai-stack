# ADR-003: Self-Critique Loop Between Pipeline Stages (Task 5)

## Status
Accepted

## Date
2026-08-17

## Context
The AGENTS.md priority task 5 specified: "Add a second-pass LLM step that compares script vs. generated panels and flags inconsistencies, then propose prompt tweaks or regeneration steps." The user further requested this run *between each stage*, not just at the end.

The pipeline has 11 stages (stage0 → stage1 → stage1_world → stage1r → stage3 → stage2 → stage3b → stage4 → stage3c → stage_vlm_review → stage5), each producing artifacts (JSON, images, audio, video). Without intermediate validation, errors compound: a wrong character voice in stage1 propagates to stage4 audio; a missing location in stage1r causes wrong plates in stage3b.

## Decision
Add a `stage_critique` module that runs after each stage in `run_all()`:

### Core Components
1. **Prompt template** (`prompts/stage_critique.md`): Compares original script + stage purpose + artifacts, returns structured JSON with:
   - `consistency_score` (0.0-1.0)
   - `critical_issues` (typed: character/plot/setting/tone/technical, severity: critical/major/minor)
   - `warnings`
   - `suggested_fixes` (action: regenerate/repair/tweak_prompt/manual_review)
   - `passes` boolean

2. **`stage_critique.py` module**:
   - `run_stage_critique()`: Gathers artifacts, runs LLM call, saves to `logs/critique_<stage>_<ts>.json`
   - `_collect_artifacts()`: Stage-specific artifact paths (JSON, dirs, etc.)
   - `should_retry_stage()`: Default threshold 0.6, or any critical issue
   - `get_retry_actions()`: Extracts actionable commands from suggestions

3. **Integration in `run.py`**:
   - `run_all()` accepts `run_critique=True` and `retry_on_critique=True` params
   - CLI: `run.py all <slug> [--no-critique] [--no-retry]`
   - On critique failure + retry enabled: re-runs stage, then re-critiques

4. **Tests**: `tests/test_stage_critique.py` (8 tests covering model validation, retry logic, transport errors)

### Behavior
- Runs after EACH stage in `run_all()` (not in single `run_stage()` calls)
- On critique failure with retry enabled: re-runs the stage, then re-critiques
- Results stored in `logs/critique_<stage>_<ts>.json` for postmortem
- Previous critiques fed as context to subsequent critiques (cumulative learning)

### Configuration
- Retry threshold: `config.automation.critique_retry_threshold` (default 0.6)
- Disabled via `--no-critique` / `--no-retry` flags

## Alternatives Considered
| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| Only end-to-end critique at stage5 | Simpler | Errors compound; late detection | Rejected |
| Critique only visual stages (3b, 3c) | Fewer LLM calls | Misses upstream errors (voice, world, screenplay) | Rejected |
| Hard-block on critique failure (no retry) | Strict | No auto-recovery; manual intervention every time | Rejected (added retry) |
| Separate critique stage after each | Explicit | Breaks stage ordering; complicates scorecard | Rejected (inline in run_all) |

## Consequences
- **Positive**: Catches drift early (voice mismatch before TTS, missing location before plates). Auto-retry recovers from transient LLM errors. 199 tests pass including 8 new critique tests.
- **Negative**: Doubles LLM calls per stage (stage + critique). Adds ~2-5s per stage. Configurable via flags.
- **Neutral**: Requires Ollama running for `run.py all` with critique enabled (already required for stages).

## Verification
- `pytest tests/ -q` → 199 passed (191 existing + 8 new)
- `run.py all --help` shows `--no-critique` / `--no-retry` flags
- Critique module imports and model validation works