"""Stage 3 -- STORYBOARD & BLOCKS (design section 4 / Stage 3).

1. Partition shots into blocks <= ``max_block_seconds`` (duration estimated
   from narration+dialogue text at ~150 wpm until Stage 4 writes real audio
   durations back).
2. Generation order per Amir's spec: the ``first`` block, then the ``ending``
   block, then ``infill`` blocks -- start + destination anchor the middle.
3. ``seed_frame`` slots record img2img continuity hooks for Stage 3B (filled
   in as blocks generate).
4. Motion tier + motion prompt per shot (design 3C.2): tier from shot type +
   dialogue presence, capped by the ``[animation]`` motion budget; motion
   prompts via one temp-0.3 LLM call per Tier 1-2 shot.
5. Panel state machine initialized: every shot ``pending``; locked panels are
   never touched by later automation.
6. SFX tagging (v2 improvement #8): conservative keyword map over shot beats.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .blueprint import Blueprint
from .config import ENGINE_ROOT, PipelineConfig
from .llm import PipelineLLM
from .scores import Scores

logger = logging.getLogger(__name__)

PROMPTS_DIR = ENGINE_ROOT / "prompts"

_WPM = 150.0
_MIN_SHOT_SECONDS = 2.5

_SFX_MAP = {
    "door": "door_creak", "blade": "blade_clash", "sword": "blade_clash",
    "explosion": "explosion", "rain": "rain_loop", "footsteps": "footsteps",
    "glass": "glass_break", "thunder": "thunder", "fire": "fire_crackle",
}


def estimate_shot_seconds(shot: dict[str, Any]) -> float:
    """Words at 150 wpm + pause_before_ms, floored at 2.5s per shot."""
    words = 0
    if shot.get("narration"):
        words += len(shot["narration"]["text"].split())
    pause_s = 0.0
    for line in shot.get("dialogue", []):
        words += len(line["text"].split())
        pause_s += line.get("pause_before_ms", 0) / 1000.0
    return max(_MIN_SHOT_SECONDS, words / _WPM * 60.0 + pause_s)


def partition_blocks(
    shots: list[dict[str, Any]], max_block_seconds: float
) -> list[dict[str, Any]]:
    """Greedy partition preserving story order; then order labels: the first
    block is ``first``, the last is ``ending``, the rest ``infill``."""
    blocks: list[dict[str, Any]] = []
    current: list[str] = []
    current_s = 0.0
    for shot in shots:
        dur = estimate_shot_seconds(shot)
        if current and current_s + dur > max_block_seconds:
            blocks.append({"shots": current, "est_seconds": round(current_s, 1)})
            current, current_s = [], 0.0
        current.append(shot["id"])
        current_s += dur
    if current:
        blocks.append({"shots": current, "est_seconds": round(current_s, 1)})

    for i, b in enumerate(blocks):
        b["id"] = f"blk-{i + 1:03d}"
        b["order"] = "first" if i == 0 else ("ending" if i == len(blocks) - 1 else "infill")
        b["seed_frame"] = None
        b["status"] = "pending"
    return blocks


def assign_motion(
    shots: list[dict[str, Any]], config: PipelineConfig,
    blocks: list[dict[str, Any]], llm: PipelineLLM,
) -> dict[str, int]:
    """Motion tiers (design 3C.1): Tier 1 floor, Tier 2 for action shots,
    Tier 3 for lipsync close-ups -- capped by max_animated_seconds_per_block
    (overflow degrades to Tier 0 oscillating drift, the designed degradation
    path). Tier 1-2 shots get a motion prompt."""
    tiers: dict[str, int] = {}
    by_id = {s["id"]: s for s in shots}
    for block in blocks:
        budget = config.animation.max_animated_seconds_per_block
        for sid in block["shots"]:
            shot = by_id[sid]
            if shot.get("lipsync"):
                tier = 3
            elif shot["shot_type"] == "action":
                tier = 2
            else:
                tier = config.animation.default_motion_tier
            dur = estimate_shot_seconds(shot)
            if tier >= 1 and budget - dur < 0:
                tier = 0  # budget exhausted -> clean drift hold
            elif tier >= 1:
                budget -= dur
            tiers[sid] = tier

    for sid, tier in tiers.items():
        shot = by_id[sid]
        shot["motion_tier"] = tier
        if tier in (1, 2):
            shot["motion_prompt"] = llm.complete_text(
                "s3_motion_prompt.md",
                {
                    "composition": shot["composition"], "beat": shot["beat"],
                    "characters": ", ".join(shot["characters_in_frame"]) or "none",
                    "has_dialogue": bool(shot["dialogue"]),
                },
                role="script",
                stage_hint=f"stage3_motion_{sid}",
            ).strip()
        else:
            shot["motion_prompt"] = None
    return tiers


def tag_sfx(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Conservative keyword->sound map over beats (silence beats wrong foley)."""
    sfx = []
    for shot in shots:
        blob = f"{shot['beat']} {shot['movement']}".lower()
        for keyword, sound in _SFX_MAP.items():
            if re.search(rf"\b{keyword}", blob):
                sfx.append({"shot": shot["id"], "sound": sound, "keyword": keyword})
                break
    return sfx


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    llm: PipelineLLM | None = None,
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    screenplay = json.loads(
        (project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8")
    )
    bp = Blueprint.load(project_dir)
    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")

    shots = [shot for scene in screenplay["scenes"] for shot in scene["shots"]]
    max_block_seconds = float(bp.target.max_block_seconds)  # design 3.1

    blocks = partition_blocks(shots, max_block_seconds)
    tiers = assign_motion(shots, config, blocks, llm)
    sfx = tag_sfx(shots)

    est_total = sum(b["est_seconds"] for b in blocks)
    if est_total > 11 * 3600:
        logger.warning("estimated duration %.1fh exceeds the 11-hour ceiling", est_total / 3600)

    storyboard = {
        "story_id": bp.story_id,
        "fps": bp.fps,
        "blocks": blocks,
        "panels": {
            s["id"]: {"status": "pending", "locked_by": None, "issues": []} for s in shots
        },
        "shot_detail": {
            s["id"]: {
                "facial": s["facial"], "posture": s["posture"],
                "movement": s["movement"], "motion_tier": s["motion_tier"],
                "motion_prompt": s["motion_prompt"], "lipsync": s["lipsync"],
            }
            for s in shots
        },
        "sfx": sfx,
        "estimated_duration_s": round(est_total, 1),
    }
    out_dir = project_dir / "storyboard"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "storyboard.json"
    out_path.write_text(json.dumps(storyboard, indent=2, ensure_ascii=False), encoding="utf-8")

    # Screenplay gains motion fields -- persist the enrichment.
    (project_dir / "screenplay" / "screenplay.json").write_text(
        json.dumps(screenplay, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    tier_counts = {t: sum(1 for v in tiers.values() if v == t) for t in (0, 1, 2, 3)}
    scores.record("stage3", "global", "block_count", float(len(blocks)))
    scores.record("stage3", "global", "estimated_duration_s", est_total)
    scores.record("stage3", "global", "sfx_tags", float(len(sfx)))
    for t, n in tier_counts.items():
        scores.record("stage3", "global", f"tier{t}_shots", float(n))
    scores.stage_done("stage3")

    bp.stages["stage3"].status = "done"
    bp.stages["stage3"].ts = _now_iso()
    bp.write(project_dir)

    return {
        "stage": "stage3", "status": "done",
        "blocks": len(blocks), "shots": len(shots),
        "estimated_duration_s": round(est_total, 1),
        "motion_tiers": tier_counts, "sfx_tags": len(sfx),
        "storyboard_path": str(out_path),
    }
