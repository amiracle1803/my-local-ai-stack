"""Stage VLM_REVIEW -- Visual LLM quality gate for generated video clips.

Extracts keyframes from each clip, sends them to Ollama llava, produces
a structured quality report with PASS/REVIEW/REJECT verdicts.
"""
from __future__ import annotations

import base64
import io
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import requests

from ._util import now_iso, read_json, write_json, load_screenplay, _shots_by_id
from .blueprint import Blueprint
from .config import NimConfig, PipelineConfig
from .nim_client import NIMClient
from .scores import Scores

logger = logging.getLogger(__name__)

_OLLAMA_ENDPOINT = "http://127.0.0.1:11434/api/chat"
_DEFAULT_TIMEOUT = 240  # long timeout absorbs warm-up page-in on the 8GB card

_SCORE_RE = [
    re.compile(r"visual quality.*?[:\-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"motion smoothness.*?[:\-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"color.*?consistency.*?[:\-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"character.*?consistency.*?[:\-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"cinematic composition.*?[:\-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"physics.*?plausibility.*?[:\-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"limb.*?continuity.*?[:\-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"object.*?permanence.*?[:\-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"motion.*?logic.*?[:\-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"narrative.*?continuity.*?[:\-]?\s*(\d+(?:\.\d+)?)", re.I),
]
_SCORE_NAMES = [
    "visual_quality", "motion_smoothness", "color_consistency",
    "character_consistency", "cinematic_composition",
    "physics_plausibility", "limb_continuity", "object_permanence",
    "motion_logic", "narrative_continuity",
]

# Review prompt: 10 scored dimensions + a single PASS/REVIEW/REJECT verdict.
# Dimensions 1-5 are visual quality; 6-10 are the logic/physics/continuity
# layer (option 3) -- does motion obey physics, do limbs stay attached across
# frames, do objects persist, does the motion match the scripted motion_prompt,
# does the shot follow the story/scene logic.
_REVIEW_PROMPT_TEMPLATE = (
    "Review these {n} keyframes from an anime video clip.\n\n"
    "Shot: {shot_description}\n"
    "Motion tier: {motion_tier}\n"
    "Scripted motion intent: {motion_intent}\n\n"
    "Score each dimension 1-10 (10 = perfect, 5 = borderline, 1 = broken):\n"
    "1. Visual quality\n"
    "2. Motion smoothness (no stutter/jitter; temporal coherence of the motion)\n"
    "3. Color consistency (palette holds across the {n} frames)\n"
    "4. Character consistency (same design across frames - face, hair, outfit)\n"
    "5. Cinematic composition\n"
    "6. Physics plausibility (no objects passing through each other, no gravity violations, no impossible deformation)\n"
    "7. Limb continuity (hands/arms/legs stay attached and anatomically valid across frames)\n"
    "8. Object permanence (items present in frame stay present unless scripted to leave)\n"
    "9. Motion logic (the on-screen motion matches the scripted intent and is physically sensible)\n"
    "10. Narrative continuity (the shot follows the scene's story/beat logically)\n\n"
    "Output one line per dimension as 'N. <name> <score>' then a final line:\n"
    "Verdict: PASS / REVIEW / REJECT\n"
    "REJECT if any of physics_plausibility/limb_continuity/motion_logic is <=4 "
    "(a single broken limb or impossible motion fails the clip).\n\n"
    "IMPORTANT: answer immediately with the numbered list. Do NOT produce any "
    "thinking, chain-of-reasoning, or prose before the list -- put scores only."
)
_SYSTEM_PROMPT = (
    "You are an expert anime video quality reviewer and physics/logic auditor. "
    "Score every dimension 1-10 honestly. You are specifically watching for "
    "physics violations (objects passing through each other, motion that "
    "ignores gravity or momentum), limb discontinuities (extra/missing/attached-"
    "wrong limbs across frames), and motion that contradicts the scripted intent. "
    "Provide a PASS / REVIEW / REJECT verdict."
)


def _extract_keyframes(clip_path: Path, count: int = 5) -> list[Path]:
    """Extract count uniform keyframes. WEBP via PIL, MP4 via ffmpeg."""
    tmpdir = Path(tempfile.mkdtemp(prefix="vlm_"))
    stem = clip_path.stem

    if clip_path.suffix.lower() == ".webp":
        try:
            from PIL import Image
            img = Image.open(clip_path)
            frames_all = []
            try:
                while True:
                    frames_all.append(img.copy().convert("RGB"))
                    img.seek(img.tell() + 1)
            except EOFError:
                pass
            if not frames_all:
                return []
            step = len(frames_all) / count
            paths = []
            for i in range(min(count, len(frames_all))):
                f = frames_all[int(i * step)]
                p = tmpdir / f"{stem}_{i:03d}.jpg"
                f.save(p, "JPEG", quality=90)
                paths.append(p)
            return paths
        except ImportError:
            return []

    cmd = ["ffmpeg", "-y", "-i", str(clip_path),
           "-vf", f"select='not(mod(n,{max(1, count - 1)}))',scale=480:-1",
           "-vsync", "vfr", "-q:v", "2", str(tmpdir / f"{stem}_%03d.jpg")]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
    except subprocess.CalledProcessError:
        return []

    frames = sorted(tmpdir.glob(f"{stem}_*.jpg"))
    if len(frames) > count:
        step = len(frames) / count
        frames = [frames[int(i * step)] for i in range(count)]
    return frames[:count]


def _image_to_base64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _call_ollama(prompt: str, images: list[str], model: str = "qwen3:8b",
                 system: str = "", temperature: float = 0.3, timeout: int = _DEFAULT_TIMEOUT,
                 nim_cfg: NimConfig | None = None) -> str:
    # Primary judge: NVIDIA NIM (local Ollama on standby as fallback).
    if nim_cfg is not None:
        nim = NIMClient(nim_cfg)
        if nim.available():
            img_bytes = [
                base64.b64decode(b64) if isinstance(b64, str) else b64
                for b64 in images
            ]
            raw = nim.judge_vision(
                prompt, img_bytes,
                system=system or _SYSTEM_PROMPT,
                temperature=temperature, max_tokens=4096,
            )
            if raw:
                return raw

    payload = {"model": model, "messages": [{"role": "user", "content": prompt, "images": images}],
               "stream": False, "options": {"temperature": temperature, "num_predict": 2048},
               "keep_alive": 0}
    # One transport retry: on the 8GB card the first load after an Ollama
    # idle window can exceed the timeout while the model pages in. A single
    # retry (with the model now warm) recovers the bulk of transport-only
    # failures without masking real model errors (which fail twice).
    for attempt in (1, 2):
        try:
            resp = requests.post(_OLLAMA_ENDPOINT, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
        except requests.RequestException as exc:
            logger.error("Ollama vision call failed (attempt %d/2): %s", attempt, exc)
            if attempt == 2:
                return ""
    return ""


def _parse_scores(text: str) -> dict[str, Any]:
    scores = {}
    for i, pattern in enumerate(_SCORE_RE):
        if i < len(_SCORE_NAMES):
            m = pattern.search(text)
            scores[_SCORE_NAMES[i]] = float(m.group(1)) if m else None

    if re.search(r"\bREJECT\b|\bFAIL\b", text, re.I):
        verdict = "REJECT"
    elif re.search(r"\bPASS\b", text, re.I):
        verdict = "PASS"
    else:
        verdict = "REVIEW"

    valid = [v for v in scores.values() if v is not None]
    overall = round(sum(valid) / len(valid), 2) if valid else 0.0
    return {"overall_score": overall, "verdict": verdict, "details": scores, "raw_response": text[:2000]}


def review_clip(clip_path: Path, shot: dict[str, Any], config: dict[str, Any], audio_path: Any = None,
                nim_cfg: NimConfig | None = None) -> dict[str, Any]:
    if not clip_path.exists():
        return {"error": f"clip not found: {clip_path}", "verdict": "REJECT", "overall_score": 0.0}

    kf_count = config.get("keyframes", {}).get("count", 3)
    frames = _extract_keyframes(clip_path, count=kf_count)
    if not frames:
        return {"error": "no keyframes extracted", "verdict": "REJECT", "overall_score": 0.0}

    tier = shot.get("motion_tier", 0)
    template = config.get("review_prompt_template", _REVIEW_PROMPT_TEMPLATE)
    # Motion intent: the scripted motion_prompt (stage2/3). Empty if absent.
    motion_intent = (
        shot.get("motion_prompt")
        or shot.get("movement")
        or "no scripted motion intent (static shot)"
    )
    try:
        prompt = template.format(
            n=len(frames),
            shot_description=shot.get("sd_prompt", "anime scene"),
            motion_tier=f"Tier {tier}",
            motion_intent=motion_intent,
        )
    except KeyError:
        # Backward-compat: templates that don't use {n}/{motion_intent}.
        prompt = template.format(
            shot_description=shot.get("sd_prompt", "anime scene"),
            motion_tier=f"Tier {tier}",
        )

    # Add audio context to prompt if audio_path provided
    audio_context = ""
    if audio_path:
        if isinstance(audio_path, list):
            audio_types = [a[0] for a in audio_path]
            audio_context = f"\n\nAudio tracks available: {', '.join(audio_types)} (narration + dialogue)"
        else:
            audio_context = f"\n\nAudio track available: {audio_path}"
        prompt += audio_context

    raw = _call_ollama(
        prompt, [_image_to_base64(f) for f in frames],
        model=config.get("model", "qwen2.5vl:7b"),
        system=config.get("system_prompt", _SYSTEM_PROMPT),
        temperature=config.get("temperature", 0.3),
        nim_cfg=nim_cfg,
    )
    if not raw:
        return {"error": "vlm call failed", "verdict": "REJECT", "overall_score": 0.0}

    result = _parse_scores(raw)
    result["shot_id"] = shot.get("id", "unknown")
    result["clip_path"] = str(clip_path)
    result["keyframes_count"] = len(frames)
    result["motion_intent"] = motion_intent
    result["has_audio"] = audio_path is not None

    # Hard reject gate (option 3): any of the physics/logic dimensions <=4
    # is an automatic REJECT regardless of the VLM's stated verdict, because
    # a single impossible motion or broken limb fails the clip definitively.
    hard_dims = ("physics_plausibility", "limb_continuity", "motion_logic")
    hard_min = min(
        (result["details"].get(d) for d in hard_dims
         if result["details"].get(d) is not None),
        default=None,
    )
    if hard_min is not None and hard_min <= 4:
        result["verdict"] = "REJECT"
        result["hard_reject_reason"] = (
            f"physics/logic dimension <=4: {hard_min} "
            f"({[d for d in hard_dims if result['details'].get(d) == hard_min]})"
        )

    for f in frames:
        try:
            f.unlink()
        except OSError:
            pass
    try:
        frames[0].parent.rmdir()
    except OSError:
        pass
    return result


def run(project_dir: str | Path, config: PipelineConfig, scores: Scores, *, vlm_config: dict[str, Any] | None = None) -> dict[str, Any]:
    project_dir = Path(project_dir)
    clips_dir = project_dir / "clips"
    review_dir = project_dir / "reviews"
    review_dir.mkdir(exist_ok=True)

    if not (project_dir / "screenplay" / "screenplay.json").exists():
        return {"status": "skipped", "reason": "no screenplay"}

    screenplay = load_screenplay(project_dir)
    shots_by_id = _shots_by_id(screenplay)

    # Load audio info for audio+visual review
    audio_dir = project_dir / "audio"
    has_audio = audio_dir.exists() and any(audio_dir.glob("*.wav"))

    if vlm_config is None:
        # Reviewer model: dedicated [ollama.models].review (qwen2.5vl:7b) —
        # a non-reasoning VLM that produces reliable structured scores. The
        # reasoning qwen3-vl:8b (vision) returns empty content on some frames
        # because it exhausts its token budget on thinking. Fall back through
        # review -> vision -> qwen2.5vl:7b.
        vision_model = (
            getattr(getattr(config, "models", None), "llm_review", "")
            or getattr(getattr(config, "models", None), "llm_vision", "")
            or "qwen2.5vl:7b"
        )
        vlm_config = {
            "model": vision_model,
            "temperature": 0.3, "pass_threshold": 7.0,
            "review_prompt_template": _REVIEW_PROMPT_TEMPLATE,
            "system_prompt": _SYSTEM_PROMPT,
            "keyframes": {"count": 3},
        }

    clips = sorted(clips_dir.glob("*.webp")) + sorted(clips_dir.glob("*.mp4"))
    # stage5 writes per-shot segments (panel + LTX motion + synced audio) to
    # ``video/segments/sh-*.mp4``; these are the real animation clips that
    # should be reviewed for motion/physics/logic. Prefer segments over the
    # raw stage3c ``clips/`` dir (which may be empty after stage5 ingestion).
    segments_dir = project_dir / "video" / "segments"
    if segments_dir.exists() and any(segments_dir.glob("sh-*.mp4")):
        clips = sorted(segments_dir.glob("sh-*.mp4"))
    reviews, pass_c, reject_c, review_c = {}, 0, 0, 0
    total, reviewed = 0.0, 0
    hard_rejects = 0

    for clip_path in clips:
        sid = clip_path.stem
        shot = shots_by_id.get(sid, {})
        
        # Find corresponding audio file for audio+visual review
        audio_path = None
        if has_audio:
            # Look for narration + dialogue audio for this shot
            narration_audio = audio_dir / f"{sid}_narration.wav"
            dialogue_audio = audio_dir / f"{sid}_dialogue.wav"
            audio_files = []
            if narration_audio.exists():
                audio_files.append(("narration", narration_audio))
            if dialogue_audio.exists():
                audio_files.append(("dialogue", dialogue_audio))
            if audio_files:
                audio_path = audio_files  # Pass list of (type, path) tuples

        logger.info("Reviewing %s (shot %s)...", clip_path.name, sid)
        result = review_clip(clip_path, shot, vlm_config, audio_path=audio_path, nim_cfg=config.nim)
        reviews[sid] = result
        if "error" not in result:
            reviewed += 1
            total += result.get("overall_score", 0.0)
            v = result.get("verdict", "REVIEW")
            pass_c += v == "PASS"
            reject_c += v == "REJECT"
            review_c += v not in ("PASS", "REJECT")
            if result.get("hard_reject_reason"):
                hard_rejects += 1

    avg = round(total / reviewed, 2) if reviewed else 0.0
    report = {
        "timestamp": now_iso(), "model": vlm_config.get("model", "qwen2.5vl:7b"),
        "total_clips": len(clips), "reviewed": reviewed,
        "pass": pass_c, "reject": reject_c, "review": review_c,
        "hard_rejects": hard_rejects,
        "avg_score": avg, "pass_rate": round(pass_c / reviewed, 2) if reviewed else 0.0,
        "reviews": reviews,
    }
    write_json(review_dir / "vlm_review.json", report)

    scores.record_globals("stage_vlm_review", {
        "clips_reviewed": reviewed, "pass_rate": report["pass_rate"],
        "avg_score": avg, "rejects": reject_c, "needs_review": review_c,
        "hard_rejects": hard_rejects,
        "review_coverage": round(reviewed / len(clips), 3) if clips else 0.0,
    })
    scores.stage_done("stage_vlm_review")
    bp = Blueprint.load(project_dir)
    bp.stages["stage_vlm_review"].status = "done"
    bp.write(project_dir)

    return {"stage": "stage_vlm_review", "status": "done", "reviewed": reviewed,
            "pass": pass_c, "reject": reject_c, "avg_score": avg,
            "pass_rate": report["pass_rate"], "hard_rejects": hard_rejects}