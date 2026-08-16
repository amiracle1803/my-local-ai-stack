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
from ._util import now_iso
from .video_metrics import location_diversity

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
    path). Tier 1-2 shots get a motion prompt.

    M-AP-5 (2026-08-09): Adds motion_tier_reason provenance field to each shot
    for audit trail -- why a shot was Tier 1 vs Tier 2 (composition cue? 
    camera_movement field? motion-budget heuristics?).
    """
    tiers: dict[str, int] = {}
    tier_reasons: dict[str, str] = {}
    by_id = {s["id"]: s for s in shots}
    for block in blocks:
        budget = config.animation.max_animated_seconds_per_block
        for sid in block["shots"]:
            shot = by_id[sid]
            reason_parts = []
            if shot.get("lipsync"):
                tier = 3
                reason_parts.append("lip-sync dialogue")
            elif shot["shot_type"] == "action":
                tier = 2
                reason_parts.append("action shot_type")
            else:
                tier = config.animation.default_motion_tier
                reason_parts.append(f"default tier {tier}")
            dur = estimate_shot_seconds(shot)
            if tier >= 1 and budget - dur < 0:
                tier = 0  # budget exhausted -> clean drift hold
                reason_parts.append("motion budget exhausted")
            elif tier >= 1:
                budget -= dur
                reason_parts.append(f"budget remaining {budget:.1f}s")
            tiers[sid] = tier
            tier_reasons[sid] = "; ".join(reason_parts)

    for sid, tier in tiers.items():
        shot = by_id[sid]
        shot["motion_tier"] = tier
        # M-AP-5: Record the reason for this tier assignment
        shot["motion_tier_reason"] = tier_reasons.get(sid, "")
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
            if re.search(rf"\b{keyword}\b", blob):
                sfx.append({"shot": shot["id"], "sound": sound, "keyword": keyword})
                break
    return sfx




def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    llm: PipelineLLM | None = None,
) -> dict[str, Any]:
    """Stage 3 -- STORYBOARD (design section 4 / Stage 3).

    Reads:  worldbible/world_bible.json, references/references.json, input/script.txt
    Writes: storyboard/storyboard.json  (scenes + shots + blocks, NO narration/dialogue yet)

    The scene segmentation, shot planning, and SD-prompt assembly use reference
    images (character refs, location refs, asset style refs) as context so that
    the storyboard reflects the actual visual references. This gives downstream
    stage2 (screenplay) and stage3b (panels) a solid structural + visual skeleton.
    """
    project_dir = Path(project_dir)
    # Imports inside run() to avoid a circular import (stage2 imports tag_sfx
    # from this module).
    from .stage2_screenplay import (
        segment_scenes, plan_shots, assemble_sd_prompt, Stage2Error,
    )
    from .schemas.worldbible import WorldBible
    wb = WorldBible.model_validate_json(
        (project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8")
    )
    # Load references (stage1r output) for visual context
    refs_path = project_dir / "references" / "references.json"
    references = {}
    if refs_path.exists():
        references = json.loads(refs_path.read_text(encoding="utf-8"))
    else:
        logger.warning("references/references.json not found - running without visual context")
    script_text = (project_dir / "input" / "script.txt").read_text(encoding="utf-8")
    bp = Blueprint.load(project_dir)
    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")

    # --- scene segmentation + shot planning (moved from old stage2) ---
    scenes = segment_scenes(script_text, wb, llm, references=references)
    if not scenes:
        raise Stage2Error("scene segmentation produced no scenes")

    for i, scene in enumerate(scenes, 1):
        scene["shots"] = plan_shots(scene, i, len(scenes), wb, llm, references=references)
    total_shots = sum(len(s["shots"]) for s in scenes)
    if not 20 <= total_shots <= 60:
        logger.warning("shot count %d outside the 20-60 band (original spec warns)", total_shots)

    for scene in scenes:
        for shot in scene["shots"]:
            shot["sd_prompt"] = assemble_sd_prompt(shot, scene, wb, references=references)

    shots = [shot for scene in scenes for shot in scene["shots"]]
    max_block_seconds = float(bp.target.max_block_seconds)  # design 3.1

    # --- per-scene block partitioning (first/ending/infill per scene) ---
    blocks: list[dict[str, Any]] = []
    for scene in scenes:
        scene_blocks = partition_blocks(scene["shots"], max_block_seconds)
        for b in scene_blocks:
            b["id"] = f"blk-{len(blocks) + 1:03d}"
            b["scene_id"] = scene["id"]
            blocks.append(b)

    # --- motion tier assignment (still done here so blocks have tiers) ---
    tiers = assign_motion(shots, config, blocks, llm)

    est_total = sum(b["est_seconds"] for b in blocks)
    if est_total > 11 * 3600:
        logger.warning("estimated duration %.1fh exceeds the 11-hour ceiling", est_total / 3600)

    storyboard = {
        "story_id": bp.story_id,
        "fps": bp.fps,
        "scenes": scenes,           # scenes+shots now live in storyboard (structural)
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
        "estimated_duration_s": round(est_total, 1),
    }
    out_dir = project_dir / "storyboard"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "storyboard.json"
    out_path.write_text(json.dumps(storyboard, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write the freshly-assembled sd_prompts back to screenplay.json so
    # stage3b reads the NO_TEXT_TAIL-expanded prompts (krea2 / qwen3vl will
    # otherwise render JP signage when manga is in the prompt).
    screenplay_path = project_dir / "screenplay" / "screenplay.json"
    if screenplay_path.exists():
        sp = json.loads(screenplay_path.read_text(encoding="utf-8"))
        new_prompts = {
            shot["id"]: shot["sd_prompt"]
            for scene in scenes for shot in scene["shots"]
        }
        for sp_scene in sp.get("scenes", []):
            for sp_shot in sp_scene.get("shots", []):
                if sp_shot.get("id") in new_prompts:
                    sp_shot["sd_prompt"] = new_prompts[sp_shot["id"]]
        screenplay_path.write_text(json.dumps(sp, indent=2, ensure_ascii=False), encoding="utf-8")

    tier_counts = {t: sum(1 for v in tiers.values() if v == t) for t in (0, 1, 2, 3)}
    loc_div = location_diversity(scenes)
    if loc_div < 0.5:
        logger.warning(
            "location_diversity %.2f: most scenes share one location - the "
            "'weak world' complaint. Enrich the world bible before ship.",
            loc_div,
        )
    scores.record("stage3", "global", "block_count", float(len(blocks)))
    scores.record("stage3", "global", "estimated_duration_s", est_total)
    scores.record("stage3", "global", "location_diversity", loc_div)
    for t, n in tier_counts.items():
        scores.record("stage3", "global", f"tier{t}_shots", float(n))
    scores.stage_done("stage3")

    bp.stages["stage3"].status = "done"
    bp.stages["stage3"].ts = now_iso()
    bp.write(project_dir)

    return {
        "stage": "stage3", "status": "done",
        "scenes": len(scenes), "blocks": len(blocks), "shots": total_shots,
        "estimated_duration_s": round(est_total, 1),
        "motion_tiers": tier_counts,
        "storyboard_path": str(out_path),
    }
