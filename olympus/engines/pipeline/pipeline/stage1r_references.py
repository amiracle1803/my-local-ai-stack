"""Stage 1R -- REFERENCES (design section 4 / Stage 1R). [GPU]

Role-scaled reference sets per character (mains 30 frames, minors 10),
4-angle sets per recurring location, 10 style-lock refs, and a 5-second voice
audition per character. Images run through :class:`~pipeline.comfy_client.ComfyClient`.

**Image model note (design 5.3b)**: krea2 is the mandated primary but has no
weights on disk, so ``resolve_image_model("primary")`` cannot be honored yet.
This stage uses the ONLY permitted fallback (flux1-schnell GGUF) via
``image_flux_fallback.json`` and records ``model_used=fallback`` in the
scorecard -- never a banned model. flux has no IPAdapter/LoRA path, so
consistency comes from the world-bible sd_prompt anchors + per-character
fixed seeds (documented deviation until krea2 passes model_lab).

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

from .blueprint import Blueprint
from .comfy_client import ComfyClient, ComfyError, ContingencyStop
from .config import PipelineConfig
from .schemas.worldbible import WorldBible
from .scores import Scores

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

_REF_RESOLUTION = (832, 1216)  # portrait for character sheets
_PLATE_RESOLUTION = (1216, 704)

_VOICE_STUDIO_URL = "http://127.0.0.1:5050"


def _seed_for(unit: str, variant: int = 0) -> int:
    return int(hashlib.sha256(f"{unit}:{variant}".encode()).hexdigest()[:12], 16)


def _char_frames(role: str) -> list[tuple[str, int]]:
    """(prompt_suffix, seed_variant) list -- 30 frames for mains, 10 for minors."""
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    # Record the model decision honestly (design 5.3b krea2 gate).
    fallback = config.resolve_image_model("fallback")
    scores.record("stage1r", "global", "model_used_fallback", 1.0)
    logger.warning("stage1r: krea2 absent; using permitted fallback %s", fallback)

    per_char_counts: dict[str, int] = {}
    failed_generations = 0
    for char in wb.characters:
        ref_dir = project_dir / "worldbible" / "refs" / char.id
        ref_dir.mkdir(parents=True, exist_ok=True)
        frames = _char_frames(char.role)
        manifest = []
        for i, (suffix, variant) in enumerate(frames):
            fname_prefix = f"pipeline/{project_dir.name}/refs/{char.id}/ref_{i:02d}"
            existing = sorted(ref_dir.glob(f"ref_{i:02d}*.png"))
            if existing:  # resume-safe: skip already-rendered frames
                manifest.append({"frame": i, "view": suffix, "file": existing[0].name})
                continue
            prompt = f"{char.sd_prompt}, {suffix}, plain background, {_STYLE_TAIL}"
            try:
                paths = comfy.generate(
                    "image_flux_fallback.json",
                    {
                        "PROMPT_POS": prompt,
                        "WIDTH": _REF_RESOLUTION[0], "HEIGHT": _REF_RESOLUTION[1],
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
        (ref_dir / "manifest.json").write_text(
            json.dumps({"character": char.id, "frames": manifest}, indent=2), encoding="utf-8"
        )
        per_char_counts[char.id] = len(frames)
        scores.record("stage1r", char.id, "refs", float(len(frames)))

    # Recurring locations: 4 angles each.
    loc_count = 0
    for loc in wb.locations:
        if not loc.get("recurring"):
            continue
        loc_dir = project_dir / "worldbible" / "refs" / loc["id"]
        loc_dir.mkdir(parents=True, exist_ok=True)
        for i, angle in enumerate(("wide establishing view", "opposite side view",
                                   "interior or close detail view", "high angle overview")):
            if sorted(loc_dir.glob(f"ref_{i:02d}*.png")):
                continue
            prompt = f"{loc['sd_prompt']}, {angle}, {_STYLE_TAIL}"
            try:
                paths = comfy.generate(
                    "image_flux_fallback.json",
                    {
                        "PROMPT_POS": prompt,
                        "WIDTH": _PLATE_RESOLUTION[0], "HEIGHT": _PLATE_RESOLUTION[1],
                        "SEED": _seed_for(loc["id"]) + i,
                        "SAVE_PREFIX": f"pipeline/{project_dir.name}/refs/{loc['id']}/ref_{i:02d}",
                    },
                    dest=loc_dir,
                )
            except ComfyError as exc:
                logger.error("location ref %s/%d failed: %s", loc["id"], i, exc)
                failed_generations += 1
                continue
            paths[0].rename(loc_dir / f"ref_{i:02d}_{paths[0].name}")
        loc_count += 1

    # Style lock: 10 style reference images (LoRA training itself is the
    # recorded contingency below).
    style_dir = project_dir / "worldbible" / "refs" / "_style"
    style_dir.mkdir(parents=True, exist_ok=True)
    for i, subject in enumerate(_STYLE_REF_SUBJECTS):
        if sorted(style_dir.glob(f"style_{i:02d}*.png")):
            continue
        try:
            paths = comfy.generate(
                "image_flux_fallback.json",
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

    # LoRA training: contingency stop, recorded (see module docstring).
    scores.record("stage1r", "global", "lora_training_contingency", 1.0)

    auditions = render_auditions(project_dir, wb, voices)

    refs_min = min(per_char_counts.values()) if per_char_counts else 0
    scores.record("stage1r", "global", "refs_per_character", float(refs_min))
    scores.record("stage1r", "global", "style_refs", float(len(_STYLE_REF_SUBJECTS)))
    scores.record("stage1r", "global", "failed_generations", float(failed_generations))
    scores.record("stage1r", "global", "auditions", float(auditions))
    scores.stage_done("stage1r")

    bp = Blueprint.load(project_dir)
    bp.stages["stage1r"].status = "done"
    bp.stages["stage1r"].ts = _now_iso()
    bp.write(project_dir)

    return {
        "stage": "stage1r", "status": "done",
        "model": fallback, "refs_per_character": per_char_counts,
        "recurring_locations": loc_count, "auditions": auditions,
        "lora_training": "contingency_stop (kohya unavailable on Linux; deviation recorded)",
    }
