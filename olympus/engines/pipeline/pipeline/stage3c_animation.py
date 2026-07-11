"""Stage 3C -- ANIMATION & LIP SYNC (design section 4 / Stage 3C). Runs AFTER
Stage 4 (real per-shot durations must already be written to screenplay.json).

This Linux install has no LTX motion nodes and no mouth sheets / face detector
yet, so Tier 1-3 motion engines are CONTINGENCY-STOPPED by design. Design
3C.1 names Tier 0 "oscillating drift" as the sanctioned degradation path: a
clean linear translate along one axis, alternating direction shot-to-shot --
never a zoom (a zoom reads as a production choice, not a fallback).

Every shot in the storyboard is therefore degraded to Tier 0:

1. ``motion_tier`` 1-3 -> 0, with the original recorded as ``planned_tier`` so
   the contingency is auditable rather than silently overwriting history.
2. A drift plan is written for every shot: shots alternate ``direction``
   (+1/-1) in story order along ``config.animation.drift_axis``, at 350px
   scaled to the 1216x704 generation frame (350 * height/704).

Because no Tier-3 lipsync shot is ever actually processed here (all shots are
degraded before lipsync would run), the mandatory ``lipsync_overlap_avg``
proof metric is recorded as ``0.0``. That is the honest contingency value,
NOT a passing score -- the design's >=85% target only applies once mouth
sheets and a face detector exist on this box. Recording it (rather than
skipping it) is what lets ``scores.require_stage`` gate Stage 5 correctly
without the ledger lying about coverage.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .blueprint import Blueprint
from .config import PipelineConfig
from .scores import Scores

logger = logging.getLogger(__name__)

# Generation frame (design 3B): 1216x704. Drift distance scales off its
# height, so at the default resolution 350 * (704 / 704) == 350 exactly.
_RESOLUTION = (1216, 704)
_BASE_DRIFT_PX = 350.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shots_in_story_order(screenplay: dict[str, Any]) -> list[str]:
    return [shot["id"] for scene in screenplay["scenes"] for shot in scene["shots"]]


def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    storyboard_path = project_dir / "storyboard" / "storyboard.json"
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    screenplay = json.loads(
        (project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8")
    )
    bp = Blueprint.load(project_dir)

    axis = config.animation.drift_axis
    pixels = round(_BASE_DRIFT_PX * (_RESOLUTION[1] / 704.0), 1)

    shot_detail = storyboard["shot_detail"]
    tier_degraded_shots = 0
    drift_shots = 0
    for i, sid in enumerate(_shots_in_story_order(screenplay)):
        detail = shot_detail[sid]
        orig_tier = detail["motion_tier"]
        if orig_tier in (1, 2, 3):
            tier_degraded_shots += 1
        direction = 1 if i % 2 == 0 else -1
        detail["motion_tier"] = 0
        detail["planned_tier"] = orig_tier
        detail["drift"] = {"axis": axis, "direction": direction, "pixels": pixels}
        drift_shots += 1

    storyboard_path.write_text(
        json.dumps(storyboard, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Contingencies recorded honestly (design 3C.1 / 5.2) -- never silent.
    scores.record("stage3c", "global", "tier_degraded_shots", float(tier_degraded_shots))
    scores.record("stage3c", "global", "ltx_contingency", 1.0)
    scores.record("stage3c", "global", "lipsync_contingency", 1.0)

    # Mandatory proof metric: honest contingency value (0.0), not a passing
    # score. See module docstring -- the >=85% target needs mouth sheets +
    # a face detector, neither of which exists on this box yet.
    scores.record("stage3c", "global", "lipsync_overlap_avg", 0.0)
    scores.record("stage3c", "global", "lipsync_shots_processed", 0.0)
    scores.stage_done("stage3c")

    bp.stages["stage3c"].status = "done"
    bp.stages["stage3c"].ts = _now_iso()
    bp.write(project_dir)

    return {
        "stage": "stage3c", "status": "done",
        "tier_degraded_shots": tier_degraded_shots,
        "drift_shots": drift_shots,
        "lipsync": "contingency_stop (no mouth sheets/face detector on Linux yet)",
    }
