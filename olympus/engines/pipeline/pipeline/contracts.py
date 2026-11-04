"""Run preflight and stage artifact validation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from .blueprint import STAGE_ORDER, Blueprint
from .optimizer import HardwareOptimizer, PreflightDecision, free_vram_gb


class ArtifactCheck(BaseModel):
    required: list[str] = Field(default_factory=list)
    present: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    valid: bool = True
    reason: str = ""


class StageContract(BaseModel):
    stage: str
    preflight: PreflightDecision
    artifacts: ArtifactCheck


def required_paths(project_dir: Path, stage: str) -> list[Path]:
    mapping = {
        "stage0": [project_dir / "input" / "script.txt", project_dir / "stage0_scenes.json"],
        "stage0_dossier": [project_dir / "stage0_scenes.json", project_dir / "intake" / "dossier.json"],
        "stage1": [project_dir / "intake" / "dossier.json", project_dir / "worldbible" / "world_bible.json"],
        "stage1_world": [project_dir / "worldbible" / "world_bible.json"],
        "stage3": [project_dir / "worldbible" / "world_bible.json", project_dir / "stage0_scenes.json",
                   project_dir / "storyboard" / "storyboard.json"],
        "stage2": [project_dir / "stage0_scenes.json", project_dir / "storyboard" / "storyboard.json",
                   project_dir / "screenplay" / "screenplay.json"],
        "stage4": [project_dir / "screenplay" / "screenplay.json", project_dir / "audio" / "timeline.json"],
        "stage1r": [project_dir / "worldbible" / "refs" / "_manifest.json"],
        "stage3b": [project_dir / "panels"],
        "stage3c": [project_dir / "panels"],
        "stage_vlm_review": [project_dir / "reviews" / "vlm_review.json"],
        "stage5": [project_dir / "video" / "final.mp4", project_dir / "video" / "final.srt"],
    }
    return mapping.get(stage, [])


def _json_ok(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except (OSError, ValueError):
        return False


def validate_stage_outputs(project_dir: Path, stage: str) -> ArtifactCheck:
    required = required_paths(project_dir, stage)
    missing = [str(p.relative_to(project_dir)) for p in required if not p.exists()]
    present = [str(p.relative_to(project_dir)) for p in required if p.exists()]
    valid = not missing
    reason = ""
    for path in required:
        if path.suffix == ".json" and path.exists() and not _json_ok(path):
            valid = False
            reason = f"invalid JSON: {path.name}"
    if missing and not reason:
        reason = "required artifact missing"
    return ArtifactCheck(required=[str(p.relative_to(project_dir)) for p in required],
                         present=present, missing=missing, valid=valid, reason=reason)


def preflight(project_dir: Path, stage: str, optimizer: HardwareOptimizer) -> StageContract:
    if stage not in STAGE_ORDER:
        raise ValueError(f"unknown stage: {stage}")
    decision = optimizer.decide(stage, project_dir, available_vram_gb=free_vram_gb())
    # When OLYMPUS_REAL_COMFY is not set, the comfyui-profiled stages never
    # touch the GPU (PIL placeholders + ffmpeg fallbacks), so VRAM/smoke gates
    # don't apply. The profile decision only matters for real GPU rendering.
    if (stage in {"stage1r", "stage3b", "stage3c"}
            and not decision.accepted
            and os.environ.get("OLYMPUS_REAL_COMFY", "0") != "1"):
        decision.accepted = True
        decision.reason = "deterministic local fallback selected; GPU gates bypassed"
    if (stage in {"stage1r", "stage3b", "stage3c"}
            and not decision.accepted
            and os.environ.get("OLYMPUS_ALLOW_LOCAL_REAL_COMFY", "0") == "1"):
        decision.accepted = True
        decision.reason = "local low-VRAM ComfyUI override selected"
    # A disabled animation profile is an explicit panels-mode decision, not an
    # accidental failure. Other disabled GPU profiles remain hard failures.
    if stage == "stage3c" and not decision.accepted and decision.reason == "profile disabled":
        decision.accepted = True
        decision.reason = "animation disabled; panels mode explicitly selected"
    # Output validation happens after the stage has run. Preflight only checks
    # hardware/profile policy; predecessor gating remains owned by Scores.
    return StageContract(stage=stage, preflight=decision, artifacts=ArtifactCheck())


def validate_media(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                                capture_output=True, text=True, timeout=30)
        return result.returncode == 0 and float(result.stdout.strip()) > 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
