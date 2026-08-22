"""Stage 0A -- TRANSFORM (source -> original). Original spec
``aether-studio-original-spec-stages0-2.md`` STAGE 0 -> Stage 0A; design
``anime-pipeline-v2-design.md`` 4. Stage 0 THREE MODES, 0A bullet.

Four passes, all through :class:`~pipeline.llm.PipelineLLM`:

- **Pass 1 -- Mechanics Extraction** (temp 0.1, JSON,
  :class:`~pipeline.schemas.stage0.MechanicsExtraction`). Reads the first 4000
  chars of the source and extracts structural mechanics only -- never plot,
  names, or characters.
- **Pass 2 -- Originality Design** (temp 0.5, JSON,
  :class:`~pipeline.schemas.stage0.TransformationMap`). Designs original
  equivalents for every source mechanic, then computes the legal-proximity
  score (:class:`~pipeline.schemas.stage0.LegalScore`). Below 50 blocks Pass 3;
  below 75 is a warning (proceed unless ``auto_approve_transform_map`` is off,
  in which case the run pauses ``awaiting_approval`` until the draft is
  re-run).
- **Pass 3 -- Blueprint** (temp 0.3, JSON, :class:`StoryBlueprint`) from the
  transformation map instead of a free brief.
- **Pass 4 -- Scene Prose** -- delegates to the shared
  :func:`~pipeline.stage0_intake.generate_from_blueprint` (the same
  draft->critique->revise loop and integration as Stage 0B).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .blueprint import Blueprint
from .config import ENGINE_ROOT, PipelineConfig
from .llm import PipelineLLM
from .schemas.stage0 import (
    LegalScore,
    MechanicsExtraction,
    StoryBlueprint,
    TransformationMap,
)
from .scores import Scores
from .stage0_intake import PROMPTS_DIR, generate_from_blueprint
from ._util import now_iso

logger = logging.getLogger(__name__)

_MECHANICS_SAMPLE_CHARS = 4000  # mechanics appear in the setup, not the full story
_TRANSFORM_MAP_DRAFT = "stage0a_transform_draft.json"
_MECHANICS_PATH = "stage0a_mechanics.json"
_TRANSFORM_MAP_PATH = "stage0a_transform_map.json"
_LEGAL_SCORE_PATH = "stage0a_legal_score.json"


class Stage0AError(ValueError):
    """Stage 0A-specific input problems (missing source, empty map, etc.)."""


def extract_mechanics(source_text: str, llm: PipelineLLM) -> MechanicsExtraction:
    """Pass 1 -- structural mechanics from the first 4000 chars of the source."""
    sample = source_text[:_MECHANICS_SAMPLE_CHARS]
    return llm.complete_json(
        "s0a_mechanics.md",
        {"source_text": sample},
        MechanicsExtraction,
        role="script",
        stage_hint="stage0a_mechanics",
    )


def design_originality(
    mech: MechanicsExtraction, llm: PipelineLLM
) -> TransformationMap:
    """Pass 2 -- original equivalents for every source mechanic."""
    return llm.complete_json(
        "s0a_originality.md",
        {"mechanics_json": mech.model_dump_json(indent=2)},
        TransformationMap,
        role="script",
        stage_hint="stage0a_originality",
    )


def compute_legal_score(
    mech: MechanicsExtraction, tmap: TransformationMap
) -> LegalScore:
    """Pass 2 post-check -- deterministic proximity gate. No LLM."""
    score = LegalScore()
    score.recompute(mech, tmap)
    return score


def build_blueprint(
    tmap: TransformationMap, llm: PipelineLLM, world_context: str = ""
) -> StoryBlueprint:
    """Pass 3 -- blueprint committed from the approved transformation map."""
    return llm.complete_json(
        "s0a_blueprint.md",
        {
            "transformation_map_json": tmap.model_dump_json(indent=2),
            "world_context": world_context,
        },
        StoryBlueprint,
        role="script",
        stage_hint="stage0a_blueprint",
    )


def _write_json(project_dir: Path, rel: str, data: Any) -> None:
    (project_dir / rel).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    source_path: str | Path | None = None,
    word_target: int = 900,
    llm: PipelineLLM | None = None,
) -> dict[str, Any]:
    """Run Stage 0A (TRANSFORM) for the project at ``project_dir``.

    ``source_path``, if given, is copied into ``input/source.txt`` (persisted so
    a later call does not need it repeated). If omitted, an existing
    ``input/source.txt`` is reused; if neither exists, raises
    :class:`Stage0AError`.

    ``word_target`` is the total prose word budget for the transformed episode
    (default 900). ``auto_approve_transform_map`` in config controls whether the
    run pauses for human review of the transformation map.
    """
    project_dir = Path(project_dir)
    source_file = project_dir / "input" / "source.txt"

    if source_path is not None:
        (project_dir / "input").mkdir(parents=True, exist_ok=True)
        source_file.write_text(Path(source_path).read_text(encoding="utf-8"), encoding="utf-8")

    if not source_file.exists():
        raise Stage0AError(
            "stage0 (mode 0A, transform-from-source) requires a source text: pass "
            "--source <file>."
        )
    source_text = source_file.read_text(encoding="utf-8")
    if not source_text.strip():
        raise Stage0AError("source text is empty")

    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")

    # ---- Pass 1: Mechanics Extraction -----------------------------------
    mech_path = project_dir / _MECHANICS_PATH
    if mech_path.exists():
        mech = MechanicsExtraction.model_validate_json(mech_path.read_text(encoding="utf-8"))
    else:
        mech = extract_mechanics(source_text, llm)
        _write_json(project_dir, _MECHANICS_PATH, mech.model_dump())

    # ---- Pass 2: Originality Design + legal score -----------------------
    tmap_path = project_dir / _TRANSFORM_MAP_PATH
    draft_path = project_dir / _TRANSFORM_MAP_DRAFT
    if tmap_path.exists():
        tmap = TransformationMap.model_validate_json(tmap_path.read_text(encoding="utf-8"))
    elif draft_path.exists():
        tmap = TransformationMap.model_validate_json(draft_path.read_text(encoding="utf-8"))
        tmap_path.write_text(tmap.model_dump_json(indent=2), encoding="utf-8")
    else:
        tmap = design_originality(mech, llm)
        legal = compute_legal_score(mech, tmap)
        _write_json(project_dir, _LEGAL_SCORE_PATH, legal.model_dump())

        if legal.blocked:
            # Below 50: block Pass 3 -- user must acknowledge + modify first.
            raise Stage0AError(
                f"legal proximity score {legal.total:.0f} < 50: the transformation "
                "is too close to the source. Refine the transformation map "
                f"(edit {_TRANSFORM_MAP_DRAFT}) then re-run."
            )

        if not config.automation.auto_approve_transform_map:
            # Pause for human review of the transformation map.
            _write_json(project_dir, _TRANSFORM_MAP_DRAFT, tmap.model_dump())
            bp = Blueprint.load(project_dir)
            bp.stages["stage0"].status = "awaiting_approval"
            bp.stages["stage0"].ts = now_iso()
            bp.write(project_dir)
            return {
                "stage": "stage0",
                "status": "awaiting_approval",
                "legal_score": legal.total,
                "draft_path": str(draft_path),
            }
        tmap_path.write_text(tmap.model_dump_json(indent=2), encoding="utf-8")

    if not tmap.character_originals:
        raise Stage0AError("transformation map has no character_originals; cannot continue")

    # ---- Pass 3: Blueprint ----------------------------------------------
    blueprint_path = project_dir / "stage0_blueprint.json"
    if blueprint_path.exists():
        story_bp = StoryBlueprint.model_validate_json(blueprint_path.read_text(encoding="utf-8"))
    else:
        world_context = (
            f"{tmap.world_design.name} -- {tmap.world_design.geography} -- "
            f"scarce: {tmap.world_design.what_is_scarce}"
        )
        story_bp = build_blueprint(tmap, llm, world_context=world_context)
        blueprint_path.write_text(story_bp.model_dump_json(indent=2), encoding="utf-8")

    if not story_bp.scene_list:
        raise Stage0AError("Pass 3 blueprint has an empty scene_list")

    # ---- Pass 4: Scene Prose (shared with 0B) ---------------------------
    return generate_from_blueprint(
        project_dir,
        config,
        scores,
        story_bp,
        word_target=word_target,
        llm=llm,
    )
