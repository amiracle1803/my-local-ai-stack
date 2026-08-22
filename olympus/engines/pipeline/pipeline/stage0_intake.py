"""Stage 0B -- GENERATE (original spec `aether-studio-original-spec-stages0-2.md`
STAGE 0 -> Stage 0B; design `anime-pipeline-v2-design.md` 4. Stage 0 THREE MODES,
0B bullet). Only mode 0B (original-from-brief) is implemented here; 0A/0I land
later.

Three passes, all through :class:`~pipeline.llm.PipelineLLM`:

- **Pass 1 -- Story Blueprint** (temp 0.3, JSON, schema
  :class:`~pipeline.schemas.stage0.StoryBlueprint`). Honors
  ``automation.auto_approve_blueprint``: when false, the draft is written to
  ``blueprint_draft.json`` and the run stops cleanly with stage status
  ``awaiting_approval`` -- no Pass 2/3 work happens until a later call finds
  that draft file (re-running promotes it, whether or not the flag flipped
  back, since a human is assumed to have reviewed it in between).
- **Pass 2 -- Scene-by-scene prose** (temp 0.5 draft -> temp 0.2 critique ->
  temp 0.5 revise, per design's v2 "prose-quality loop"), one call trio per
  scene, plus a single condense/expand rewrite when the word count enforcement
  band is missed, plus automated (no-LLM) per-scene checks.
- **Pass 3 -- Integration** (no LLM): scene markers, name/location presence,
  oversized-scene check, ``input/script.txt`` write, ``structure_completeness``
  metric, ``scores.stage_done("stage0")``.

Design note on the story-pollution guard (`blueprint.py`): mode 0B has no
pre-existing script at intake time -- ``new-project`` is seeded with the brief
file itself (so the guard has *something* to fingerprint from creation). Once
Pass 3 produces the real ``script.txt``, this module re-pins
``blueprint.title_hash`` to the generated script: from that point on
(stage1..stage5) the generated script *is* the project's identity, and the
guard protects it from being swapped underneath an in-progress project -- it
was never meant to freeze the brief-to-prose transformation that intake itself
performs.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frontmatter

from .agi_scorer import scorer_enabled
from .blueprint import Blueprint, compute_title_hash
from .chunking import chunk_text
from .config import ENGINE_ROOT, PipelineConfig
from .llm import PipelineLLM
from .schemas.stage0 import (
    BlueprintCharacter,
    IntegrationReport,
    SceneChecks,
    ScenePlan,
    SceneProse,
    StoryBlueprint,
    ThreeActStructure,
)
from .scores import Scores
from ._util import now_iso

PROMPTS_DIR = ENGINE_ROOT / "prompts"

# Pass 2 word-target multipliers (original spec: "+30% for climax, -20% for
# transitional scenes").
_CLIMAX_MULT = 1.3
_TRANSITIONAL_MULT = 0.8
_MIN_SCENE_WORDS = 50

# Word-count enforcement band (original spec: >130% condense, <70% expand).
_CONDENSE_ABOVE = 1.30
_EXPAND_BELOW = 0.70

# Quality thresholds (new -- enforce movie-grade script)
_MIN_AGI_FIDELITY = 0.50
_MIN_AGI_CAUSAL_FLOW = 0.50
_MIN_AGI_CONSISTENCY = 0.50
_MAX_CRITIQUE_ITERATIONS = 3

# Keyword heuristic for "transitional" scenes -- the spec describes the
# adjustment but leaves detection to editorial judgment; this module has no
# LLM call for it, so a small curated keyword scan stands in (see M1-FINISH
# report "deviations" for why).
_TRANSITIONAL_HINTS = (
    "transition", "travel", "montage", "journey", "aftermath", "downtime",
    "in between", "on the way", "days pass", "time skip", "interlude",
)

# Heuristic "static description opener" pattern for the automated
# opens_on_action_or_dialogue check (see module docstring / report).
_STATIC_OPEN_RE = re.compile(
    r"^(the|a|an|it|there)\b.{0,60}?\b(was|were|stood|sat|lay|loomed|stretched|"
    r"hung|drifted)\b",
    re.IGNORECASE,
)
_QUOTE_CHARS = ('"', "“", "”")


class Stage0Error(ValueError):
    """Raised for stage0-specific input problems (missing/invalid brief, etc.)."""


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Brief loading
# --------------------------------------------------------------------------
@dataclass
class Brief:
    """A parsed creative brief: YAML frontmatter (call params) + body text."""

    word_target: int
    text: str
    style_exemplars: list[str] = field(default_factory=list)


def load_brief(path: str | Path) -> Brief:
    """Parse a brief file: frontmatter ``word_target`` (required, int > 0) and
    optional ``style_exemplars`` (string or list of strings); body is the
    freeform creative brief text (genre, tone, protagonist, themes, ...)."""
    post = frontmatter.load(str(path))
    meta = dict(post.metadata)

    if "word_target" not in meta:
        raise Stage0Error(
            f"brief file {path} is missing required frontmatter field "
            "'word_target' (e.g. `word_target: 600`)."
        )
    try:
        word_target = int(meta["word_target"])
    except (TypeError, ValueError) as exc:
        raise Stage0Error(
            f"brief 'word_target' must be an integer, got {meta['word_target']!r}"
        ) from exc
    if word_target <= 0:
        raise Stage0Error(f"brief 'word_target' must be positive, got {word_target}")

    exemplars_raw = meta.get("style_exemplars", [])
    if isinstance(exemplars_raw, str):
        exemplars_raw = [exemplars_raw]
    style_exemplars = [str(e) for e in exemplars_raw]

    text = post.content.strip()
    if not text:
        raise Stage0Error(f"brief file {path} has an empty body (the creative brief text)")

    return Brief(word_target=word_target, text=text, style_exemplars=style_exemplars)


# --------------------------------------------------------------------------
# small pure helpers
# --------------------------------------------------------------------------


def _word_count(text: str) -> int:
    return len(text.split())


def _normalize_words(s: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z']+", s.lower()))


def _world_bible_context(project_dir: Path) -> str:
    """Pass 1 world-bible context input. M1 has no Stage 1 output yet, so a
    fresh project gets an explicit "nothing yet" note; if a future continuity
    run drops a ``world_bible.json`` in the project dir, it is chunked the
    same way Step 1 chunks the script (design 4, Stage 0 bullet) and only the
    first chunk is used as direct context -- multi-chunk summarization for
    long-running continuity is a later enhancement, not needed for one-shot
    generation."""
    wb_path = project_dir / "world_bible.json"
    if not wb_path.exists():
        return (
            "(no existing world bible -- this is a new/first episode; invent "
            "characters, locations, and world rules freely from the brief.)"
        )
    raw = wb_path.read_text(encoding="utf-8")
    chunks = chunk_text(raw)
    return chunks[0].text if chunks else raw


def _summarize_three_act(tas: ThreeActStructure) -> str:
    return (
        f"Act 1 -- inciting incident: {tas.act1.inciting_incident} "
        f"Establishes: {tas.act1.establishes}\n"
        f"Act 2 -- escalation: {tas.act2.escalation} "
        f"Midpoint reversal: {tas.act2.midpoint_reversal} "
        f"What breaks: {tas.act2.what_breaks}\n"
        f"Act 3 -- climax decision: {tas.act3.climax_decision} "
        f"Cost: {tas.act3.cost} Permanent change: {tas.act3.permanent_change}"
    )


def _character_profiles(names: list[str], lookup: dict[str, BlueprintCharacter]) -> str:
    if not names:
        return "(no characters specified for this scene)"
    blocks = []
    for name in names:
        c = lookup.get(name.lower())
        if c is None:
            blocks.append(f"{name}: (no blueprint profile found; use brief context)")
            continue
        blocks.append(
            f"{c.name} ({c.role}): {c.personality_core}. "
            f"Wants: {c.episode_want}. Fears: {c.episode_fear}. "
            f"Arc end: {c.episode_arc_end}."
        )
    return "\n".join(blocks)


def _scene_role(scene_number: int, scene_hints: str, climax_number: int) -> str:
    if scene_number == climax_number:
        return "climax"
    lowered = scene_hints.lower()
    if any(h in lowered for h in _TRANSITIONAL_HINTS):
        return "transitional"
    return "standard"


def _scene_checks(text: str) -> SceneChecks:
    """Automated (no-LLM) per-scene quality checks (original spec Pass 2)."""
    words = text.split()
    first20 = " ".join(words[:20])
    first50 = " ".join(words[:50])
    last50 = " ".join(words[-50:])

    has_quote_open = any(q in first20 for q in _QUOTE_CHARS)
    static_open = bool(_STATIC_OPEN_RE.search(first20)) and not has_quote_open
    opens_ok = has_quote_open or not static_open

    has_dialogue = bool(re.search(r'"[^"]+"', text)) or bool(
        re.search(r"“[^”]+”", text)
    )

    a, b = _normalize_words(first50), _normalize_words(last50)
    ends_differently = True if (not a or not b) else (len(a & b) / len(a | b)) < 0.5

    flags = []
    if not opens_ok:
        flags.append("opens_on_action_or_dialogue")
    if not has_dialogue:
        flags.append("has_dialogue")
    if not ends_differently:
        flags.append("ends_differently")

    return SceneChecks(
        opens_on_action_or_dialogue=opens_ok,
        has_dialogue=has_dialogue,
        ends_differently=ends_differently,
        flags=flags,
    )


def _enforce_word_count(
    text: str,
    target: int,
    base_ctx: dict[str, Any],
    llm: PipelineLLM,
    scene_number: int,
) -> tuple[str, str | None]:
    """>130% of target -> condense rewrite; <70% -> expand rewrite; both are a
    single extra LLM call using the current scene as input (original spec)."""
    if target <= 0:
        return text, None
    wc = _word_count(text)
    pct = wc / target

    if pct > _CONDENSE_ABOVE:
        guidance = (
            f"This scene is too long (about {wc} words; target {target}). Rewrite it "
            "condensed to only the essential beats -- cut description and redundant "
            "dialogue -- while keeping the scene's key events and its ending state."
        )
        rewritten = llm.complete_text(
            "s0b_revise.md",
            {**base_ctx, "scene_text": text, "guidance": guidance},
            role="script",
            stage_hint=f"stage0_scene{scene_number}_condense",
        )
        return rewritten, "condensed"

    if pct < _EXPAND_BELOW:
        guidance = (
            f"This scene is too short (about {wc} words; target {target}). Rewrite it "
            "expanded with more character interiority and sensory detail, keeping the "
            "same events and the same ending state."
        )
        rewritten = llm.complete_text(
            "s0b_revise.md",
            {**base_ctx, "scene_text": text, "guidance": guidance},
            role="script",
            stage_hint=f"stage0_scene{scene_number}_expand",
        )
        return rewritten, "expanded"

    return text, None


def _structure_completeness(
    integration: IntegrationReport,
    scenes: list[SceneProse],
    total_characters: int,
    total_locations: int,
) -> float:
    """Composite 0-1 proof metric for the ``stage0`` gate. Equal-weighted mean
    of: character-name coverage, location-name coverage, scene-size compliance,
    closeness of total word count to target, and per-scene automated-check
    pass rate. Not specified verbatim in the original spec (which only lists
    the individual Pass 3 validations) -- this is the M1 scoring formula that
    turns those validations into the single mandatory ``structure_completeness``
    metric the stage gate (`scores.py`) requires."""
    name_score = 1.0 if total_characters == 0 else max(
        0.0, 1 - len(integration.missing_character_names) / total_characters
    )
    loc_score = 1.0 if total_locations == 0 else max(
        0.0, 1 - len(integration.missing_location_names) / total_locations
    )
    size_score = 1.0 if not scenes else 1 - len(integration.oversized_scenes) / len(scenes)
    word_pct_score = max(0.0, 1 - min(abs(1 - integration.word_count_pct), 1.0))
    checks_score = (
        1.0 if not scenes else sum(1 for s in scenes if s.checks.all_passed) / len(scenes)
    )
    return round((name_score + loc_score + size_score + word_pct_score + checks_score) / 5, 4)


def _script_quality_scores(
    scorer: Any,
    story_bp: StoryBlueprint,
    scene_records: list[SceneProse],
    scores: Scores,
) -> dict[str, float]:
    """Best-effort AGI script-quality scoring (Pass 3, no LLM).

    Uses the vendored AGI relationship scorer to add three non-mandatory
    metrics on top of ``structure_completeness``:

    - ``agi_fidelity``      (mean over scenes) -- SAME-head: does each scene's
      prose deliver its blueprint beat (narrative_function + emotional_purpose)?
    - ``agi_causal_flow``   (mean over scene pairs) -- CAUSE-head: does scene N
      lead plausibly into scene N+1?
    - ``agi_consistency``   (mean over characters) -- SAME-head: is each
      character written consistently with their blueprint profile?

    Every call is tolerant: if the scorer is unavailable (disabled / checkpoint
    missing / no torch), each metric is skipped and ``None`` is recorded. Never
    raises -- script quality is advisory, not a stage gate.
    """
    if scorer is None or not getattr(scorer, "available", lambda: False)():
        return {}

    beat_by_number = {s.number: s for s in story_bp.scene_list}
    by_number = {r.number: r for r in scene_records}

    # Scene fidelity: prose vs its own blueprint beat.
    fidelities: list[float] = []
    for rec in scene_records:
        beat = beat_by_number.get(rec.number)
        if beat is None:
            continue
        beat_text = (
            f"Scene {rec.number} {beat.title}: "
            f"{beat.narrative_function}; {beat.emotional_purpose}"
        )
        sim = scorer.fidelity(rec.text, beat_text)
        if sim is not None:
            fidelities.append(sim)
        if sim is not None:
            scores.record("stage0", f"scene_{rec.number}", "agi_fidelity", sim)

    # Causal flow between consecutive scenes.
    flows: list[float] = []
    ordered = sorted(scene_records, key=lambda r: r.number)
    for a, b in zip(ordered, ordered[1:]):
        sim = scorer.causal_flow(a.text, b.text)
        if sim is not None:
            flows.append(sim)

    # Character consistency: profile vs the prose they appear in.
    consistencies: list[float] = []
    for char in story_bp.characters:
        profile = (
            f"{char.name} ({char.role}): {char.personality_core}. "
            f"Wants: {char.episode_want}. Fears: {char.episode_fear}."
        )
        matching = [r.text for r in scene_records if char.name in r.text]
        if not matching:
            continue
        sim = scorer.consistency(profile, " ".join(matching))
        if sim is not None:
            consistencies.append(sim)

    metrics: dict[str, float] = {}
    if fidelities:
        metrics["agi_fidelity"] = round(sum(fidelities) / len(fidelities), 4)
    if flows:
        metrics["agi_causal_flow"] = round(sum(flows) / len(flows), 4)
    if consistencies:
        metrics["agi_consistency"] = round(sum(consistencies) / len(consistencies), 4)
    if metrics:
        scores.record_globals("stage0", metrics)
    return metrics


# --------------------------------------------------------------------------
# shared Pass 2 + Pass 3 -- prose generation + integration (used by 0B and 0A)
# --------------------------------------------------------------------------


def generate_from_blueprint(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    story_bp: StoryBlueprint,
    *,
    word_target: int,
    style_exemplars: list[str] | None = None,
    llm: PipelineLLM | None = None,
    scorer: Any | None = None,
) -> dict[str, Any]:
    """Pass 2 (scene-by-scene prose) + Pass 3 (integration) shared by Stage 0B
    (GENERATE) and Stage 0A (TRANSFORM). Given a committed :class:`StoryBlueprint`
    and a word target, writes per-scene prose, integrates ``input/script.txt``,
    records the ``structure_completeness`` metric, and marks ``stage0`` done.

    The blueprint's own ``title_hash`` is re-pinned to the generated script so
    the story-pollution guard protects the finished script downstream (same
    behavior as the original 0B flow).
    """
    project_dir = Path(project_dir)

    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")
    if scorer is None and config.agi.enabled and scorer_enabled(config.agi):
        from .agi_scorer import get_scorer

        scorer = get_scorer(config.agi)

    style_block = (
        "\n\n".join(style_exemplars or [])
        if style_exemplars
        else "(no style exemplars provided; use clear, vivid third-person-limited prose)"
    )

    # ---- Pass 2: Scene-by-scene prose ----------------------------------
    scene_count = len(story_bp.scene_list)
    base_target = word_target / scene_count if scene_count else 0
    act3_numbers = [s.number for s in story_bp.scene_list if s.act == 3]
    climax_number = max(act3_numbers) if act3_numbers else story_bp.scene_list[-1].number

    three_act_summary = _summarize_three_act(story_bp.three_act_structure)
    char_lookup = {c.name.lower(): c for c in story_bp.characters}

    scene_records: list[SceneProse] = []
    for scene in story_bp.scene_list:
        hints = f"{scene.narrative_function} {scene.emotional_purpose} {scene.title}"
        role = _scene_role(scene.number, hints, climax_number)
        mult = {"climax": _CLIMAX_MULT, "transitional": _TRANSITIONAL_MULT}.get(role, 1.0)
        word_t = max(_MIN_SCENE_WORDS, round(base_target * mult))

        plan = ScenePlan(
            number=scene.number,
            title=scene.title,
            act=scene.act,
            location=scene.location,
            characters_present=scene.characters_present,
            emotional_purpose=scene.emotional_purpose,
            narrative_function=scene.narrative_function,
            word_target=word_t,
            scene_role=role,
        )

        base_ctx = {
            "scene_number": plan.number,
            "scene_title": plan.title,
            "act": plan.act,
            "location": plan.location,
            "characters_present": ", ".join(plan.characters_present) or "(none specified)",
            "emotional_purpose": plan.emotional_purpose,
            "narrative_function": plan.narrative_function,
            "three_act_summary": three_act_summary,
            "character_profiles": _character_profiles(plan.characters_present, char_lookup),
            "word_target": plan.word_target,
            "style_exemplars": style_block,
        }

        # Iterative quality loop: draft -> critique -> revise -> score -> repeat.
        current_text = ""
        guidance = ""
        for iteration in range(_MAX_CRITIQUE_ITERATIONS + 1):
            if iteration == 0:
                current_text = llm.complete_text(
                    "s0b_scene_prose.md", base_ctx, role="script",
                    stage_hint=f"stage0_scene{plan.number}_draft",
                )
            else:
                current_text = llm.complete_text(
                    "s0b_revise.md",
                    {**base_ctx, "scene_text": current_text, "guidance": guidance},
                    role="script",
                    stage_hint=f"stage0_scene{plan.number}_revise_iter{iteration}",
                )

            agi_fid = agi_causal = agi_cons = None
            if scorer is not None and getattr(scorer, "available", lambda: False)():
                beat = next((s for s in story_bp.scene_list if s.number == plan.number), None)
                if beat:
                    beat_text = f"Scene {plan.number} {beat.title}: {beat.narrative_function}; {beat.emotional_purpose}"
                    agi_fid = scorer.fidelity(current_text, beat_text)
                    agi_cons = scorer.consistency(
                        f"{plan.characters_present}: {plan.emotional_purpose}",
                        current_text,
                    )
                if scene_records:
                    agi_causal = scorer.causal_flow(scene_records[-1].text, current_text)

            quality_pass = True
            failures = []
            if agi_fid is not None and agi_fid < _MIN_AGI_FIDELITY:
                quality_pass = False
                failures.append(f"agi_fidelity {agi_fid:.3f} < {_MIN_AGI_FIDELITY}")
            if agi_causal is not None and agi_causal < _MIN_AGI_CAUSAL_FLOW:
                quality_pass = False
                failures.append(f"agi_causal_flow {agi_causal:.3f} < {_MIN_AGI_CAUSAL_FLOW}")
            if agi_cons is not None and agi_cons < _MIN_AGI_CONSISTENCY:
                quality_pass = False
                failures.append(f"agi_consistency {agi_cons:.3f} < {_MIN_AGI_CONSISTENCY}")

            if quality_pass or iteration == _MAX_CRITIQUE_ITERATIONS:
                final_text = current_text
                if not quality_pass:
                    logger.warning(
                        "Scene %d quality below threshold after %d iterations: %s -- accepting best attempt",
                        plan.number, _MAX_CRITIQUE_ITERATIONS, "; ".join(failures),
                    )
                break

            guidance = llm.complete_text(
                "s0b_critique.md", {**base_ctx, "scene_text": current_text}, role="script",
                stage_hint=f"stage0_scene{plan.number}_critique_iter{iteration}",
            )

        final_text, enforcement = _enforce_word_count(
            final_text, plan.word_target, base_ctx, llm, plan.number
        )
        checks = _scene_checks(final_text)
        scene_records.append(
            SceneProse(
                number=plan.number,
                title=plan.title,
                text=final_text.strip(),
                word_count=_word_count(final_text),
                word_target=plan.word_target,
                checks=checks,
                enforcement_applied=enforcement,
            )
        )

    (project_dir / "stage0_scenes.json").write_text(
        json.dumps([r.model_dump() for r in scene_records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ---- Pass 3: Integration (no LLM) -----------------------------------
    scene_records.sort(key=lambda r: r.number)
    parts = [f"--- [SCENE {r.number}: {r.title}] ---\n\n{r.text}\n" for r in scene_records]
    full_script = "\n".join(parts).strip() + "\n"

    total_word_count = sum(r.word_count for r in scene_records)
    word_count_pct = (total_word_count / word_target) if word_target else 0.0

    lowered_script = full_script.lower()
    missing_characters = [
        c.name for c in story_bp.characters if c.name.lower() not in lowered_script
    ]
    locations = sorted({s.location for s in story_bp.scene_list})
    missing_locations = [loc for loc in locations if loc.lower() not in lowered_script]
    oversized = [
        r.number for r in scene_records
        if total_word_count > 0 and r.word_count > 0.30 * total_word_count
    ]

    integration = IntegrationReport(
        total_word_count=total_word_count,
        target_word_count=word_target,
        word_count_pct=word_count_pct,
        missing_character_names=missing_characters,
        missing_location_names=missing_locations,
        oversized_scenes=oversized,
    )
    (project_dir / "stage0_integration.json").write_text(
        integration.model_dump_json(indent=2), encoding="utf-8"
    )

    (project_dir / "input").mkdir(parents=True, exist_ok=True)
    (project_dir / "input" / "script.txt").write_text(full_script, encoding="utf-8")

    # Re-pin the story identity to the generated script.
    bp = Blueprint.load(project_dir)
    bp.title_hash = compute_title_hash(full_script)
    bp.stages["stage0"].status = "done"
    bp.stages["stage0"].ts = now_iso()
    bp.write(project_dir)

    structure_completeness = _structure_completeness(
        integration, scene_records, len(story_bp.characters), len(locations)
    )
    scores.record("stage0", "global", "structure_completeness", structure_completeness)
    scores.record("stage0", "global", "total_word_count", float(total_word_count))
    scores.record("stage0", "global", "word_count_pct", float(word_count_pct))
    agi_metrics = _script_quality_scores(scorer, story_bp, scene_records, scores)
    if scorer is not None and getattr(scorer, "available", lambda: False)():
        scorer.close()
    scores.stage_done("stage0")

    return {
        "stage": "stage0",
        "status": "done",
        "structure_completeness": structure_completeness,
        "total_word_count": total_word_count,
        "target_word_count": word_target,
        "script_path": str(project_dir / "input" / "script.txt"),
        "agi": agi_metrics,
    }


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------
def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    brief_path: str | Path | None = None,
    llm: PipelineLLM | None = None,
    scorer: Any | None = None,
) -> dict[str, Any]:
    """Run Stage 0B (GENERATE) for the project at ``project_dir``.

    ``brief_path``, if given, is copied into ``input/brief.md`` (persisted so
    a later call -- e.g. after an ``awaiting_approval`` pause -- does not need
    it repeated). If omitted, an existing ``input/brief.md`` is reused; if
    neither exists, raises :class:`Stage0Error`.

    ``scorer`` (optional) is an AGI script-quality scorer; when not passed, a
    shared instance is pulled from :func:`~pipeline.agi_scorer.get_scorer` when
    AGI scoring is enabled in config. It is advisory only -- unavailable
    scoring degrades to recording no agi_* metrics.
    """
    project_dir = Path(project_dir)
    brief_file = project_dir / "input" / "brief.md"

    if brief_path is not None:
        brief_file.parent.mkdir(parents=True, exist_ok=True)
        brief_file.write_text(Path(brief_path).read_text(encoding="utf-8"), encoding="utf-8")

    if not brief_file.exists():
        raise Stage0Error(
            "stage0 (mode 0B, generate-from-brief) requires a creative brief: pass "
            "--brief <file> (frontmatter: word_target [required], style_exemplars "
            "[optional list])."
        )
    brief = load_brief(brief_file)

    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")
    if scorer is None and config.agi.enabled and scorer_enabled(config.agi):
        from .agi_scorer import get_scorer

        scorer = get_scorer(config.agi)

    # ---- Pass 1: Story Blueprint ---------------------------------------
    blueprint_path = project_dir / "stage0_blueprint.json"
    draft_path = project_dir / "blueprint_draft.json"

    if blueprint_path.exists():
        story_bp = StoryBlueprint.model_validate_json(blueprint_path.read_text(encoding="utf-8"))
    elif draft_path.exists():
        # A prior awaiting_approval run left a draft; a rerun means the human
        # (or automation) has decided to proceed -- promote it as-is (edits
        # made to the file by hand are honored).
        story_bp = StoryBlueprint.model_validate_json(draft_path.read_text(encoding="utf-8"))
        blueprint_path.write_text(story_bp.model_dump_json(indent=2), encoding="utf-8")
    else:
        world_ctx = _world_bible_context(project_dir)
        story_bp = llm.complete_json(
            "s0b_blueprint.md",
            {"brief": brief.text, "world_bible_context": world_ctx},
            StoryBlueprint,
            role="script",
            stage_hint="stage0_blueprint",
        )
        if not config.automation.auto_approve_blueprint:
            draft_path.write_text(story_bp.model_dump_json(indent=2), encoding="utf-8")
            bp = Blueprint.load(project_dir)
            bp.stages["stage0"].status = "awaiting_approval"
            bp.stages["stage0"].ts = now_iso()
            bp.write(project_dir)
            return {
                "stage": "stage0",
                "status": "awaiting_approval",
                "draft_path": str(draft_path),
            }
        blueprint_path.write_text(story_bp.model_dump_json(indent=2), encoding="utf-8")

    if not story_bp.scene_list:
        raise Stage0Error("Pass 1 blueprint has an empty scene_list; cannot continue to Pass 2")

    # Pass 2 (prose) + Pass 3 (integration) -- shared with Stage 0A TRANSFORM.
    return generate_from_blueprint(
        project_dir,
        config,
        scores,
        story_bp,
        word_target=brief.word_target,
        style_exemplars=brief.style_exemplars,
        llm=llm,
        scorer=scorer,
    )
