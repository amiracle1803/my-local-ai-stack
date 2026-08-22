"""Stage 1R -- REFERENCES (design section 4 / Stage 1R). [GPU]

Role-scaled reference sets per character (mains 30 frames, minors 10),
4-angle sets per recurring location, 10 style-lock refs, and a 5-second voice
audition per character. Images run through :class:`~pipeline.comfy_client.ComfyClient`.

**Image model note (design 5.3b)**: krea2 is the mandated primary.
``pipeline.image_router.pick_template()`` is called ONCE at the top of
``run()`` and routes to ``image_txt2img_krea2.json`` when krea2's weights are fully
on disk, else the ONLY permitted fallback (flux-2-klein-4b GGUF) via
``image_txt2img_flux_fallback.json`` -- never a banned model. ``model_used_fallback``
in the scorecard reflects which one actually ran. flux has no IPAdapter/LoRA
path, so consistency comes from the world-bible sd_prompt anchors +
per-character fixed seeds (documented deviation until krea2 has an
established LoRA/IPAdapter-equivalent path, M4 scope).

**LoRA training (design Stage 1R 2b -- mandatory gate)**: kohya_ss is not
runnable on this Linux install (Windows venv; known-broken CLI per
WORK_QUEUE). Training is therefore a **contingency stop recorded in the
scorecard** (``lora_training_contingency=1``), and the Stage 3B LoRA gate is
relaxed by the ``[automation] allow_missing_loras`` flag -- an explicit,
logged deviation, not a silent skip.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from . import image_router
from .blueprint import Blueprint
from .comfy_client import ComfyClient, ComfyError, ContingencyStop
from .config import PipelineConfig
from .schemas.worldbible import WorldBible
from .scores import Scores
from ._util import now_iso

logger = logging.getLogger(__name__)

_TURNAROUND_VIEWS = (
    "front view", "three-quarter view from the left", "left side profile view",
    "back three-quarter view from the left", "back view",
    "back three-quarter view from the right", "right side profile view",
    "three-quarter view from the right",
)
_EXPRESSIONS_MINOR = ("joyful expression", "angry expression")
_EXPRESSIONS_MAIN = (
    "joyful expression", "angry expression", "fearful expression",
    "grieving expression", "resolute expression", "smirking expression",
)
_POSES_MAIN = ("standing pose", "dynamic action pose", "seated pose")
_DETAILS_MAIN = (
    "face close-up portrait", "hands detail", "full body from behind",
    "waist-up portrait", "profile portrait",
)
_MAIN_ROLES = {"protagonist", "antagonist"}

_STYLE_REF_SUBJECTS = (
    "a quiet village street at dawn", "a dense forest clearing", "a castle interior hall",
    "a market square with stalls", "a rooftop at night", "a riverside path",
    "a training ground", "a candle-lit study", "a mountain pass", "a harbor at dusk",
)
_STYLE_TAIL = "anime 2d illustration, manga panel style, high quality linework, cel shading"

_REF_RESOLUTION = (512, 768)  # Flux character sheet resolution for 8GB VRAM safety
_PLATE_RESOLUTION = (1024, 576)  # landscape plates; 1216x704 (~1.1M px) OOMs in
# KSampler on the 8GB card's lowvram mode (same class as stage3b's documented
# 1024x576-safe resolution). Refs are LoRA material, not the final video.

_VOICE_STUDIO_URL = "http://127.0.0.1:5050"


def _seed_for(unit: str, variant: int = 0) -> int:
    return int(hashlib.sha256(f"{unit}:{variant}".encode()).hexdigest()[:12], 16)


def _char_frames(char: Any) -> list[tuple[str, int]]:
    """(prompt_suffix, seed_variant) list -- 30 frames for mains, 10 for minors.

    Prefers the character's dossier-derived ``views`` (pose/expression/360
    turnaround extracted at intake and merged into the world bible); falls back
    to the role-based fixed set when the dossier provided none."""
    if getattr(char, "views", None):
        return [
            (v.get("description") or v.get("angle") or "full body", 0)
            for v in char.views
        ]
    role = char.role
    if (role or "").lower() in _MAIN_ROLES:
        frames = [(v, 0) for v in _TURNAROUND_VIEWS] + [(v, 1) for v in _TURNAROUND_VIEWS]
        frames += [(e, 0) for e in _EXPRESSIONS_MAIN]
        frames += [(p, 0) for p in _POSES_MAIN]
        frames += [(d, 0) for d in _DETAILS_MAIN]
        return frames  # 8+8+6+3+5 = 30
    return [(v, 0) for v in _TURNAROUND_VIEWS] + [(e, 0) for e in _EXPRESSIONS_MINOR]  # 10


def _audition_line(char: dict[str, Any] | Any) -> str:
    drive = getattr(getattr(char, "personality", None), "core_drive", "") or "what I believe in"
    return f"My name is {char.name}. I will not turn back from {drive}."


def _location_views(loc: Any) -> list[tuple[str, str]]:
    """(angle_label, description) pairs for a location's 360 coverage.

    Prefers the world bible's ``views`` (angle + self-contained prompt
    fragment, merged from the stage0 dossier); falls back to ``angles`` labels,
    then the fixed 4-angle default. Each returned description is prompt-ready.
    """
    if loc.views:
        return [
            (v.get("angle", ""), v.get("description", ""))
            for v in loc.views
            if v.get("angle") and v.get("description")
        ]
    angles = loc.angles or ["wide_establishing", "medium_shot", "closeup_counter", "over_shoulder"]
    _HUMANIZED = {
        "wide_establishing": "wide establishing view",
        "medium_shot": "medium shot view",
        "closeup_counter": "close detail view",
        "over_shoulder": "over the shoulder view",
        "top_down": "high angle top-down overview",
        "reverse_angle": "opposite side view",
    }
    return [(a, _HUMANIZED.get(a, a.replace("_", " ") + " view")) for a in angles]


def render_auditions(project_dir: Path, wb: WorldBible, voices: dict[str, Any]) -> int:
    """5-second voice audition per character via Voice Studio (design 4.4.1)."""
    done = 0
    for char in wb.characters:
        spec = voices.get(char.id)
        if not spec:
            continue
        ref_dir = project_dir / "worldbible" / "refs" / char.id
        ref_dir.mkdir(parents=True, exist_ok=True)
        try:
            r = requests.post(
                f"{_VOICE_STUDIO_URL}/api/tts",
                json={"text": _audition_line(char), "voice": spec["base"], "speed": spec["speed"]},
                timeout=120,
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("audition failed for %s: %s", char.id, exc)
            continue
        (ref_dir / "voice_audition.wav").write_bytes(r.content)
        spec["audition"] = str(ref_dir / "voice_audition.wav")
        done += 1
    (project_dir / "voices.json").write_text(
        json.dumps(voices, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return done


def _write_aggregate_manifest(project_dir: Path, wb: WorldBible) -> None:
    """Write ``references/references.json`` consumed by stage2/stage3.

    Contract (see ``stage2_screenplay.segment_scenes``/``plan_shots`` and
    ``stage3_storyboard.run``)::

        {"characters": {id: {...}}, "locations": {id: {...}},
         "style": [...paths...]}

    Each character/location ref dir already carries a ``manifest.json``;
    this folds them into one file so the screenplay and storyboard get the
    visual context they previously logged as missing ("references/
    references.json not found - running without visual context").
    """
    refs_root = project_dir / "worldbible" / "refs"

    def _load_manifest(ref_dir: Path) -> dict:
        mf = ref_dir / "manifest.json"
        if mf.exists():
            try:
                return json.loads(mf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("unreadable manifest %s: %s", mf, exc)
        frames = sorted(ref_dir.glob("ref_*.png"))
        return {"frames": [{"frame": i, "file": f.name} for i, f in enumerate(frames)]}

    characters: dict[str, dict] = {}
    for char in wb.characters:
        ref_dir = refs_root / char.id
        if not ref_dir.exists():
            continue
        characters[char.id] = {
            "name": char.name,
            "role": char.role or "",
            "sd_prompt": char.sd_prompt,
            "frames": _load_manifest(ref_dir).get("frames", []),
        }

    locations: dict[str, dict] = {}
    for loc in wb.locations:
        ref_dir = refs_root / loc.id
        if not ref_dir.exists():
            continue
        locations[loc.id] = {
            "name": loc.name,
            "recurring": loc.recurring,
            "sd_prompt": loc.sd_prompt,
            "frames": _load_manifest(ref_dir).get("frames", []),
        }

    style_dir = refs_root / "_style"
    style = sorted(str(p.relative_to(refs_root)) for p in style_dir.glob("*.png")) if style_dir.exists() else []

    references = {"characters": characters, "locations": locations, "style": style}
    out = project_dir / "references"
    out.mkdir(parents=True, exist_ok=True)
    (out / "references.json").write_text(
        json.dumps(references, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(
        "references/references.json written: %d characters, %d locations, %d style refs",
        len(characters), len(locations), len(style),
    )


def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    comfy: ComfyClient | None = None,
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    wb = WorldBible.model_validate_json(
        (project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8")
    )
    voices = json.loads((project_dir / "voices.json").read_text(encoding="utf-8"))
    if comfy is None:
        comfy = ComfyClient(config)
    if not comfy.healthy():
        raise ContingencyStop("ComfyUI is not reachable at its API - start it first.")
    comfy.unload_ollama()  # GPU scheduling rule (design section 1)

    # Route once for the whole stage run (design 5.3b krea2 gate) and record
    # the decision honestly.
    # Use flux-based character sheet template (lighter than krea2 for 8GB VRAM)
    template, model_used = image_router.pick_character_template(config, comfy)
    used_fallback = template == "image_txt2img_flux_fallback.json"
    scores.record("stage1r", "global", "model_used_fallback", 1.0 if used_fallback else 0.0)

    per_char_counts: dict[str, int] = {}
    failed_generations = 0
    for char in wb.characters:
        ref_dir = project_dir / "worldbible" / "refs" / char.id
        ref_dir.mkdir(parents=True, exist_ok=True)
        frames = _char_frames(char)
        manifest = []
        for i, (suffix, variant) in enumerate(frames):
            fname_prefix = f"pipeline/{project_dir.name}/refs/{char.id}/ref_{i:02d}"
            existing = sorted(ref_dir.glob(f"ref_{i:02d}*.png"))
            if existing:  # resume-safe: skip already-rendered frames
                manifest.append({"frame": i, "view": suffix, "file": existing[0].name})
                continue
            prompt = f"{_STYLE_TAIL}, {char.sd_prompt}, {suffix}, plain background"
            try:
                paths = comfy.generate(
                    template,
                    {
                        "PROMPT_POS": prompt,
                        "WIDTH": 512, "HEIGHT": 768,  # Flux character sheet resolution
                        "SEED": _seed_for(char.id, variant) + i,
                        "SAVE_PREFIX": fname_prefix,
                    },
                    dest=ref_dir,
                )
            except ComfyError as exc:
                # One bad frame must not abort the stage (consistency review
                # 2026-07-11 finding 2); ContingencyStop still propagates.
                logger.error("ref frame %s/%d failed: %s", char.id, i, exc)
                failed_generations += 1
                continue
            renamed = ref_dir / f"ref_{i:02d}_{paths[0].name}"
            paths[0].rename(renamed)
            manifest.append({"frame": i, "view": suffix, "file": renamed.name})
            # Aggressive VRAM management: free after EACH frame
            comfy.free()
        (ref_dir / "manifest.json").write_text(
            json.dumps({"character": char.id, "frames": manifest}, indent=2), encoding="utf-8"
        )
        per_char_counts[char.id] = len(frames)
        scores.record("stage1r", char.id, "refs", float(len(frames)))
        # Free after each character (already freed per frame, but belt-and-suspenders)
        comfy.free()

    # Recurring locations: full 360 coverage from the world bible (dossier views).
    loc_count = 0
    for loc in wb.locations:
        if not loc.recurring:
            continue
        loc_dir = project_dir / "worldbible" / "refs" / loc.id
        loc_dir.mkdir(parents=True, exist_ok=True)
        for i, (angle, desc) in enumerate(_location_views(loc)):
            if sorted(loc_dir.glob(f"ref_{i:02d}*.png")):
                continue
            prompt = f"{loc.sd_prompt}, {desc}, {_STYLE_TAIL}, no text, no letters, no subtitles, no captions, no signage"
            try:
                paths = comfy.generate(
                    template,
                    {
                        "PROMPT_POS": prompt,
                        "WIDTH": 512, "HEIGHT": 512,  # Smaller for location refs
                        "SEED": _seed_for(loc.id) + i,
                        "SAVE_PREFIX": f"pipeline/{project_dir.name}/refs/{loc.id}/ref_{i:02d}",
                    },
                    dest=loc_dir,
                )
            except ComfyError as exc:
                logger.error("location ref %s/%d failed: %s", loc.id, i, exc)
                failed_generations += 1
                continue
            paths[0].rename(loc_dir / f"ref_{i:02d}_{paths[0].name}")
            comfy.free()  # Free after each location ref
        loc_count += 1
        comfy.free()  # Free after all locations

    # Style lock: 10 style reference images (LoRA training itself is the
    # recorded contingency below).
    style_dir = project_dir / "worldbible" / "refs" / "_style"
    style_dir.mkdir(parents=True, exist_ok=True)
    for i, subject in enumerate(_STYLE_REF_SUBJECTS):
        if sorted(style_dir.glob(f"style_{i:02d}*.png")):
            continue
        try:
            paths = comfy.generate(
                template,
                {
                    "PROMPT_POS": f"{subject}, {_STYLE_TAIL}",
                    "WIDTH": _PLATE_RESOLUTION[0], "HEIGHT": _PLATE_RESOLUTION[1],
                    "SEED": _seed_for("_style") + i,
                    "SAVE_PREFIX": f"pipeline/{project_dir.name}/refs/_style/style_{i:02d}",
                },
                dest=style_dir,
            )
        except ComfyError as exc:
            logger.error("style ref %d failed: %s", i, exc)
            failed_generations += 1
            continue
        paths[0].rename(style_dir / f"style_{i:02d}_{paths[0].name}")
    comfy.free()

    # Mouth sheets: 9 viseme frames per main character for lipsync (contingency
    # Stage 3C). Requires a face close-up ref (index 25 in the 30-frame set =
    # "face close-up portrait" from _DETAILS_MAIN). Uses the char_ref_mouth_visemes.json
    # ComfyUI workflow with inpainting to produce mouth variants.
    _VISEME_PROMPTS = (
        "closed mouth neutral expression",
        "slightly open mouth",
        "open mouth speaking",
        "wide open mouth",
        "mouth showing teeth",
        "pursed lips",
        "smile with closed mouth",
        "slight frown",
        "tongue visible",
    )
    mouth_sheet_count = 0
    for char in wb.characters:
        if (char.role or "").lower() not in _MAIN_ROLES:
            continue
        ms_dir = project_dir / "worldbible" / "refs" / char.id / "mouth_sheets"
        ms_dir.mkdir(parents=True, exist_ok=True)
        if len(sorted(ms_dir.glob("viseme_*.png"))) >= len(_VISEME_PROMPTS):
            mouth_sheet_count += 1
            continue
        # Use face close-up portrait. The 30-frame main-role set is:
        # turnarounds v0 (0-7) + v1 (8-15) + expressions (16-21) + poses
        # (22-24) + details (25-29); "face close-up portrait" is details[0] at
        # index 25 (NOT 24, which is "seated pose").
        face_ref = None
        for f in sorted((project_dir / "worldbible" / "refs" / char.id).glob("ref_25_*.png")):
            face_ref = f
            break
        if not face_ref:
            logger.warning("no face close-up ref for %s, skipping mouth sheet", char.id)
            continue
        try:
            uploaded = comfy.upload_image(face_ref, name=f"{char.id}_mouth_ref.png")
            paths = comfy.generate(
                "char_ref_mouth_visemes.json",
                {"REF_IMAGE": uploaded},
                dest=ms_dir,
            )
        except ComfyError as exc:
            logger.warning("mouth sheet failed for %s: %s", char.id, exc)
            continue
        # ComfyUI returns one composite image; rename it.
        if paths:
            paths[0].rename(ms_dir / "mouth_sheet.png")
        mouth_sheet_count += 1

    # LoRA training: contingency stop, recorded (see module docstring).
    scores.record("stage1r", "global", "lora_training_contingency", 1.0)

    auditions = render_auditions(project_dir, wb, voices)

    # Aggregate manifest: stage2 (screenplay) and stage3 (storyboard) read
    # ``references/references.json`` for visual context. Each ref dir already
    # carries a per-character/per-location ``manifest.json``; fold them into
    # the single top-level file those stages expect, keyed by id.
    _write_aggregate_manifest(project_dir, wb)

    refs_min = min(per_char_counts.values()) if per_char_counts else 0
    scores.record("stage1r", "global", "refs_per_character", float(refs_min))
    scores.record("stage1r", "global", "style_refs", float(len(_STYLE_REF_SUBJECTS)))
    scores.record("stage1r", "global", "failed_generations", float(failed_generations))
    scores.record("stage1r", "global", "auditions", float(auditions))
    scores.record("stage1r", "global", "mouth_sheets", float(mouth_sheet_count))
    scores.stage_done("stage1r")

    bp = Blueprint.load(project_dir)
    bp.stages["stage1r"].status = "done"
    bp.stages["stage1r"].ts = now_iso()
    bp.write(project_dir)

    return {
        "stage": "stage1r", "status": "done",
        "model": model_used, "refs_per_character": per_char_counts,
        "recurring_locations": loc_count, "auditions": auditions,
        "lora_training": "contingency_stop (kohya unavailable on Linux; deviation recorded)",
    }
