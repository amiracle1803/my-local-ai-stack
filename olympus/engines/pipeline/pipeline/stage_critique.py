"""Stage Critique Loop (Task 5) — Self-critique between each pipeline stage.

Compares original script/brief against stage artifacts using an LLM call,
returns structured findings, and optionally triggers retry/regeneration.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .llm import PipelineLLM
from .config import PipelineConfig

logger = logging.getLogger(__name__)

# Maximum chars per artifact when sending to critique LLM
_MAX_ARTIFACT_CHARS = 4000
_MAX_SCRIPT_CHARS = 3000


class CritiqueIssue(BaseModel):
    type: str = Field(..., pattern="^(character|plot|setting|tone|technical)$")
    description: str
    severity: str = Field(..., pattern="^(critical|major|minor)$")
    artifact_ref: str


class CritiqueSuggestion(BaseModel):
    stage: str
    action: str = Field(..., pattern="^(regenerate|repair|tweak_prompt|manual_review)$")
    details: str


class StageCritiqueResult(BaseModel):
    stage_name: str
    consistency_score: float = Field(ge=0.0, le=1.0)
    critical_issues: list[CritiqueIssue] = []
    warnings: list[CritiqueIssue] = []
    suggested_fixes: list[CritiqueSuggestion] = []
    passes: bool
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CritiqueContext:
    original_script: str
    stage_name: str
    stage_purpose: str
    artifacts: dict[str, Any]
    previous_critiques: list[StageCritiqueResult]


STAGE_PURPOSES = {
    "stage0": "Break script into scenes/shots; create initial blueprint with scenes array",
    "stage1": "M2a: Character scan + profiles (appearance, personality, voice, role)",
    "stage1_world": "M2b: World enrichment (locations, era, magic, economy, relationships, contradictions)",
    "stage1r": "Reference images: character sheets, location plates, asset style refs",
    "stage3": "Storyboard: shots+blocks using refs as context, detail per scene",
    "stage2": "Screenplay: narration+dialogue using storyboard+refs as context",
    "stage3b": "Panels: krea2 img2img from plates using refs (identity/style locking)",
    "stage4": "Audio: TTS narration + dialogue alignment + duration per shot",
    "stage3c": "Animation: krea2 base LTX I2V from panels (tiered routing: 2B/2.3 tiled)",
    "stage_vlm_review": "VLM review: audio+visual quality gate, flags drift/repeats",
    "stage5": "Assembly: final MP4 with chapters+SRT+timeline, av_sync check",
}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + " ...[truncated]"


def _collect_artifacts(project_dir: Path, stage_name: str) -> dict[str, Any]:
    """Gather key artifacts produced by a stage for critique."""
    artifacts = {}

    # Common artifact paths by stage
    stage_paths = {
        "stage0": ["stage0_scenes.json", "stage0_integration.json"],
        "stage1": ["voices.json"],
        "stage1_world": ["worldbible/contradictions.json", "voices.json"],
        "stage1r": ["character_sheet.json", "mouth_sheet.json", "location_refs.json", "style_refs.json"],
        "stage3": ["storyboard/storyboard.json"],
        "stage2": ["screenplay/screenplay.json"],
        "stage3b": ["panels/"],
        "stage4": ["audio/"],
        "stage3c": ["clips/"],
        "stage_vlm_review": ["vlm_review.json"],
        "stage5": ["video/final.mp4", "timeline.json", "video/final.srt"],
    }

    paths = stage_paths.get(stage_name, [])
    for p in paths:
        full = project_dir / p
        if full.exists():
            if full.is_dir():
                # List directory contents
                artifacts[f"dir:{p}"] = [f.name for f in full.iterdir() if not f.name.startswith(".")]
            else:
                try:
                    content = full.read_text(encoding="utf-8")
                    artifacts[p] = _truncate(content, _MAX_ARTIFACT_CHARS)
                except UnicodeDecodeError:
                    artifacts[p] = f"[binary file, {full.stat().st_size} bytes]"

    return artifacts


def _load_previous_critiques(project_dir: Path) -> list[StageCritiqueResult]:
    """Load all previous critique results from the project logs."""
    critiques = []
    log_dir = project_dir / "logs"
    if not log_dir.exists():
        return critiques
    for f in sorted(log_dir.glob("critique_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            critiques.append(StageCritiqueResult.model_validate(data))
        except Exception as e:
            logger.warning("Failed to load critique %s: %s", f, e)
    return critiques


def _save_critique(project_dir: Path, result: StageCritiqueResult) -> Path:
    """Save critique result to project logs."""
    log_dir = project_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = log_dir / f"critique_{result.stage_name}_{ts}.json"
    path.write_text(json.dumps(result.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def run_stage_critique(
    project_dir: Path,
    stage_name: str,
    llm: PipelineLLM,
    config: PipelineConfig,
) -> StageCritiqueResult:
    """Run the self-critique for a completed stage.

    Args:
        project_dir: Project root (contains input/script.txt, blueprint.json, artifacts)
        stage_name: Name of the stage just completed (e.g., "stage1", "stage3b")
        llm: Shared PipelineLLM instance
        config: PipelineConfig

    Returns:
        StageCritiqueResult with score, issues, suggestions, and pass/fail.
    """
    # Load original script
    script_path = project_dir / "input" / "script.txt"
    if not script_path.exists():
        raise FileNotFoundError(f"Original script not found: {script_path}")
    original_script = _truncate(script_path.read_text(encoding="utf-8"), _MAX_SCRIPT_CHARS)

    # Gather stage artifacts
    artifacts = _collect_artifacts(project_dir, stage_name)

    # Load previous critiques for context
    previous = _load_previous_critiques(project_dir)

    # Build context for critique prompt
    purpose = STAGE_PURPOSES.get(stage_name, "Unknown stage")
    context = {
        "original_script": original_script,
        "stage_name": stage_name,
        "stage_purpose": purpose,
        "stage_artifacts": json.dumps(artifacts, indent=2, ensure_ascii=False),
        "previous_critiques": json.dumps(
            [{"stage": c.stage_name, "score": c.consistency_score, "issues": len(c.critical_issues), "passes": c.passes} for c in previous],
            indent=2,
        ),
    }

    # Run critique LLM call
    try:
        result = llm.complete_json(
            prompt_file="stage_critique.md",
            context=context,
            schema=StageCritiqueResult,
            role="script",
            stage_hint=f"critique_{stage_name}",
        )
        result.stage_name = stage_name  # ensure stage_name is set
    except Exception as e:
        logger.error("Critique LLM call failed for %s: %s", stage_name, e)
        # Return a failed critique on transport error
        result = StageCritiqueResult(
            stage_name=stage_name,
            consistency_score=0.0,
            critical_issues=[CritiqueIssue(
                type="technical",
                description=f"Critique LLM call failed: {e}",
                severity="critical",
                artifact_ref="llm_transport",
            )],
            passes=False,
        )

    # Save critique
    saved_path = _save_critique(project_dir, result)
    logger.info("Stage critique for %s: score=%.2f passes=%s (saved to %s)",
                stage_name, result.consistency_score, result.passes, saved_path)

    return result


def should_retry_stage(result: StageCritiqueResult, config: PipelineConfig) -> bool:
    """Determine if a stage should be retried based on critique result.

    By default: retry if score < 0.6 (critical failures) OR any critical issues.
    This is conservative; can be tuned via config.automation.critique_retry_threshold.
    """
    threshold = getattr(config.automation, "critique_retry_threshold", 0.6)
    if result.consistency_score < threshold:
        return True
    if any(i.severity == "critical" for i in result.critical_issues):
        return True
    return False


def get_retry_actions(result: StageCritiqueResult) -> list[str]:
    """Extract actionable retry commands from critique suggestions."""
    actions = []
    for fix in result.suggested_fixes:
        if fix.action == "regenerate":
            actions.append(f"rerun {fix.stage}")
        elif fix.action == "repair":
            actions.append(f"repair {fix.stage}: {fix.details}")
        elif fix.action == "tweak_prompt":
            actions.append(f"tweak prompt for {fix.stage}: {fix.details}")
    return actions