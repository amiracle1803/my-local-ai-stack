"""Lip-sync bridge (design M-AP-6).

Connects stage4 alignment output (viseme timelines) to the
`char_ref_mouth_visemes.json` krea2 inpaint workflow, producing per-shot
mouth flipbook MP4s for Tier-3 lip-sync shots.

Pipeline:
  1. Load alignment JSON (visemes with start/end timestamps)
  2. Map each viseme to mouth_viseme_sheet prompt/mask
  3. Queue char_ref_mouth_visemes.json per viseme segment
  4. Concatenate resulting PNGs into MP4 at dialogue framerate
  5. Return clip path for stage3c Tier-3 integration
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from .comfy_client import ComfyClient, ComfyError
from .config import PipelineConfig

logger = logging.getLogger(__name__)

# 9 Preston Blair viseme classes used by char_ref_mouth_visemes.json
_VISEME_ORDER = ["A", "E", "I", "O", "U", "M", "F", "L", "REST"]

# Viseme prompt templates (patched into mouth_viseme_sheet VISEME_PROMPT)
_VISEME_PROMPTS = {
    "A": "same character, close-up on mouth area only. Mouth shape: wide open, jaw dropped, showing teeth and tongue. Face is exactly the same as the reference image, no changes to eyes, hair, or other features. anime art style, masterpiece, best quality.",
    "E": "same character, close-up on mouth area only. Mouth shape: lips stretched horizontally, teeth slightly visible. Face is exactly the same as the reference image, no changes to eyes, hair, or other features. anime art style, masterpiece, best quality.",
    "I": "same character, close-up on mouth area only. Mouth shape: lips stretched wide, corners back, teeth visible. Face is exactly the same as the reference image, no changes to eyes, hair, or other features. anime art style, masterpiece, best quality.",
    "O": "same character, close-up on mouth area only. Mouth shape: rounded, lips pursed into a small circle. Face is exactly the same as the reference image, no changes to eyes, hair, or other features. anime art style, masterpiece, best quality.",
    "U": "same character, close-up on mouth area only. Mouth shape: small tight circle, lips pushed forward. Face is exactly the same as the reference image, no changes to eyes, hair, or other features. anime art style, masterpiece, best quality.",
    "M": "same character, close-up on mouth area only. Mouth shape: lips closed, pressed together naturally. Face is exactly the same as the reference image, no changes to eyes, hair, or other features. anime art style, masterpiece, best quality.",
    "F": "same character, close-up on mouth area only. Mouth shape: upper teeth touching lower lip, slight gap. Face is exactly the same as the reference image, no changes to eyes, hair, or other features. anime art style, masterpiece, best quality.",
    "L": "same character, close-up on mouth area only. Mouth shape: tongue touching behind upper teeth, lips slightly parted. Face is exactly the same as the reference image, no changes to eyes, hair, or other features. anime art style, masterpiece, best quality.",
    "REST": "same character, close-up on mouth area only. Mouth shape: neutral, relaxed, lips gently closed. Face is exactly the same as the reference image, no changes to eyes, hair, or other features. anime art style, masterpiece, best quality.",
}

# Mask filenames per viseme (stored in ComfyUI/input/masks/viseme_{A,E,I,O,U,M,F,L,REST}.png)
_VISEME_MASK_PREFIX = "viseme_"


def _viseme_for_alignment_viseme(align_viseme: str) -> str:
    """Map alignment viseme (from _ARPABET_TO_VISEME) to mouth_viseme_sheet viseme class."""
    # Alignment uses: A, E, I, O, U, M, F, L, REST
    # mouth_viseme_sheet uses same 9 classes
    if align_viseme in _VISEME_ORDER:
        return align_viseme
    return "REST"


def _seed_for_viseme(character_id: str, viseme: str) -> int:
    """Deterministic seed per character + viseme."""
    import hashlib
    h = hashlib.sha256(f"{character_id}:{viseme}".encode()).hexdigest()[:12]
    return int(h, 16)


def generate_viseme_frames(
    project_dir: Path,
    character_id: str,
    viseme_timeline: list[dict[str, Any]],
    config: PipelineConfig,
    comfy: ComfyClient,
) -> list[tuple[str, float, float]]:
    """Generate PNG for each viseme segment via char_ref_mouth_visemes.json.

    Returns list of (viseme_png_path, start_time, end_time) in timeline order.
    """
    # Load character reference face (from stage1r outputs)
    ref_dir = project_dir / "references" / character_id
    front_ref = ref_dir / "front.png"
    if not front_ref.exists():
        # Fallback: use panel from first shot with this character
        panels_dir = project_dir / "panels"
        for block_dir in panels_dir.iterdir():
            if not block_dir.is_dir():
                continue
            for panel in block_dir.glob("*.png"):
                front_ref = panel
                break
            if front_ref.exists():
                break

    if not front_ref.exists():
        raise FileNotFoundError(f"No face reference found for character {character_id}")

    # Prepare mask directory (ComfyUI/input/masks/ should have viseme_{A,E,I,...}.png)
    # These are pre-generated white-on-black mouth masks
    mask_dir = config.comfyui_dir() / "input" / "masks"

    results = []
    for entry in viseme_timeline:
        viseme = _viseme_for_alignment_viseme(entry["viseme"])
        start = entry["start"]
        end = entry["end"]

        mask_path = mask_dir / f"{_VISEME_MASK_PREFIX}{viseme}.png"
        if not mask_path.exists():
            logger.warning("Viseme mask %s not found, using REST", mask_path)
            mask_path = mask_dir / f"{_VISEME_MASK_PREFIX}REST.png"
            if not mask_path.exists():
                raise FileNotFoundError(f"No viseme masks found in {mask_dir}")

        patches = {
            "FRONT_REF": str(front_ref),
            "MASK_IMAGE": str(mask_path),
            "VISEME_PROMPT": _VISEME_PROMPTS[viseme],
            "SEED": _seed_for_viseme(character_id, viseme),
            "SAVE_PREFIX": f"pipeline/viseme/{character_id}/{viseme}",
        }

        try:
            paths = comfy.generate("char_ref_mouth_visemes.json", patches, dest=project_dir / "viseme" / character_id)
            viseme_png = paths[0]
            results.append((str(viseme_png.relative_to(project_dir)), start, end))
            logger.info("Generated viseme %s for %s (%.3f-%.3fs)", viseme, character_id, start, end)
        except ComfyError as exc:
            logger.error("Failed to generate viseme %s for %s: %s", viseme, character_id, exc)
            # Use REST as fallback
            rest_mask = mask_dir / f"{_VISEME_MASK_PREFIX}REST.png"
            if rest_mask.exists():
                patches["MASK_IMAGE"] = str(rest_mask)
                patches["VISEME_PROMPT"] = _VISEME_PROMPTS["REST"]
                paths = comfy.generate("char_ref_mouth_visemes.json", patches, dest=project_dir / "viseme" / character_id)
                results.append((str(paths[0].relative_to(project_dir)), start, end))

        comfy.free()

    return results


def concatenate_viseme_flipbook(
    project_dir: Path,
    viseme_frames: list[tuple[str, float, float]],
    output_name: str,
    fps: int = 16,
) -> Path:
    """Concatenate viseme PNGs into MP4 at dialogue framerate.

    Each PNG is held for its (end - start) duration, converted to frame count at fps.
    """
    if not viseme_frames:
        raise ValueError("No viseme frames to concatenate")

    clip_dir = project_dir / "clips"
    clip_dir.mkdir(exist_ok=True)
    output_path = clip_dir / output_name

    # Build concat list for ffmpeg
    concat_list = clip_dir / f"{output_name}_concat.txt"
    with concat_list.open("w") as f:
        for png_rel, start, end in viseme_frames:
            png_path = project_dir / png_rel
            duration = max(end - start, 1.0 / fps)  # minimum 1 frame
            # Repeat the image for the duration (ffmpeg -loop 1 -t)
            # We'll use the image directly with -t duration
            f.write(f"file '{png_path.resolve()}'\n")
            f.write(f"duration {duration:.3f}\n")
        # Repeat last frame to ensure ffmpeg includes it
        last_png = project_dir / viseme_frames[-1][0]
        f.write(f"file '{last_png.resolve()}'\n")

    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-vsync", "vfr", "-pix_fmt", "yuv420p",
            "-r", str(fps), "-c:v", "libx264", "-crf", "18",
            str(output_path)
        ], capture_output=True, timeout=120, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.error("ffmpeg concatenation failed: %s", exc)
        raise

    concat_list.unlink(missing_ok=True)
    return output_path


def render_lip_sync_for_shot(
    project_dir: Path,
    shot: dict[str, Any],
    character_id: str,
    config: PipelineConfig,
    comfy: ComfyClient,
) -> Path | None:
    """Render lip-sync flipbook for a single Tier-3 shot.

    Returns path to the lip-sync MP4, or None on failure.
    """
    # Load alignment for this shot's dialogue
    dialogue = shot.get("dialogue", [])
    if not dialogue:
        return None

    # Concatenate all dialogue text for this shot
    transcript = " ".join(line["text"] for line in dialogue if line.get("text"))
    if not transcript:
        return None

    # Find the alignment file (stage4 writes <shot>.align.json alongside WAV)
    align_path = project_dir / "audio" / f"{shot['id']}.align.json"
    if not align_path.exists():
        # Try alternative location
        align_path = project_dir / "dialogue" / f"{shot['id']}.align.json"

    if not align_path.exists():
        logger.warning("Alignment file not found for shot %s: %s", shot['id'], align_path)
        return None

    try:
        align_data = json.loads(align_path.read_text(encoding="utf-8"))
        visemes = align_data.get("visemes", [])
        coverage = align_data.get("coverage", 0.0)

        if not visemes or coverage < 0.5:
            logger.warning("Insufficient alignment coverage for %s: %.2f", shot['id'], coverage)
            return None
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Failed to parse alignment for %s: %s", shot['id'], exc)
        return None

    # Filter visemes to this shot's time range (alignment is per-shot, so should match)
    # The alignment timestamps are relative to the shot's audio start
    viseme_timeline = visemes

    # Generate viseme frames
    try:
        viseme_frames = generate_viseme_frames(
            project_dir, character_id, viseme_timeline, config, comfy
        )
    except (FileNotFoundError, ComfyError) as exc:
        logger.error("Viseme generation failed for %s: %s", shot['id'], exc)
        return None

    if not viseme_frames:
        logger.warning("No viseme frames generated for %s", shot['id'])
        return None

    # Concatenate into flipbook MP4
    output_name = f"{shot['id']}_lipsync.mp4"
    try:
        lipsync_mp4 = concatenate_viseme_flipbook(project_dir, viseme_frames, output_name)
        logger.info("Lip-sync rendered for %s: %s", shot['id'], lipsync_mp4)
        return lipsync_mp4
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.error("Lip-sync concatenation failed for %s: %s", shot['id'], exc)
        return None


def render_lip_sync_for_project(
    project_dir: Path,
    config: PipelineConfig,
    scores: Any,  # Scores type avoided for circular import
    comfy: ComfyClient | None = None,
) -> dict[str, Any]:
    """Main entry point for stage3c Tier-3 lip-sync pass.

    Iterates all Tier-3 shots, renders lip-sync flipbooks, and records results
    in the shot_detail and scorecard. Designed to be called from stage3c_animation
    after LTX renders are done.
    """
    if comfy is None:
        comfy = ComfyClient(config)

    storyboard_path = project_dir / "storyboard" / "storyboard.json"
    screenplay_path = project_dir / "screenplay" / "screenplay.json"

    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    screenplay = json.loads(screenplay_path.read_text(encoding="utf-8"))

    shot_detail = storyboard["shot_detail"]
    shots_by_id = {s["id"]: s for scene in screenplay["scenes"] for s in scene["shots"]}

    lipsync_rendered = 0
    lipsync_failed = 0

    for sid, detail in shot_detail.items():
        if detail.get("motion_tier") != 3:
            continue  # Only Tier-3 (lip-sync) shots

        shot = shots_by_id.get(sid)
        if not shot:
            continue

        # Find character with dialogue in this shot
        dialogue = shot.get("dialogue", [])
        if not dialogue:
            continue

        # Use first character in dialogue (assuming single-speaker per shot for now)
        char_id = dialogue[0].get("char_id")
        if not char_id:
            continue

        logger.info("Rendering lip-sync for %s (character %s)", sid, char_id)

        lipsync_mp4 = render_lip_sync_for_shot(
            project_dir, shot, char_id, config, comfy
        )

        if lipsync_mp4:
            detail["motion_tier"] = 3
            detail["clip_path"] = str(lipsync_mp4.relative_to(project_dir))
            detail["lipsync_rendered"] = True
            lipsync_rendered += 1
        else:
            detail["lipsync_rendered"] = False
            lipsync_failed += 1

    # Update scorecard
    if hasattr(scores, 'record_globals'):
        scores.record_globals("stage3c", {
            "lipsync_shots_processed": float(lipsync_rendered + lipsync_failed),
            "lipsync_contingency": 0.0 if lipsync_rendered > 0 else 1.0,
            "lipsync_overlap_avg": 0.0,  # placeholder for future quality metric
        })

    # Write updated storyboard
    storyboard_path.write_text(
        json.dumps(storyboard, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "lipsync_rendered": lipsync_rendered,
        "lipsync_failed": lipsync_failed,
    }