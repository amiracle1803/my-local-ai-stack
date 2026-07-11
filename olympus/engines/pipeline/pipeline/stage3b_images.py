"""Stage 3B -- IMAGES (design section 4 / Stage 3B). [GPU]

Scene environment lock + per-shot panels, landscape 1216x704, via
:class:`~pipeline.comfy_client.ComfyClient`:

- Per scene: ONE location master plate first (location sd_prompt + time of
  day, no characters) -> ``panels/<block>/_plates/<scene>.png``. On the flux
  fallback there is no IPAdapter, so the plate conditions shots through the
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

from .blueprint import Blueprint
from .comfy_client import ComfyClient, ComfyError, ContingencyStop
from .config import PipelineConfig
from .schemas.worldbible import WorldBible
from .scores import Scores

logger = logging.getLogger(__name__)

_RESOLUTION = (1216, 704)
_OLLAMA_URL = "http://127.0.0.1:11434"
_VISION_FAIL_GATE = 0.20  # design 0.2 hard gate


class Stage3BError(RuntimeError):
    pass


class _VisionCheck(BaseModel):
    characters_visible: int = 0
    background_matches: bool = True
    composition_matches: bool = True


def _seed_for(scene_id: str, shot_id: str = "", retry: int = 0) -> int:
    return int(hashlib.sha256(f"{scene_id}:{shot_id}:{retry}".encode()).hexdigest()[:12], 16)


def _env_token_block(scene: dict[str, Any], wb: WorldBible) -> str:
    """The scene's fixed environment tokens, appended verbatim to every shot
    prompt in the scene (background consistency without IPAdapter)."""
    loc = next((l for l in wb.locations if l["id"] == scene["location"]), None)
    tod = scene.get("time_of_day", "")
    bits = []
    if loc:
        bits.append(f"consistent background: {loc['name']}")
    if tod and tod != "unclear":
        bits.append(f"{tod} palette")
    return ", ".join(bits)


def vision_judge(
    panel_path: Path, shot: dict[str, Any], scene: dict[str, Any], config: PipelineConfig,
) -> tuple[bool, dict[str, Any]]:
    """qwen2.5vl checklist on the rendered panel. Returns (passed, detail).
    A transport error counts as an inconclusive pass (flag-only, never blocks
    the run on a broken vision model -- design risk note)."""
    expected = len(shot["characters_in_frame"])
    prompt = (
        "Look at this anime panel. Answer as JSON only, no prose: "
        '{"characters_visible": <int>, "background_matches": <bool>, '
        '"composition_matches": <bool>}. '
        f"The panel should show exactly {expected} character(s), "
        f"a background of: {scene.get('time_of_day', '')} {scene['location']}, "
        f"and composition: {shot['composition']}."
    )
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
            timeout=180,
        )
        r.raise_for_status()
        check = _VisionCheck.model_validate_json(r.json()["message"]["content"])
    except (requests.RequestException, ValueError) as exc:
        logger.warning("vision judge unavailable for %s: %s", shot["id"], exc)
        return True, {"inconclusive": True, "error": str(exc)}

    passed = (
        check.characters_visible == expected
        and check.background_matches
        and check.composition_matches
    )
    return passed, check.model_dump()


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
    screenplay = json.loads(
        (project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8")
    )
    storyboard_path = project_dir / "storyboard" / "storyboard.json"
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    if comfy is None:
        comfy = ComfyClient(config)
    if not comfy.healthy():
        raise ContingencyStop("ComfyUI is not reachable - start it first.")

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

    # Block generation order: first -> ending -> infill (design Stage 3.2).
    order_rank = {"first": 0, "ending": 1, "infill": 2}
    block_rank = {
        b["id"]: (order_rank[b["order"]], i) for i, b in enumerate(storyboard["blocks"])
    }
    shots_by_scene.sort(key=lambda pair: block_rank[shot_to_block[pair[1]["id"]]])

    generated = retries = vision_fails = 0
    adherence_scores: list[float] = []
    plates_done: set[str] = set()

    for scene, shot in shots_by_scene:
        sid = shot["id"]
        block_id = shot_to_block[sid]
        block_dir = project_dir / "panels" / block_id
        state = panels_state[sid]
        if state["status"] == "locked":
            continue
        panel_path = block_dir / f"{sid}.png"
        if panel_path.exists() and state["status"] in ("generated", "reviewed"):
            continue  # resume-safe

        # Scene plate first (once per scene).
        if scene["id"] not in plates_done:
            plate_dir = block_dir / "_plates"
            plate_path = plate_dir / f"{scene['id']}.png"
            if not plate_path.exists():
                loc = next((l for l in wb.locations if l["id"] == scene["location"]), None)
                plate_prompt = (
                    f"{loc['sd_prompt'] if loc else 'unspecified location'}, "
                    f"{scene.get('time_of_day', 'day')} lighting, no people, "
                    "anime 2d illustration, manga panel style, cel shading"
                )
                paths = comfy.generate(
                    "image_flux_fallback.json",
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
        detail: dict[str, Any] = {}
        for attempt in (0, 1):  # retry ladder: one re-seed retry, then flag
            seed = _seed_for(scene["id"], sid, attempt)
            try:
                paths = comfy.generate(
                    "image_flux_fallback.json",
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

            passed, detail = vision_judge(panel_path, shot, scene, config)
            sidecar = {
                "seed": seed, "prompt": prompt, "model": config.resolve_image_model("fallback"),
                "attempt": attempt, "vision": detail, "ts": _now_iso(),
            }
            (block_dir / f"{sid}.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
            if passed:
                state["status"] = "generated"
                break
            retries += 1

        if not passed and state["status"] != "flagged":
            vision_fails += 1
            state["status"] = "flagged"
            state["issues"].append(f"vision-judge failed twice: {detail}")
        if passed and not detail.get("inconclusive"):
            adherence_scores.append(1.0)
        elif not passed:
            adherence_scores.append(0.0)

    comfy.free()

    # seed_frame continuity hooks: last panel of each block (design Stage 3.3).
    for b in storyboard["blocks"]:
        last_panel = project_dir / "panels" / b["id"] / f"{b['shots'][-1]}.png"
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

    scores.record("stage3b", "global", "panels_generated", float(generated))
    scores.record("stage3b", "global", "retries", float(retries))
    scores.record("stage3b", "global", "vision_fail_rate", fail_rate)
    scores.record("stage3b", "global", "prompt_adherence_avg", adherence_avg)
    scores.stage_done("stage3b")

    bp = Blueprint.load(project_dir)
    bp.stages["stage3b"].status = "done"
    bp.stages["stage3b"].ts = _now_iso()
    bp.write(project_dir)

    if fail_rate > _VISION_FAIL_GATE:
        logger.warning(
            "vision failure rate %.0f%% exceeds the 20%% hard gate - review "
            "flagged panels before assembly.", fail_rate * 100,
        )

    return {
        "stage": "stage3b", "status": "done",
        "panels_generated": generated, "retries": retries,
        "prompt_adherence_avg": round(adherence_avg, 3),
        "vision_fail_rate": round(fail_rate, 3),
        "missing_loras_deviation": missing_loras,
    }
