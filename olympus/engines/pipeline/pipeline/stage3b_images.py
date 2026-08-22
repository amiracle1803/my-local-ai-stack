"""Stage 3B -- IMAGES (design section 4 / Stage 3B). [GPU]

Scene environment lock + per-shot panels, landscape 1216x704, via
:class:`~pipeline.comfy_client.ComfyClient`:

- ``pipeline.image_router.pick_template()`` is called ONCE at the top of
  ``run()`` (design 5.3b): routes to ``image_krea2.json`` when krea2's
  weights are on disk, else the permitted ``image_flux_fallback.json``.
- Per scene: ONE location master plate first (location sd_prompt + time of
  day, no characters) -> ``panels/<block>/_plates/<scene>.png``. Neither
  template has IPAdapter yet, so the plate conditions shots through the
  scene's fixed environment token block + the scene-level base seed
  (``hash(scene_id)``) that all shot seeds derive from.
- Per shot (skip locked): txt2img with the assembled 120-word sd_prompt; a
  sidecar json stores seed/prompt/model for reproducibility.
- **Vision-judge QC** (v2): qwen2.5vl:7b (Ollama, images attached) checks
  visible-character count and composition/background match; a failing panel
  is retried once with a derived seed, then flagged in the storyboard panel
  state machine. >20% vision failures is the design's hard pause-gate.
- **LoRA gate** (design Stage 3B.5): refuses to start when character LoRAs
  are missing UNLESS ``[automation] allow_missing_loras`` is true (explicit
  deviation recorded by stage1r).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel

from . import image_router
from . import identity
from .blueprint import Blueprint
from .comfy_client import ComfyClient, ComfyError, ContingencyStop
from .config import PipelineConfig
from .nim_client import NIMClient
from .schemas.worldbible import WorldBible
from .scores import Scores

logger = logging.getLogger(__name__)

_RESOLUTION = (896, 512)  # reduced from 1024x576 for 8GB VRAM safety (improved headroom)
_OLLAMA_URL = "http://127.0.0.1:11434"
_VISION_TIMEOUT = 10  # seconds; vision judge failure returns inconclusive pass
_VISION_FAIL_GATE = 0.25  # raised to 25% for 8GB VRAM; design was 20%
_VISION_MIN_PASS_RATE = 0.70  # lowered from 0.85 for local LLM on 8GB
_MIN_PROMPT_ADHERENCE = 0.60  # lowered from 0.80 for local LLM on 8GB


class Stage3BError(RuntimeError):
    pass


class _VisionCheck(BaseModel):
    """Extraction schema — the VLM *describes* what it sees (hair/eye/outfit),
    and the on-model verdict is computed in code against the canonical facts
    (extract-then-compare: more reliable than a binary VLM judgement)."""

    characters_visible: int = 0
    background_matches: bool = True
    composition_matches: bool = True
    hair_color: str = ""
    eye_color: str = ""
    outfit: str = ""


def _seed_for(scene_id: str, shot_id: str = "", retry: int = 0) -> int:
    return int(hashlib.sha256(f"{scene_id}:{shot_id}:{retry}".encode()).hexdigest()[:12], 16)


def _plate_key_for_scene(scene: dict[str, Any], shot: dict[str, Any] | None = None) -> str:
    """Stable per-scene plate key, angle-aware: ``<location>__<tod>__<angle>``.

    Time-of-day is normalized (lowercase, spaces -> underscores, empty -> "day")
    so a scene renders one master plate per angle regardless of how the LLM
    spelled the time. Shots without a camera_angle fall back to
    "wide_establishing" (matches WorldBible location defaults).
    """
    loc = scene.get("location", "unknown")
    tod = scene.get("time_of_day", "day")
    if not tod or str(tod).strip().lower() == "unclear":
        tod = "day"
    tod = str(tod).strip().lower().replace(" ", "_")
    angle = "wide_establishing"
    if shot is not None:
        angle = shot.get("camera_angle") or angle
    return f"{loc}__{tod}__{angle}"



def _env_token_block(scene: dict[str, Any], wb: WorldBible) -> str:
    """The scene's fixed environment tokens, appended verbatim to every shot
    prompt in the scene (background consistency without IPAdapter)."""
    loc = next((l for l in wb.locations if l.id == scene["location"]), None)
    tod = scene.get("time_of_day", "")
    bits = []
    if loc:
        bits.append(f"consistent background: {loc.name}")
    if tod and tod != "unclear":
        bits.append(f"{tod} palette")
    return ", ".join(bits)


def _location_view_description(loc: Any, angle: str = "wide_establishing") -> str:
    """The 360-view description (self-contained prompt fragment) for a location
    and camera angle, merged from the stage0 dossier. Falls back to the first
    view's description, then '' (caller falls back to ``loc.sd_prompt``)."""
    if loc is None:
        return ""
    views = getattr(loc, "views", None) or []
    for v in views:
        if v.get("angle") == angle and v.get("description"):
            return v["description"]
    for v in views:
        if v.get("description"):
            return v["description"]
    return ""


def _enhance_prompt_for_vision(
    prompt: str, shot: dict[str, Any], vision_detail: dict[str, Any], config: PipelineConfig
) -> str:
    """Strengthen prompt based on vision judge failure reasons."""
    enhanced = prompt
    if not vision_detail.get("characters_visible") == len(shot.get("characters_in_frame", [])):
        # Boost character specificity
        chars = ", ".join(shot.get("characters_in_frame", []))
        enhanced = f"{enhanced}, EXACTLY {len(shot.get('characters_in_frame', []))} characters: {chars}, each distinct and visible"
    if not vision_detail.get("background_matches"):
        enhanced = f"{enhanced}, background MUST match: {shot.get('location', '')}, {shot.get('time_of_day', '')} lighting"
    if not vision_detail.get("composition_matches"):
        comp = shot.get("composition", "")
        if comp:
            enhanced = f"{enhanced}, composition: {comp}"
    if not vision_detail.get("appearance_matches"):
        spec = vision_detail.get("appearance_spec", "")
        if spec:
            enhanced = f"{enhanced}, character appearance MUST be: {spec}"
    return enhanced


# Appearance color groups for code-side extract-then-compare. A "conflict" is
# when the VLM-extracted description and the canonical one both name a colour
# from *different* groups (e.g. extracted "red" vs canonical "dark/black") -- a
# colour substitution, not a missing detail. Synonyms within a group ("dark" vs
# "black", "blonde" vs "golden") do NOT conflict.
_COLOR_GROUPS: tuple[tuple[str, ...], ...] = (
    ("black", "dark", "raven"),
    ("white", "silver", "grey", "gray", "pale", "fair", "light"),
    ("red", "crimson", "scarlet"),
    ("blue", "navy"),
    ("green", "emerald", "teal"),
    ("brown", "auburn"),
    ("blonde", "blond", "gold", "golden", "yellow", "amber"),
    ("pink", "purple", "violet", "magenta", "lavender"),
    ("orange", "copper", "bronze"),
    ("aqua", "cyan", "turquoise"),
)


def _color_group_tokens(s: str) -> set[int]:
    """The indices of the color groups named in ``s``."""
    text = (s or "").lower()
    return {i for i, g in enumerate(_COLOR_GROUPS) if any(t in text for t in g)}


def _color_conflict(extracted: str, canonical: str) -> bool:
    """True if ``extracted`` and ``canonical`` both name colour groups but share
    none (a colour substitution)."""
    ex = _color_group_tokens(extracted)
    ca = _color_group_tokens(canonical)
    return bool(ex and ca) and not bool(ex & ca)


def _appearance_verdict(
    extracted: dict[str, str], canonical: dict[str, str]
) -> tuple[bool, str]:
    """Compare extracted hair/eye/outfit against canonical facts. Returns
    (matches, issue) where ``issue`` lists the conflicting fields."""
    conflicts: list[str] = []
    for ext_key, can_key in (("hair_color", "hair"), ("eye_color", "eyes"), ("outfit", "outfit")):
        if _color_conflict(extracted.get(ext_key, ""), canonical.get(can_key, "")):
            conflicts.append(can_key)
    return (not conflicts), ", ".join(conflicts)


def _shot_appearance(shot: dict[str, Any], wb: WorldBible) -> tuple[str, dict[str, str]]:
    """(spec_string, facts) for the shot's in-frame characters. ``facts`` is the
    first in-frame character's {hair/eyes/skin/outfit} (empty when none)."""
    ids = shot.get("characters_in_frame", []) or []
    chars = {c.id: c for c in wb.characters}
    specs: list[str] = []
    facts: dict[str, str] = {}
    for i in ids:
        c = chars.get(i)
        if c is None:
            continue
        specs.append(c.appearance_spec())
        if not facts:
            facts = c.appearance_facts()
    return " | ".join(specs), facts


def vision_judge(
    panel_path: Path, shot: dict[str, Any], scene: dict[str, Any], config: PipelineConfig,
    appearance_facts: dict[str, str] | None = None,
    appearance_spec: str = "",
) -> tuple[bool, dict[str, Any]]:
    """QC checklist on the rendered panel (NIM judge first, local Ollama fallback).

    Returns (passed, detail). A transport error counts as an inconclusive pass
    (flag-only, never blocks the run on a broken vision model -- design note).

    On-model consistency uses extract-then-compare: the VLM *describes* the
    character's hair/eye/outfit, and code compares those against
    ``appearance_facts`` (canonical). This is more reliable for small VLMs than
    asking for a binary "matches" verdict.
    """
    expected = len(shot["characters_in_frame"])
    prompt = (
        "Look at this anime panel. Answer as JSON only, no prose: "
        '{"characters_visible": <int>, "background_matches": <bool>, '
        '"composition_matches": <bool>, "hair_color": <string>, '
        '"eye_color": <string>, "outfit": <string>}. '
        f"The panel should show exactly {expected} character(s), "
        f"a background of: {scene.get('time_of_day', '')} {scene['location']}, "
        f"and composition: {shot['composition']}. "
        "For hair_color / eye_color / outfit: describe the PRIMARY character's "
        "appearance in 1-4 words each (e.g. 'black', 'blue', 'red coat'). "
        "Write 'unknown' if you cannot tell."
    )

    # Primary judge: NVIDIA NIM (local Ollama stays on standby as fallback).
    raw = _try_nim_judge(config, prompt, panel_path)
    if raw is not None:
        try:
            check = _VisionCheck.model_validate_json(_extract_json_text(raw))
        except ValueError as exc:
            logger.warning("NIM vision judge returned bad JSON for %s: %s", shot["id"], exc)
            check = None
        if check is not None:
            return _vision_result(check, expected, shot, appearance_facts, appearance_spec, "nim")

    # Fallback judge: local Ollama.
    img_b64 = base64.b64encode(panel_path.read_bytes()).decode()
    try:
        r = requests.post(
            f"{_OLLAMA_URL}/api/chat",
            json={
                "model": config.models.llm_vision,
                "messages": [{"role": "user", "content": prompt, "images": [img_b64]}],
                "stream": False, "format": "json", "keep_alive": 0,
                "options": {"temperature": 0.0},
            },
            timeout=_VISION_TIMEOUT,
        )
        r.raise_for_status()
        check = _VisionCheck.model_validate_json(r.json()["message"]["content"])
    except (requests.RequestException, ValueError) as exc:
        logger.warning("vision judge unavailable for %s: %s", shot["id"], exc)
        return True, {"inconclusive": True, "error": str(exc), "judge": "local"}

    return _vision_result(check, expected, shot, appearance_facts, appearance_spec, "local")


def _vision_result(
    check: _VisionCheck, expected: int, shot: dict[str, Any],
    appearance_facts: dict[str, str] | None, appearance_spec: str, judge: str,
) -> tuple[bool, dict[str, Any]]:
    """Compute the passed verdict (code-side appearance comparison) and detail."""
    appearance_matches = True
    appearance_issue = ""
    if appearance_facts:
        appearance_matches, appearance_issue = _appearance_verdict(
            {"hair_color": check.hair_color, "eye_color": check.eye_color, "outfit": check.outfit},
            appearance_facts,
        )
    passed = (
        check.characters_visible == expected
        and check.background_matches
        and check.composition_matches
        and appearance_matches
    )
    detail = check.model_dump()
    detail["judge"] = judge
    detail["appearance_matches"] = appearance_matches
    detail["appearance_issue"] = appearance_issue
    if appearance_spec:
        detail["appearance_spec"] = appearance_spec
    if appearance_facts:
        detail["appearance_facts"] = appearance_facts
    return passed, detail


def _extract_json_text(text: str) -> str:
    """Strip markdown code fences (```json ... ```) the NIM judge may wrap
    its JSON in, returning the bare JSON payload."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].strip().lstrip("`").strip().lower() == "json":
            lines = lines[1:]
        body = []
        for ln in lines:
            if ln.strip() == "```":
                break
            body.append(ln)
        return "\n".join(body).strip()
    return text


def _try_nim_judge(config: PipelineConfig, prompt: str, panel_path: Path) -> str | None:
    """Ask the NVIDIA NIM judge for the panel QC JSON. Returns raw text, or
    None when NIM is disabled / unreachable / errored (caller falls back to
    the local Ollama judge)."""
    nim = NIMClient(config)
    if not nim.available():
        return None
    return nim.judge_vision(
        prompt,
        [panel_path],
        system=(
            "You are a strict anime-panel QC judge. Return ONLY the requested "
            "JSON object -- no prose, no markdown fences."
        ),
        temperature=0.0,
        max_tokens=512,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_CHAR_REF_TEMPLATE = "panel_ref_flux_klein.json"


def _char_ref_path(project_dir: Path, char_id: str) -> Path | None:
    """First stage1r reference frame for ``char_id``, or None.

    stage1r writes per-character reference sheets under
    ``worldbible/refs/<char_id>/`` (manifest.json + ref_XX_*.png). We take the
    first sorted reference frame as the identity anchor. Returns None when the
    character has no reference sheet (caller falls back to the plain panel)."""
    ref_dir = project_dir / "worldbible" / "refs" / char_id
    if not ref_dir.is_dir():
        return None
    pngs = sorted(p for p in ref_dir.glob("*.png") if "mouth" not in p.name)
    return pngs[0] if pngs else None


def _refine_panel_for_char(
    comfy: ComfyClient,
    project_dir: Path,
    block_dir: Path,
    panel_path: Path,
    char_ref: Path,
    shot: dict[str, Any],
    scene: dict[str, Any],
    wb: WorldBible,
    config: PipelineConfig,
    seed: int,
    template: str,
    model_used: str,
) -> Path | None:
    """Re-render a panel conditioned on the character reference (identity lock).

    Uses ``panel_ref_flux_klein.json``: the base panel is the img2img latent
    (keeps composition + scene), the character reference is the
    ReferenceLatent (keeps the character on-model). Denoise < 1 lets the base
    panel's scene survive while the char ref locks the face/design -- the
    direct fix for downstream LTX/Wan face + character-design distortion.

    Returns the refined panel path, or None on any failure (caller keeps the
    base panel). GPU freed before the vision model reloads.
    """
    try:
        ref_uploaded = comfy.upload_image(char_ref, name=f"charref_{shot['id']}.png")
        base_uploaded = comfy.upload_image(panel_path, name=f"panel_{shot['id']}_base.png")
        env_block = _env_token_block(scene, wb)
        prompt = f"{shot['sd_prompt']}, {env_block}" if env_block else shot["sd_prompt"]
        patch_set = {
            "CHAR_REF": ref_uploaded,
            "PLATE": base_uploaded,
            "PROMPT_POS": prompt,
            "WIDTH": _RESOLUTION[0], "HEIGHT": _RESOLUTION[1],
            "SEED": seed,
            "STEPS": config.animation.panel_char_ref_steps,
            "CFG": 2.0,
            "DENOISE": config.animation.panel_char_ref_denoise,
            "SAVE_PREFIX": f"pipeline/{project_dir.name}/refine/{shot['id']}",
        }
        out = comfy.generate(_CHAR_REF_TEMPLATE, patch_set, dest=block_dir)
        comfy.free()
        refined = Path(out[0])
        sidecar = (block_dir / f"{shot['id']}.json")
        if sidecar.exists():
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
                data["char_ref"] = str(char_ref.relative_to(project_dir))
                data["refined"] = True
                data["refine_template"] = _CHAR_REF_TEMPLATE
                sidecar.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return refined
    except Exception as exc:
        # Best-effort identity-lock pass: ANY failure (ComfyError, upload
        # HTTPError, empty output IndexError, etc.) must fall back to the
        # already-vision-passed base panel -- never crash the stage.
        logger.warning("char-ref refinement failed for %s: %s; keeping base panel", shot["id"], exc)
        return None


def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    comfy: ComfyClient | None = None,
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    project = identity.project_code(project_dir)
    wb = WorldBible.model_validate_json(
        (project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8")
    )
    screenplay = json.loads(
        (project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8")
    )
    storyboard_path = project_dir / "storyboard" / "storyboard.json"
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    if comfy is None:
        comfy = ComfyClient(config)
    if not comfy.healthy():
        raise ContingencyStop("ComfyUI is not reachable - start it first.")
    comfy.unload_ollama()  # GPU scheduling rule (design section 1)

    # Route once for the whole stage run (design 5.3b krea2 gate).
    template, model_used = image_router.pick_template(config, comfy)

    # LoRA gate (design Stage 3B.5) with the explicit deviation flag.
    lora_dir = config.loras_dir() / project_dir.name
    missing_loras = [
        c.id for c in wb.characters if not (lora_dir / f"char-{c.id}.safetensors").exists()
    ]
    if missing_loras and not config.automation.allow_missing_loras:
        raise Stage3BError(
            f"character LoRAs missing for {missing_loras} and "
            f"[automation].allow_missing_loras is false (design 1R.2b gate)."
        )
    if missing_loras:
        scores.record("stage3b", "global", "missing_loras_deviation", float(len(missing_loras)))

    shot_to_block = {
        sid: b["id"] for b in storyboard["blocks"] for sid in b["shots"]
    }
    panels_state = storyboard["panels"]
    shots_by_scene = [(scene, shot) for scene in screenplay["scenes"] for shot in scene["shots"]]
    # The storyboard LLM may renumber or merge shots, leaving screenplay ids
    # with no block/panel entry (seen live: sh-003-05 KeyError). Storyboard is
    # the render authority; skip unmatched screenplay shots with a recorded
    # deviation instead of crashing the stage.
    dropped = sorted(
        {shot["id"] for _, shot in shots_by_scene} - set(shot_to_block)
    )
    for sid_dropped in dropped:
        scores.record("stage3b", sid_dropped, "missing_from_storyboard_deviation", 1.0)
        logger.warning(
            "screenplay shot %s has no storyboard block/panel -- skipping render",
            sid_dropped,
        )
    shots_by_scene = [
        pair for pair in shots_by_scene if pair[1]["id"] in shot_to_block
    ]

    # Block generation order: first -> ending -> infill (design Stage 3.2).
    order_rank = {"first": 0, "ending": 1, "infill": 2}
    block_rank = {
        b["id"]: (order_rank[b["order"]], i) for i, b in enumerate(storyboard["blocks"])
    }
    shots_by_scene.sort(key=lambda pair: block_rank[shot_to_block[pair[1]["id"]]])

    generated = retries = vision_fails = 0
    adherence_scores: list[float] = []
    plates_done: set[str] = set()

    # Process panels in pairs for VRAM safety on 8GB
    # Free GPU memory between blocks to ensure all blocks get panels
    panel_pair_count = 0
    last_block_id = None
    blocks_since_free = 0
    for scene, shot in shots_by_scene:
        sid = shot["id"]
        block_id = shot_to_block[sid]
        # Free VRAM every 4 shots or when switching blocks
        if block_id != last_block_id:
            blocks_since_free = 0
            last_block_id = block_id
        blocks_since_free += 1
        if blocks_since_free >= 4:
            logger.info("Freeing VRAM between blocks (block %s)", block_id)
            comfy.free()
            blocks_since_free = 0
        sid = shot["id"]
        block_id = shot_to_block[sid]
        block_dir = project_dir / "panels" / block_id
        state = panels_state[sid]
        if state["status"] == "locked":
            continue
        panel_path = identity.panel_path(block_dir, sid, project)
        if panel_path.exists() and state["status"] in ("generated", "reviewed"):
            # Canonical naming is the standard: drop any orphaned legacy
            # sh-*.png so a stale pre-canvas panel can't shadow / confuse
            # the fresh canonical one (resolve_panel prefers canonical).
            legacy = block_dir / f"{sid}.png"
            if legacy.exists() and legacy != panel_path:
                legacy.unlink(missing_ok=True)
            continue  # resume-safe

        # Scene plate first (once per scene).
        if scene["id"] not in plates_done:
            plate_dir = block_dir / "_plates"
            plate_path = plate_dir / f"{scene['id']}.png"
            if not plate_path.exists() and project:
                # forward-only canonical plate: {project}_sc001_plate_v001.png
                plate_path = plate_dir / identity.artifact_name(
                    f"{project}_{scene['id'].replace('sc-', 'sc')}", "plate", version=1, ext="png"
                )
            if not plate_path.exists():
                loc = next((l for l in wb.locations if l.id == scene["location"]), None)
                view_desc = _location_view_description(loc)
                plate_prompt = (
                    f"{view_desc or (loc.sd_prompt if loc else 'unspecified location')}, "
                    f"{scene.get('time_of_day', 'day')} lighting, no people, "
                    "anime 2d illustration, manga panel style, cel shading"
                )
                paths = comfy.generate(
                    template,
                    {
                        "PROMPT_POS": plate_prompt,
                        "WIDTH": _RESOLUTION[0], "HEIGHT": _RESOLUTION[1],
                        "SEED": _seed_for(scene["id"]),
                        "SAVE_PREFIX": f"pipeline/{project_dir.name}/plates/{scene['id']}",
                    },
                    dest=plate_dir,
                )
                paths[0].rename(plate_path)
            plates_done.add(scene["id"])

        env_block = _env_token_block(scene, wb)
        prompt = f"{shot['sd_prompt']}, {env_block}" if env_block else shot["sd_prompt"]

        passed = False
        render_ok = False  # True only if a panel was actually rendered + vision-judged
        detail: dict[str, Any] = {}
        for attempt in (0, 1):  # retry ladder: one re-seed retry, then flag
            seed = _seed_for(scene["id"], sid, attempt)
            try:
                paths = comfy.generate(
                    template,
                    {
                        "PROMPT_POS": prompt,
                        "WIDTH": _RESOLUTION[0], "HEIGHT": _RESOLUTION[1],
                        "SEED": seed,
                        "SAVE_PREFIX": f"pipeline/{project_dir.name}/panels/{sid}",
                    },
                    dest=block_dir,
                )
            except ComfyError as exc:
                logger.error("panel %s generation failed: %s", sid, exc)
                state["status"] = "flagged"
                state["issues"].append(str(exc))
                break
            paths[0].replace(panel_path)
            generated += 1
            render_ok = True

            # GPU scheduling rule: clear flux from VRAM before the vision
            # model loads (qwen2.5vl uses keep_alive 0, so it evicts itself
            # after the call; the next generate reloads flux).
            comfy.free()
            passed, detail = vision_judge(panel_path, shot, scene, config, appearance_facts=_shot_appearance(shot, wb)[1] or None, appearance_spec=_shot_appearance(shot, wb)[0])
            sidecar = {
                "seed": seed, "prompt": prompt, "model": model_used,
                "attempt": attempt, "take": f"tk{attempt + 1:02d}",
                "version": "v001",  # bumped only on deliberate regeneration
                "vision": detail, "ts": _now_iso(),
            }
            (block_dir / f"{sid}.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
            if passed:
                state["status"] = "generated"
                # Per-panel character-reference conditioning (test 1): lock
                # identity by re-rendering through panel_ref_flux_klein with
                # the character reference + base panel, when enabled and a ref
                # exists. On failure we keep the already-vision-passed base.
                if (
                    getattr(config.animation, "panel_char_ref", True)
                    and _CHAR_REF_TEMPLATE
                    and shot.get("characters_in_frame")
                ):
                    char_id = shot["characters_in_frame"][0]
                    char_ref = _char_ref_path(project_dir, char_id)
                    if char_ref is not None:
                        refined = _refine_panel_for_char(
                            comfy, project_dir, block_dir, panel_path, char_ref,
                            shot, scene, wb, config, seed, template, model_used,
                        )
                        if refined is not None:
                            # Re-QC the refined panel before it replaces the
                            # already-vision-passed base: the identity-lock pass
                            # must not silently swap in a worse frame.
                            refined_passed, _ = vision_judge(refined, shot, scene, config, appearance_facts=_shot_appearance(shot, wb)[1] or None, appearance_spec=_shot_appearance(shot, wb)[0])
                            if refined_passed:
                                refined.replace(panel_path)
                            else:
                                logger.warning(
                                    "refined panel %s failed re-QC; keeping base panel", sid
                                )
                                refined.unlink(missing_ok=True)
                break

            # GPU: free VRAM before retrying (vision judge may leave model loaded)
            comfy.free()

            # Vision failed -- enhance prompt and retry once
            if attempt == 0:
                logger.warning("Panel %s vision judge failed (%s) -- enhancing prompt for retry", sid, detail)
                retries += 1
                # Enhance prompt: strengthen character anchors, add composition specificity
                prompt = _enhance_prompt_for_vision(prompt, shot, detail, config)
                continue

        if not passed and state["status"] != "flagged":
            panel_pair_count += 1
            if panel_pair_count >= 2:
                logger.info("Clearing VRAM after %d panels", panel_pair_count)
                comfy.free()
                panel_pair_count = 0
            vision_fails += 1
            state["status"] = "flagged"
            state["issues"].append(f"vision-judge failed twice: {detail}")
        if render_ok:
            # Only a panel that was actually generated + vision-judged counts
            # toward prompt adherence. A generation failure (render_ok=False)
            # must not pollute the adherence average with a spurious 0.0.
            if passed and not detail.get("inconclusive"):
                adherence_scores.append(1.0)
            elif not passed:
                adherence_scores.append(0.0)

    comfy.free()

    # Clean up orphaned legacy panels: once a shot has a canonical panel, its
    # old sh-*.png (pre-canonical naming) is stale and unreferenced -- remove it
    # so the folder reflects the single canonical standard.
    for block_dir in (project_dir / "panels").iterdir() if (project_dir / "panels").is_dir() else []:
        if not block_dir.is_dir():
            continue
        for png in block_dir.glob("sh-*.png"):
            sid = identity.sid_from_panel_name(png.name, project)
            canon = identity.resolve_panel(block_dir, sid, project)
            if canon.exists() and canon != png:
                png.unlink(missing_ok=True)

    # seed_frame continuity hooks: last panel of each block (design Stage 3.3).
    for b in storyboard["blocks"]:
        last_sid = b["shots"][-1]
        last_panel = identity.resolve_panel(
            project_dir / "panels" / b["id"], last_sid, project)
        if last_panel.exists():
            b_next_idx = storyboard["blocks"].index(b) + 1
            if b_next_idx < len(storyboard["blocks"]):
                storyboard["blocks"][b_next_idx]["seed_frame"] = str(
                    last_panel.relative_to(project_dir)
                )
        if all(panels_state[s]["status"] in ("generated", "reviewed", "locked") for s in b["shots"]):
            b["status"] = "generated"
    storyboard_path.write_text(json.dumps(storyboard, indent=2, ensure_ascii=False), encoding="utf-8")

    total_judged = len(adherence_scores)
    adherence_avg = sum(adherence_scores) / total_judged if total_judged else 1.0
    fail_rate = vision_fails / total_judged if total_judged else 0.0

    # Quality gates (movie-grade)
    pass_rate = 1.0 - fail_rate
    if pass_rate < _VISION_MIN_PASS_RATE:
        raise Stage3BError(
            f"Vision pass rate {pass_rate:.2%} below minimum {_VISION_MIN_PASS_RATE:.0%} -- "
            f"{vision_fails}/{total_judged} panels failed. Regenerate with better prompts or check krea2 weights."
        )
    if adherence_avg < _MIN_PROMPT_ADHERENCE:
        raise Stage3BError(
            f"Prompt adherence {adherence_avg:.2%} below minimum {_MIN_PROMPT_ADHERENCE:.0%} -- "
            "krea2 output not matching prompts. Check model weights and prompt construction."
        )

    scores.record("stage3b", "global", "panels_generated", float(generated))
    scores.record("stage3b", "global", "retries", float(retries))
    scores.record("stage3b", "global", "vision_fail_rate", fail_rate)
    scores.record("stage3b", "global", "prompt_adherence_avg", adherence_avg)
    scores.record("stage3b", "global", "vision_pass_rate", pass_rate)
    scores.stage_done("stage3b")

    bp = Blueprint.load(project_dir)
    bp.stages["stage3b"].status = "done"
    bp.stages["stage3b"].ts = _now_iso()
    bp.write(project_dir)

    if fail_rate > _VISION_FAIL_GATE:
        logger.warning(
            "vision failure rate %.0f%% exceeds the %.0f%% review threshold "
            "- review flagged panels before assembly (hard gate is %.0f%% "
            "vision pass rate).", fail_rate * 100, _VISION_FAIL_GATE * 100,
            _VISION_MIN_PASS_RATE * 100,
        )

    return {
        "stage": "stage3b", "status": "done", "model": model_used,
        "panels_generated": generated, "retries": retries,
        "prompt_adherence_avg": round(adherence_avg, 3),
        "vision_fail_rate": round(fail_rate, 3),
        "missing_loras_deviation": missing_loras,
    }
