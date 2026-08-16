"""Stage 3C -- ANIMATION (design section 4). Runs AFTER Stage 4.

Tier 0: CPU drift (no GPU). Tier 1-2: LTX-2 2B image-to-video (panel as start
frame, true motion -- verified 768x448x81f@16fps on 8GB VRAM via
``video_i2v_ltx_2b.json``). Tier 3: contingency-stop.
Tier 1-2 (Hailuo): Hailuo 2.3 I2V via API or ComfyUI for anime-style
character-consistent animation.
GPU scheduling: ComfyUI owns the GPU; Ollama unloaded before/after.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from ._util import now_iso, read_json, write_json, load_screenplay, load_storyboard, _shots_by_id
from .blueprint import Blueprint
from .comfy_client import ComfyClient, ComfyError
from .config import PipelineConfig
from . import realesrgan_upscale
from . import lipsync
from .gpu_lock import GpuBatch
from .scores import Scores
from .video_router import pick_ltx_template
from .hailuo_i2v import HailuoI2VClient, HailuoI2VResult

logger = logging.getLogger(__name__)

_DRIFT_PX = 350.0
_UPSCALE = 1.5
# Default resolution / frames / FPS / steps for primary video engine (Wan2.2)
# Wan2.2 TI2V: 1216x704, 81 frames @ 16fps, 20 steps unipc
_WAN_RES = (1216, 704)
_WAN_FRAMES = 81
_WAN_FPS = 16.0
_WAN_STEPS = {1: 20, 2: 20}  # tier1 ambient, tier2 director -- Wan uses 20 steps

# LTX-2B fallback (kept for reference)
_LTX_RES = (768, 448)
_LTX_FRAMES = 81
_LTX_FPS = 16.0
_LTX_STEPS = {1: 12, 2: 12}

# Quality thresholds
_MAX_DRIFT_REUSE = 3  # max consecutive drift shots before forcing LTX retry

# Hailuo 2.3 I2V defaults
_HAILUO_FRAMES = 81
_HAILUO_FPS = 16.0


def _postprocess_clip(clip_path: Path, *, skip_ffmpeg: bool = False) -> Path:
    """Upscale + sharpen via ffmpeg (CPU). Returns new path, or the original
    on a soft failure (ffmpeg missing, or non-zero exit). The previous
    version swallowed every exception silently -- a missing ffmpeg looked
    identical to success, hiding a system misconfiguration behind "good"
    output paths.

    When ``skip_ffmpeg`` is set (stage3c AI upscale enabled), the raw clip is
    left untouched -- the post-loop Real-ESRGAN pass owns the upscale, and
    running the cheap 1.5x scale first would only waste ESRGAN's budget on an
    already-upscaled frame."""
    if skip_ffmpeg:
        return clip_path
    if clip_path.suffix == ".mp4":
        out = clip_path.with_name(clip_path.stem + "_hq.mp4")
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", str(clip_path),
                "-vf", f"scale=trunc(iw*{_UPSCALE}/2)*2:trunc(ih*{_UPSCALE}/2)*2,unsharp=3:3:1.0",
                "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-an", str(out),
            ], capture_output=True, timeout=120, check=True)
        except FileNotFoundError:
            logger.warning("ffmpeg not found: skipping post-process for %s", clip_path.name)
            return clip_path
        except subprocess.CalledProcessError as exc:
            logger.warning("ffmpeg post-process failed for %s: %s", clip_path.name, exc)
            return clip_path
        return out
    return clip_path


def _seed_for(unit: str, variant: int = 0) -> int:
    return int(hashlib.sha256(f"{unit}:{variant}".encode()).hexdigest()[:12], 16)


def _seed_from_id(sid: str) -> int:
    return int.from_bytes(bytes.fromhex(sid.replace("sh-", "").replace("-", "")[:12].ljust(12, "0")), "big")


# Motion verification (optical flow, calibrated 2026-08-12 against real clips).
# The old mean-abs-frame-diff rule could not separate a directed pan from
# shake, and admitted a wholly static Wan render (0.08 px/frame optical flow)
# as "motion". Farneback median flow gives two independent, calibrated axes:
#   camera  -- median-flow translation per frame (px) at analysis width 320.
#              A directed pan nets a large displacement; shake nets ~0.
#   scene   -- 75th-pct residual flow after removing the camera translation.
# Admission (any-axis): camera move OR scene motion, both above floors.
# A clip fails if BOTH are static (cam < CAM_FLOOR and scene < SCENE_FLOOR)
# or the camera is shake (poor direction coherence + no net span).
_MOTION_ANALYSIS_WIDTH = 320
_MOTION_CAM_FLOOR_PX = 0.30  # mean camera speed needed to count as a move
_MOTION_CAM_DIRECT_MIN = 0.50  # min net-span fraction of travelled path (shake fails)
_MOTION_CAM_NET_MIN_PX = 8.0  # min net displacement to be a directed shot
_MOTION_SCENE_FLOOR_PX = 0.35  # 75th-pct residual flow for scene motion
_MOTION_JITTER_MAX = 12.0  # peak-to-mean camera speed swings (rejects spasms)


def verify_clip_motion(clip_path: Path) -> dict[str, Any]:
    """Optical-flow gate for a rendered clip. Returns a dict of metrics plus
    ``motion_verified`` (any-axis admission) — False if static or shake."""
    metrics = {
        "cam_speed_px": 0.0, "cam_net_px": 0.0, "cam_directed": 0.0,
        "cam_jitter": 0.0, "scene_speed_px": 0.0,
        "motion_verified": False, "motion_axis": "none",
    }
    try:
        import cv2
        cap = cv2.VideoCapture(str(clip_path))
        if not cap.isOpened():
            logger.warning("Motion verification: cannot open clip %s", Path(clip_path).name)
            return metrics
        prev = None
        cam_speeds: list[float] = []
        scene_speeds: list[float] = []
        net = np.zeros(2, dtype=np.float64)
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (_MOTION_ANALYSIS_WIDTH,
                                     int(_MOTION_ANALYSIS_WIDTH * gray.shape[0] / gray.shape[1])))
            if prev is not None:
                flow = cv2.calcOpticalFlowFarneback(prev, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                fx = flow[..., 0].ravel()
                fy = flow[..., 1].ravel()
                cam_x, cam_y = float(np.median(fx)), float(np.median(fy))
                cam = np.hypot(cam_x, cam_y)
                cam_speeds.append(cam)
                net[0] += cam_x
                net[1] += cam_y
                residual = np.hypot(fx - cam_x, fy - cam_y)
                scene_speeds.append(float(np.percentile(residual, 75)))
            prev = gray
        cap.release()

        n = len(cam_speeds)
        if n == 0:
            logger.warning("Motion verification: no frame pairs in %s", Path(clip_path).name)
            return metrics

        cam_speed = float(np.mean(cam_speeds))
        scene_speed = float(np.mean(scene_speeds))
        net_span = float(np.linalg.norm(net))
        travelled = cam_speed * n
        directed = net_span / travelled if travelled > 0 else 0.0
        jitter = float(np.ptp(cam_speeds) / (cam_speed + 1e-9))

        camera_ok = (
            cam_speed >= _MOTION_CAM_FLOOR_PX
            and directed >= _MOTION_CAM_DIRECT_MIN
            and net_span >= _MOTION_CAM_NET_MIN_PX
            and jitter <= _MOTION_JITTER_MAX
        )
        scene_ok = scene_speed >= _MOTION_SCENE_FLOOR_PX
        if camera_ok and scene_ok:
            axis = "camera+scene"
        elif camera_ok:
            axis = "camera"
        elif scene_ok:
            axis = "scene"
        else:
            axis = "none"

        metrics.update({
            "cam_speed_px": round(cam_speed, 3), "cam_net_px": round(net_span, 2),
            "cam_directed": round(directed, 3), "cam_jitter": round(jitter, 2),
            "scene_speed_px": round(scene_speed, 3),
            "motion_verified": axis != "none", "motion_axis": axis,
        })
        return metrics
    except Exception as exc:
        logger.warning("Motion verification failed for %s: %s", Path(clip_path).name, exc)
        return metrics


def _motion_prompt(shot: dict[str, Any], tier: int) -> str:
    base = shot.get("sd_prompt", "anime scene")
    comp = shot.get("composition", "medium shot")
    light = shot.get("lighting", "cinematic lighting")
    if tier == 1:
        return f"{comp} {base}. {light}. Subtle ambient motion: hair drifts, cloth sways, particles float. Shallow depth of field."
    if tier == 2:
        cam = shot.get("camera_movement") or "slow dolly in"
        return f"{comp} {base}. {light}. Camera {cam}, focused on subject. Dynamic anime scene with natural motion."
    return base


def _plate_key_for_scene(scene: dict[str, Any], shot: dict[str, Any] | None = None) -> str:
    loc = scene.get("location", "unknown")
    tod = scene.get("time_of_day", "day")
    angle = shot.get("composition", "wide") if shot else "wide"
    return f"{loc}__{tod}__{angle}".replace(" ", "_").replace("/", "-")


def _master_plate_dir(project_dir: Path) -> Path:
    return project_dir / "panels" / "_plates"


def _plate_path_for(panel_path: Path, key: str) -> Path:
    return _master_plate_dir(panel_path.parent.parent) / f"{key}.png"


def _clip_cache_key(
    panel: Path,
    motion_prompt: str,
    template: str,
    steps: int,
    seed: int,
    *,
    ai_upscale: bool,
) -> str:
    """Stable cache key: hash of all inputs that affect the rendered clip."""
    import hashlib
    h = hashlib.sha256()
    h.update(panel.read_bytes())
    h.update(motion_prompt.encode())
    h.update(template.encode())
    h.update(str(steps).encode())
    h.update(str(seed).encode())
    h.update(str(int(ai_upscale)).encode())
    return h.hexdigest()[:16]


def _clip_cache_load(clips_dir: Path) -> dict[str, str]:
    cache_file = clips_dir / ".ltx_cache.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _clip_cache_store(clips_dir: Path, key: str, clip_path: Path) -> None:
    cache_file = clips_dir / ".ltx_cache.json"
    cache = _clip_cache_load(clips_dir)
    cache[key] = str(clip_path.relative_to(clips_dir))
    cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _render_hailuo_shot(
    sid: str,
    panel: Path,
    motion_prompt: str,
    orig: int,
    project_dir: Path,
    config: PipelineConfig,
    hailuo: HailuoI2VClient,
    shots_by_id: dict[str, Any],
) -> tuple[bool, str | None]:
    """Render a single shot via Hailuo 2.3 I2V.

    Returns (success, clip_path_or_none).
    """
    try:
        result: HailuoI2VResult = hailuo.generate(
            start_image=panel,
            prompt=motion_prompt,
            duration_s=_HAILUO_FRAMES / _HAILUO_FPS,
            seed=_seed_from_id(sid),
        )
        if not result.success:
            logger.error("Hailuo I2V failed for %s: %s", sid, result.error)
            return False, None

        # Copy to project clips dir for consistency
        clips_dir = project_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        import shutil
        dest = clips_dir / f"{sid}_hailuo.mp4"
        shutil.copy2(result.clip_path, dest)

        return True, str(dest.relative_to(project_dir))

    except Exception as exc:
        logger.error("Hailuo I2V error for %s: %s", sid, exc)
        return False, None


def _render_ltx_phase(
    shot_order: list[str],
    shot_detail: dict[str, Any],
    shots_by_id: dict[str, Any],
    storyboard: dict[str, Any],
    project_dir: Path,
    config: PipelineConfig,
    comfy: ComfyClient,
    scores: Scores,
    tier0: int,
    tier1: int,
    tier2: int,
    tier3: int,
    rendered: int,
    failed: int,
    cache_hits: int,
) -> tuple[int, int, int, int, int, int, int]:
    """LTX I2V render phase (GPU). Returns updated counters."""
    axis = config.animation.drift_axis
    pixels = round(_DRIFT_PX * (720 / 576.0), 1)

    gpu_batch = GpuBatch("stage3c", comfy)
    if not gpu_batch.acquire():
        logger.error("GPU is owned by another stage - refusing to render LTX")
        scores.record("stage3c", "global", "gpu_lock_contention", 1.0)
        return tier0, tier1, tier2, tier3, rendered, failed, cache_hits

    try:
        cache: dict[str, str] | None = None
        for sid in shot_order:
            d = shot_detail[sid]
            orig = d["planned_tier"]
            if orig == 3:
                tier3 += 1
                continue
            if orig not in (1, 2):
                continue

            block_id = next((b["id"] for b in storyboard["blocks"] if sid in b["shots"]), None)
            if not block_id:
                continue
            panel = project_dir / "panels" / block_id / f"{sid}.png"
            if not panel.exists():
                logger.warning("panel %s not found, skipping", sid)
                failed += 1
                tier0 += 1
                continue

            steps = _WAN_STEPS.get(orig, 20)
            ltx_template = pick_ltx_template(config, orig, _WAN_FRAMES)
            if ltx_template is None:
                logger.warning("Video template unavailable for %s, degrading to drift", sid)
                d["motion_tier"] = 0
                if s := shots_by_id.get(sid):
                    s["motion_tier"] = 0
                tier0 += 1
                failed += 1
                continue

            # Select engine-specific constants
            if ltx_template == "wan_ti2v.json":
                res = _WAN_RES
                frames = _WAN_FRAMES
                fps = _WAN_FPS
            else:
                # LTX fallback
                res = _LTX_RES
                frames = _LTX_FRAMES
                fps = _LTX_FPS
                steps = _LTX_STEPS.get(orig, 12)

            clips_dir = project_dir / "clips"
            clips_dir.mkdir(exist_ok=True)
            motion_prompt = _motion_prompt(shots_by_id.get(sid, {}), orig)

            if cache is None:
                cache = _clip_cache_load(clips_dir)
            key = _clip_cache_key(panel, motion_prompt, ltx_template, steps, _seed_from_id(sid),
                                  ai_upscale=config.animation.ai_upscale)
            cached_rel = cache.get(key)
            cached_clip = (clips_dir / cached_rel) if cached_rel else None
            if cached_clip is not None and cached_clip.exists():
                d["motion_tier"] = orig
                d["clip_path"] = str(cached_clip.relative_to(project_dir))
                d["ltx_template"] = ltx_template
                d["cache_hit"] = True
                if s := shots_by_id.get(sid):
                    s["motion_tier"] = orig
                    s["clip_path"] = d["clip_path"]
                if orig == 1:
                    tier1 += 1
                else:
                    tier2 += 1
                rendered += 1
                cache_hits += 1
                logger.info("LTX cache hit for %s", sid)
                continue

            try:
                uploaded = comfy.upload_image(panel, name=f"anim_{sid}.png")
                paths = comfy.generate(ltx_template, {
                    "MOTION_PROMPT": motion_prompt,
                    "START_FRAME": uploaded,
                    "WIDTH": res[0], "HEIGHT": res[1],
                    "FRAMES": frames, "STEPS": steps,
                    "SEED": _seed_from_id(sid), "FPS": fps,
                    "SAVE_PREFIX": f"pipeline/{project_dir.name}/clips/{sid}",
                }, dest=clips_dir)
                clip_path = _postprocess_clip(paths[0], skip_ffmpeg=config.animation.ai_upscale)

                # Quality gate: optical-flow verification (camera + scene axes)
                motion = verify_clip_motion(clip_path)
                if not motion["motion_verified"]:
                    logger.warning(
                        "LTX clip %s motion gate FAILED (axis=%s, cam=%.2fpx, "
                        "net=%.1fpx, scene=%.2fpx) -- treating as drift",
                        sid, motion["motion_axis"], motion["cam_speed_px"],
                        motion["cam_net_px"], motion["scene_speed_px"],
                    )
                    d["motion_tier"] = 0
                    failed += 1
                    clip_path.unlink(missing_ok=True)
                    continue

                d["motion_tier"] = orig
                d["clip_path"] = str(clip_path.relative_to(project_dir))
                d["ltx_template"] = ltx_template
                d["motion_verified"] = motion
                if s := shots_by_id.get(sid):
                    s["motion_tier"] = orig
                    s["clip_path"] = d["clip_path"]
                    s["motion_verified"] = motion
                if orig == 1:
                    tier1 += 1
                else:
                    tier2 += 1
                rendered += 1
                _clip_cache_store(clips_dir, key, clip_path)
            except ComfyError as exc:
                logger.error("LTX I2V render failed for %s: %s, falling back to drift", sid, exc)
                d["motion_tier"] = 0
                failed += 1
    finally:
        gpu_batch.release()

    return tier0, tier1, tier2, tier3, rendered, failed, cache_hits


def _render_hailuo_phase(
    shot_order: list[str],
    shot_detail: dict[str, Any],
    shots_by_id: dict[str, Any],
    storyboard: dict[str, Any],
    project_dir: Path,
    config: PipelineConfig,
    hailuo: HailuoI2VClient,
    scores: Scores,
    tier0: int,
    tier1: int,
    tier2: int,
    tier3: int,
    rendered: int,
    failed: int,
) -> tuple[int, int, int, int, int, int]:
    """Hailuo 2.3 I2V render phase (GPU or API). Returns updated counters."""
    for sid in shot_order:
        d = shot_detail[sid]
        orig = d["planned_tier"]
        if orig == 3:
            tier3 += 1
            continue
        if orig not in (1, 2):
            continue

        block_id = next((b["id"] for b in storyboard["blocks"] if sid in b["shots"]), None)
        if not block_id:
            continue
        panel = project_dir / "panels" / block_id / f"{sid}.png"
        if not panel.exists():
            logger.warning("panel %s not found, skipping", sid)
            failed += 1
            tier0 += 1
            continue

        clips_dir = project_dir / "clips"
        clips_dir.mkdir(exist_ok=True)
        motion_prompt = _motion_prompt(shots_by_id.get(sid, {}), orig)

        success, clip_rel = _render_hailuo_shot(sid, panel, motion_prompt, orig,
                                                project_dir, config, hailuo, shots_by_id)
        if not success:
            d["motion_tier"] = 0
            failed += 1
            tier0 += 1
            continue

        d["motion_tier"] = orig
        d["clip_path"] = clip_rel
        d["hailuo_job"] = True
        if s := shots_by_id.get(sid):
            s["motion_tier"] = orig
            s["clip_path"] = clip_rel
        if orig == 1:
            tier1 += 1
        else:
            tier2 += 1
        rendered += 1

    return tier0, tier1, tier2, tier3, rendered, failed


def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    comfy: ComfyClient | None = None,
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    storyboard = load_storyboard(project_dir)
    screenplay = load_screenplay(project_dir)

    if comfy is None:
        comfy = ComfyClient(config)

    axis = config.animation.drift_axis
    pixels = round(_DRIFT_PX * (720 / 576.0), 1)
    shot_detail = storyboard["shot_detail"]
    shots_by_id = _shots_by_id(screenplay)
    shot_order = [sid for scene in screenplay["scenes"] for shot in scene["shots"] for sid in [shot["id"]]]

    tier0 = tier1 = tier2 = tier3 = 0
    rendered = failed = cache_hits = 0

    # Engine selection
    engine = getattr(config.animation, "engine", "ltx2b")
    hailuo = HailuoI2VClient(config) if engine == "hailuo23" else None

    # Phase 1: Assign tiers, render Tier 0 (drift, no GPU)
    consecutive_drift = 0
    for i, sid in enumerate(shot_order):
        d = shot_detail[sid]
        orig = d.get("planned_tier", d["motion_tier"])
        if orig == 0:
            # Planned as drift, stays drift -- consistent direction per shot (not ping-pong)
            shot_hash = int(hashlib.sha256(sid.encode()).hexdigest()[:8], 16)
            direction = 1 if (shot_hash % 2 == 0) else -1
            d["drift"] = {"axis": axis, "direction": direction, "pixels": pixels, "consistent": True}
            if s := shots_by_id.get(sid):
                s["motion_tier"] = 0
            tier0 += 1
            consecutive_drift += 1
        else:
            # Planned for LTX/Hailuo (1,2,3) -- initially mark drift, Phase 2 will upgrade
            d["motion_tier"] = 0
            d["planned_tier"] = orig
            shot_hash = int(hashlib.sha256(sid.encode()).hexdigest()[:8], 16)
            direction = 1 if (shot_hash % 2 == 0) else -1
            d["drift"] = {"axis": axis, "direction": direction, "pixels": pixels, "consistent": True}
            if s := shots_by_id.get(sid):
                s["motion_tier"] = 0
                s["planned_tier"] = orig
            consecutive_drift = 0

    # Phase 2: Render with selected engine
    if engine == "hailuo23":
        if not hailuo or not hailuo.available():
            logger.error("Hailuo 2.3 I2V not available")
            scores.record("stage3c", "global", "hailuo_unavailable", 1.0)
            return {
                "stage": "stage3c", "status": "blocked",
                "reason": "Hailuo backend unavailable",
                "tier0_drift": len(shot_order),
            }

        tier0, tier1, tier2, tier3, rendered, failed = _render_hailuo_phase(
            shot_order, shot_detail, shots_by_id, storyboard,
            project_dir, config, hailuo, scores,
            tier0, tier1, tier2, tier3, rendered, failed,
        )
    else:
        # LTX or LTX Director path
        tier0, tier1, tier2, tier3, rendered, failed, cache_hits = _render_ltx_phase(
            shot_order, shot_detail, shots_by_id, storyboard,
            project_dir, config, comfy, scores,
            tier0, tier1, tier2, tier3, rendered, failed, cache_hits,
        )

    # Lip-sync pass (Tier-3 shots) -- runs after render loop, GPU is free
    lipsync_result = {"lipsync_rendered": 0, "lipsync_failed": 0}
    if any(d.get("planned_tier") == 3 for d in shot_detail.values()):
        logger.info("Starting lip-sync pass for Tier-3 shots")
        try:
            lipsync_result = lipsync.render_lip_sync_for_project(
                project_dir, config, scores, comfy=comfy
            )
        except Exception as exc:
            logger.error("Lip-sync pass failed: %s", exc)
            lipsync_result = {"lipsync_rendered": 0, "lipsync_failed": 1}

    # Post-loop Real-ESRGAN upscale (after the GPU lock is released so the
    # ncnn/Vulkan binary never contends with a ComfyUI render). Only clips
    # without an ``.ai`` marker are reprocessed, so cached clips that were
    # already upscaled are left untouched on a re-run.
    ai_upscaled = 0
    if config.animation.ai_upscale and realesrgan_upscale.available():
        for sid, d in shot_detail.items():
            if d.get("motion_tier") not in (1, 2):
                continue
            rel = d.get("clip_path")
            if not rel:
                continue
            clip = project_dir / rel
            marker = project_dir / f"{rel}.ai"
            if marker.exists() or not clip.exists():
                continue
            if realesrgan_upscale.upscale_clip(
                clip,
                scale=config.animation.ai_upscale_scale,
                model=config.animation.ai_upscale_model,
            ) is not None:
                marker.write_text("ai-upscaled\n", encoding="utf-8")
                ai_upscaled += 1

    write_json(project_dir / "storyboard" / "storyboard.json", storyboard)
    write_json(project_dir / "screenplay" / "screenplay.json", screenplay)

    total_shots = len(shot_order)
    planned_animated = sum(1 for d in shot_detail.values() if d.get("planned_tier") in (1, 2))
    tier_degraded = sum(1 for d in shot_detail.values() if d.get("planned_tier") in (1, 2, 3) and d.get("motion_tier") == 0)
    coverage = (planned_animated / total_shots) if total_shots else 0.0

    # Quality gates (movie-grade)
    degradation_rate = tier_degraded / planned_animated if planned_animated else 1.0
    if degradation_rate > 0.30:
        raise RuntimeError(
            f"Stage3c degradation rate {degradation_rate:.1%} exceeds 30% limit -- "
            f"{tier_degraded}/{planned_animated} planned animated shots fell back to drift. "
            "Check LTX weights, VRAM, and motion prompts."
        )
    if rendered == 0 and planned_animated > 0:
        raise RuntimeError("Stage3c: zero clips rendered despite planned animated shots")

    scores.record_globals("stage3c", {
        "tier_degraded_shots": tier_degraded, "tier0_drift_shots": tier0,
        "tier1_ambient_shots": tier1, "tier2_director_shots": tier2,
        "tier3_lipsync_pending": tier3, "ltx_rendered": rendered, "ltx_failed": failed,
        "ltx_cache_hits": cache_hits, "ltx_cache_rate": (cache_hits / rendered) if rendered else 0.0,
        "animation_coverage": coverage,
        "ltx_contingency": 0.0 if rendered > 0 else 1.0,
        "lipsync_contingency": 0.0 if lipsync_result.get("lipsync_rendered", 0) > 0 else 1.0,
        "lipsync_overlap_avg": 0.0, "lipsync_shots_processed": float(lipsync_result.get("lipsync_rendered", 0) + lipsync_result.get("lipsync_failed", 0)),
        "ai_upscaled_clips": float(ai_upscaled),
    })
    scores.stage_done("stage3c")
    Blueprint.mark_stage(project_dir, "stage3c")

    return {"stage": "stage3c", "status": "done", "tier_degraded_shots": tier_degraded,
            "tier0_drift": tier0, "tier1_ambient": tier1, "tier2_director": tier2,
            "tier3_lipsync_pending": tier3, "ltx_rendered": rendered, "ltx_failed": failed,
            "ltx_cache_hits": cache_hits, "animation_coverage": round(coverage, 3),
            "lipsync_rendered": lipsync_result.get("lipsync_rendered", 0),
            "lipsync_failed": lipsync_result.get("lipsync_failed", 0),
            "engine": engine,
            "hailuo_available": bool(hailuo and hailuo.available()),
            "ai_upscaled_clips": ai_upscaled}