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
from .comfy_client import ComfyClient, ComfyError, ContingencyStop
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
_WAN_RES = (672, 384)
_WAN_FRAMES = 33
_WAN_FPS = 16.0
_WAN_STEPS = {1: 14, 2: 16}  # tier1 ambient, tier2 director -- Wan conservative start (per 2026-08-20 tuning)
_WAN_CFG = 2.5  # Wan 2.2 TI2V-5B starting CFG (low-vram conservative)
# Wan 2.2 negative prompt: block identity/style drift and morphing (2026-08-20 tuning)
_WAN_NEG = (
    "character redesign, changing clothes, face distortion, extra arms, extra fingers, "
    "duplicated subject, flicker, morphing, text, watermark, extreme camera shake, "
    "sudden scene change, low-detail face"
)
# Wan 2.2 two-keyframe path: END frame generated via Flux-2-Klein img2img from the
# START panel, injected at the end of the latent sequence (WanVideoAddExtraLatent -1).
_WAN_2F_TEMPLATE = "wan_ti2v_2f.json"
_END_FRAME_TEMPLATE = "panel_i2i_flux_klein.json"
_END_FRAME_DENOISE = 0.55
_END_FRAME_STEPS = 20
_END_FRAME_CFG = 2.0

# LTX-2B fallback (kept for reference)
_LTX_RES = (768, 448)
_LTX_FRAMES = 81
_LTX_FPS = 16.0
_LTX_STEPS = {1: 15, 2: 20}

# LTX-2.3 22B 8GB (proven permanent stage3c engine, 2026-08-20):
# non-tiled sampler + tiled VAE decode. 576x320x49f@24, 6 steps distilled,
# strength 0.7, cfg 1.0, euler_ancestral_cfg_pp. Hair-physics motion focus.
_LTX23_8GB_TEMPLATE = "video_i2v_ltx_23b_8gb.json"
_LTX23_8GB_RES = (576, 320)
_LTX23_8GB_FRAMES = 49
_LTX23_8GB_FPS = 24.0
_LTX23_8GB_STEPS = 6
_LTX23_8GB_CFG = 1.0
_LTX23_8GB_STRENGTH = 0.7

# LTX Director (V2V director) -- LTXDirector node on the same 8GB stack.
# Timeline image keyframe + text beat, LTXDirectorGuide keyframe guidance.
# 97 frames @24fps = 4s (LTX 8n+1 latent rule; docs recommend 97f/4s, 121f/5s).
# 8 steps distilled, cfg 1.0. End-of-clip blur is handled by the workflow's
# native LTXVSpatioTemporalTiledVAEDecode last_frame_fix (zero extra GPU work),
# not by a second img2img end-frame render. Verified 2026-08-20: smoke gate
# produced a motion-verified clip.
_DIRECTOR_TEMPLATE = "ltx_director_23.json"
_DIRECTOR_RES = (576, 320)
_DIRECTOR_FRAMES = 97
_DIRECTOR_FPS = 24.0
_DIRECTOR_STEPS = 8
_DIRECTOR_CFG = 1.0

# SVD XT (Stable Video Diffusion, ComfyUI-native, 25f / 6fps native)
_SVD_RES = (832, 480)
_SVD_FRAMES = 25
_SVD_FPS = 6
_SVD_STEPS = 20
_SVD_MODEL = "svd_xt-fp16.safetensors"
_SVD_MOTION_BUCKET = 127

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


def _motion_prompt(shot: dict[str, Any], tier: int, template: str = "") -> str:
    base = shot.get("sd_prompt", "anime scene")
    comp = shot.get("composition", "medium shot")
    light = shot.get("lighting", "cinematic lighting")
    # Wan 2.2 TI2V-5B prompting (2026-08-20 tuning): ONE subject + ONE action
    # + ONE camera instruction, concise, stability phrasing to preserve the
    # Flux keyframe identity. LTX keeps the fuller ambient phrasing.
    if template == "wan_ti2v.json":
        if tier == 1:
            return (
                f"{base}. {comp}. {light}. The character moves gently, hair and "
                "clothes sway softly in the wind, subtle ambient motion, stable "
                "anime illustration, consistent face and outfit."
            )
        cam = shot.get("camera_movement") or "slow push-in"
        return (
            f"{base}. {comp}. {light}. One controlled action, camera {cam}, "
            "stable anime illustration, consistent face and outfit."
        )
    if template == _LTX23_8GB_TEMPLATE:
        # LTX-2.3 22B 8GB (permanent engine): concise prompt with STRONG hair
        # physics emphasis up front. The full sd_prompt is too long and buries
        # the motion instruction, making the 22B distilled output static.
        chars = shot.get("characters_in_frame", [])
        hair = "long flowing hair" if chars else "hair"
        if tier == 1:
            return (
                f"{comp}, anime illustration. The character's {hair} flows and "
                "sways in the wind with soft physics, strands moving gently, "
                "hair drifting naturally. Hair and scarf cloth sway and billow. "
                "Subtle breathing, cinematic lighting."
            )
        cam = shot.get("camera_movement") or "slow push-in"
        return (
            f"{comp}, anime illustration. Hair and clothes flow with the motion, "
            f"hair physics moving naturally in the wind. Camera {cam}. "
            "Stable consistent character and outfit."
        )
    if template == "video_i2v_ltx_2b.json":
        # LTX-2B (default engine): strong, explicit motion verbs. The char-ref +
        # enhanced start frame is heavily identity-conditioned, so weak "subtle
        # ambient" phrasing leaves it static. Explicit head turn / step / wind
        # physics drives scene motion past the gate while the conditioned frame
        # keeps the character on-model (verified: strength 0.55, 81f -> pass).
        cam = shot.get("camera_movement") or "slow dolly in"
        if tier == 1:
            return (
                f"{comp}, anime scene, {light}. The character turns their head and "
                "breathes, hair and coat swaying with soft wind physics, fabric "
                "billowing gently, subtle body motion, stable consistent character "
                "and outfit, cinematic lighting."
            )
        return (
            f"{comp}, anime scene, {light}. The character moves with one clear action, "
            f"hair and clothes flowing with the motion, strong wind physics, camera "
            f"{cam}, dynamic anime motion, stable consistent character and outfit."
        )
    if tier == 1:
        return f"{comp} {base}. {light}. Subtle ambient motion: hair drifts, cloth sways, particles float. Shallow depth of field."
    if tier == 2:
        cam = shot.get("camera_movement") or "slow dolly in"
        return f"{comp} {base}. {light}. Camera {cam}, focused on subject. Dynamic anime scene with natural motion."
    return base


def build_director_timeline(
    image_file: str,
    prompt: str,
    global_prompt: str,
    frames: int,
) -> dict[str, str]:
    """Build the LTXDirector (V2V director) timeline inputs for one shot.

    Mirrors the aether-pipeline-v2 STAGE 3 (V2V Director, LTX Director 2.0)
    timeline format: an empty head text segment, the panel as an image start
    keyframe, the shot's motion prompt as a text beat, and an empty tail.
    Returns a dict of patch values for TIMELINE_DATA / LOCAL_PROMPTS /
    SEGMENT_LENGTHS / GUIDE_STRENGTH."""
    segments = [
        {"id": "s_head", "start": 0, "length": 0, "type": "text", "prompt": "", "isEndFrame": False},
        {"id": "s_img", "start": 0, "length": frames, "type": "image",
         "imageFile": image_file, "isEndFrame": False},
        {"id": "s_txt", "start": 0, "length": frames, "type": "text", "prompt": prompt, "isEndFrame": False},
        {"id": "s_tail", "start": frames, "length": 0, "type": "text", "prompt": "", "isEndFrame": False},
    ]
    timeline = {
        "mainTrackEnabled": True,
        "audioTrackEnabled": False,
        "motionTrackEnabled": False,
        "global_prompt": global_prompt,
        "normalStartFrame": 0,
        "normalDurationFrames": frames,
        "segments": segments,
        "motionSegments": [],
        "audioSegments": [],
    }
    return {
        "TIMELINE_DATA": json.dumps(timeline),
        "LOCAL_PROMPTS": f" | {prompt}\n | ",
        "SEGMENT_LENGTHS": f"0,{frames},0",
        "GUIDE_STRENGTH": "1.0",
    }


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
    enhance_panels: bool = True,
    strength: float = 0.55,
) -> str:
    """Stable cache key: hash of all inputs that affect the rendered clip.

    Includes the panel bytes plus every render-affecting knob (motion prompt,
    template, steps, seed, AI upscale, panel enhance, I2V strength) so tuning
    ``ltx_strength`` / ``enhance_panels`` invalidates stale clips instead of
    silently reusing them."""
    import hashlib
    h = hashlib.sha256()
    h.update(panel.read_bytes())
    h.update(motion_prompt.encode())
    h.update(template.encode())
    h.update(str(steps).encode())
    h.update(str(seed).encode())
    h.update(str(int(ai_upscale)).encode())
    h.update(str(int(enhance_panels)).encode())
    h.update(f"{strength:.4f}".encode())
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


def _enhance_panel(panel: Path, project_dir: Path, sid: str, *, scale: int = 2) -> Path:
    """Real-ESRGAN upscale a source panel 2x before feeding it to the I2V
    model. Under-detailed source panels cause the I2V models (LTX-2B, Wan)
    to distort faces / character design, so a higher-detail input reduces
    that distortion. Returns the enhanced path (falls back to the original
    panel on any failure)."""
    if not realesrgan_upscale.available():
        return panel
    out_dir = project_dir / "clips" / "_enhanced_panels"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sid}_enh.png"
    if out.exists():
        return out
    import subprocess
    try:
        r = subprocess.run(
            [str(realesrgan_upscale._BIN), "-i", str(panel), "-o", str(out),
             "-s", str(scale), "-n", "realesr-animevideov3-x2",
             "-m", str(realesrgan_upscale._MODELS_DIR),
             "-t", "128", "-j", "4:4:2"],
            capture_output=True, timeout=600,
        )
        if r.returncode == 0 and out.exists():
            return out
    except (subprocess.SubprocessError, OSError):
        pass
    logger.warning("panel enhance failed for %s; using original", sid)
    return panel


def _render_end_frame(
    comfy: ComfyClient,
    project_dir: Path,
    start_panel: Path,
    motion_prompt: str,
    sid: str,
    *,
    res: tuple[int, int],
    seed: int,
) -> Path:
    """Generate a high-quality END frame for the Wan 2.2 two-keyframe path.

    Uses the Flux-2-Klein img2img template (panel_i2i_flux_klein.json): the
    START panel is VAE-encoded and used both as the img2img latent (denoise
    0.55) AND as ReferenceLatent conditioning, so characters + background
    stay consistent while the motion prompt advances the moment. Returns the
    path to the saved PNG.
    """
    from PIL import Image, UnidentifiedImageError

    end_dir = project_dir / "clips" / "_end_frames"
    end_dir.mkdir(parents=True, exist_ok=True)
    end_path = end_dir / f"{sid}_end.png"

    # Prep the source (crop to 16:9 + resize) into an img2img latent source.
    # A corrupt / unreadable panel must not crash the whole stage -- fall back
    # to the original panel so the caller can still build a start-only timeline.
    try:
        img = Image.open(start_panel).convert("RGB")
        w, h = img.size
        crop_h = int(w * 9 / 16)
        if crop_h > h:
            crop_w = int(h * 16 / 9)
            left = (w - crop_w) // 2
            img = img.crop((left, 0, left + crop_w, h))
        else:
            top = (h - crop_h) // 2
            img = img.crop((0, top, w, top + crop_h))
        img = img.resize(res, Image.LANCZOS)
        img.save(end_path)
        src = end_path
    except (UnidentifiedImageError, OSError, ValueError):
        logger.warning("END frame panel prep failed for %s; using original panel", sid)
        src = start_panel

    try:
        src_uploaded = comfy.upload_image(src, name=f"anim_{sid}_end_src.png")
        paths = comfy.generate(_END_FRAME_TEMPLATE, {
            "SOURCE_IMAGE": src_uploaded,
            "WIDTH": res[0], "HEIGHT": res[1],
            "PROMPT_POS": motion_prompt,
            "PROMPT_NEG": _WAN_NEG,
            "SEED": seed,
            "STEPS": _END_FRAME_STEPS,
            "CFG": _END_FRAME_CFG,
            "DENOISE": _END_FRAME_DENOISE,
            "SAVE_PREFIX": f"pipeline/{project_dir.name}/end_frames/{sid}",
        }, dest=end_dir)
        return Path(paths[0])
    except (ComfyError, ContingencyStop):
        # Fall back to the prepped (or original) panel if the img2img pass fails
        logger.warning("END frame img2img failed for %s; using source panel", sid)
        return src


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
        consecutive_drift = 0
        for sid in shot_order:
            d = shot_detail[sid]
            orig = d.get("planned_tier", d.get("motion_tier", 1))
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
                # No I2V engine available (weights/gate missing) -> controlled
                # drift fallback. Track consecutive drift so a silent run of
                # degraded shots is surfaced instead of hiding behind "success".
                consecutive_drift += 1
                if consecutive_drift > _MAX_DRIFT_REUSE:
                    logger.warning(
                        "stage3c: %d consecutive drift fallbacks exceed cap %d "
                        "(shot %s) -- likely missing video weights or VRAM",
                        consecutive_drift, _MAX_DRIFT_REUSE, sid,
                    )
                    scores.record("stage3c", "global", "drift_cap_exceeded", 1.0)
                logger.info(
                    "Drift mode active for %s (8GB VRAM safety, fallback): "
                    "%d/%d shots using controlled motion fallback",
                    sid, consecutive_drift, len(shot_order),
                )
                d["motion_tier"] = 0 if d.get("force_drift_fallback", False) else 1
                if s := shots_by_id.get(sid):
                    s["motion_tier"] = d["motion_tier"]
                if d["motion_tier"] == 0:
                    tier0 += 1
                else:
                    tier1 += 1
                failed += 1
                continue

            # Select engine-specific constants
            if ltx_template in ("wan_ti2v.json", "wan_ti2v_2f.json"):
                res = _WAN_RES
                frames = _WAN_FRAMES
                fps = _WAN_FPS
            elif ltx_template == "video_svd.json":
                res = _SVD_RES
                frames = _SVD_FRAMES
                fps = _SVD_FPS
                steps = _SVD_STEPS
            elif ltx_template == _LTX23_8GB_TEMPLATE:
                # LTX-2.3 22B 8GB proven config (permanent engine)
                res = _LTX23_8GB_RES
                frames = _LTX23_8GB_FRAMES
                fps = _LTX23_8GB_FPS
                steps = _LTX23_8GB_STEPS
            else:
                # LTX fallback
                res = _LTX_RES
                frames = _LTX_FRAMES
                fps = _LTX_FPS
                steps = _LTX_STEPS.get(orig, 15)

            clips_dir = project_dir / "clips"
            clips_dir.mkdir(exist_ok=True)
            motion_prompt = _motion_prompt(shots_by_id.get(sid, {}), orig, ltx_template)

            if cache is None:
                cache = _clip_cache_load(clips_dir)
            key = _clip_cache_key(
                panel, motion_prompt, ltx_template, steps, _seed_from_id(sid),
                ai_upscale=config.animation.ai_upscale,
                enhance_panels=getattr(config.animation, "enhance_panels", True),
                strength=getattr(config.animation, "ltx_strength", 0.55),
            )
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
                consecutive_drift = 0  # a real (cached) clip breaks the drift streak
                logger.info("LTX cache hit for %s", sid)
                continue

            try:
                render_panel = panel
                if getattr(config.animation, "enhance_panels", True):
                    render_panel = _enhance_panel(panel, project_dir, sid)
                uploaded = comfy.upload_image(render_panel, name=f"anim_{sid}.png")
                if ltx_template == "video_svd.json":
                    # SVD is prompt-less: no MOTION_PROMPT/PROMPT_NEG patches.
                    patch_set = {
                        "START_FRAME": uploaded,
                        "WIDTH": res[0], "HEIGHT": res[1],
                        "FRAMES": frames, "STEPS": steps,
                        "SEED": _seed_from_id(sid), "FPS": fps,
                        "SVD_MODEL": _SVD_MODEL,
                        "MOTION_BUCKET": _SVD_MOTION_BUCKET,
                        "SAVE_PREFIX": f"pipeline/{project_dir.name}/clips/{sid}",
                    }
                else:
                    patch_set = {
                        "MOTION_PROMPT": motion_prompt,
                        "START_FRAME": uploaded,
                        "WIDTH": res[0], "HEIGHT": res[1],
                        "FRAMES": frames, "STEPS": steps,
                        "SEED": _seed_from_id(sid), "FPS": fps,
                        "SAVE_PREFIX": f"pipeline/{project_dir.name}/clips/{sid}",
                    }
                    if ltx_template == "wan_ti2v.json":
                        # Wan 2.2 TI2V-5B tuning: low CFG + identity-preserving negative
                        patch_set["CFG"] = _WAN_CFG
                        patch_set["PROMPT_NEG"] = _WAN_NEG
                    if ltx_template == _WAN_2F_TEMPLATE:
                        # Two-keyframe path: generate a high-quality END frame from the
                        # START panel via Flux-2-Klein img2img, then inject it at the
                        # end of the latent sequence (latent_index -1).
                        end_path = _render_end_frame(
                            comfy, project_dir, panel, motion_prompt, sid,
                            res=res, seed=_seed_from_id(sid),
                        )
                        end_uploaded = comfy.upload_image(end_path, name=f"anim_{sid}_end.png")
                        patch_set["END_FRAME"] = end_uploaded
                        patch_set["CFG"] = _WAN_CFG
                        patch_set["PROMPT_NEG"] = _WAN_NEG
                    if ltx_template == _LTX23_8GB_TEMPLATE:
                        # LTX-2.3 22B 8GB permanent engine: cfg 1.0 + strength 0.55
                        patch_set["CFG"] = _LTX23_8GB_CFG
                        patch_set["STRENGTH"] = _LTX23_8GB_STRENGTH
                    elif ltx_template == "video_i2v_ltx_2b.json":
                        # LTX-2B identity/motion tradeoff: configurable strength.
                        # Lower pins the start frame harder (less face/design
                        # drift), higher trades identity for motion. The enhanced
                        # start frame (enhance_panels) + lower strength is the
                        # 8GB-friendly antidote to 2B face distortion.
                        patch_set["STRENGTH"] = config.animation.ltx_strength
                paths = comfy.generate(ltx_template, patch_set, dest=clips_dir)
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
                consecutive_drift = 0
                _clip_cache_store(clips_dir, key, clip_path)
            except ComfyError as exc:
                logger.error("LTX I2V render failed for %s: %s, falling back to drift", sid, exc)
                d["motion_tier"] = 0
                failed += 1
    finally:
        gpu_batch.release()

    return tier0, tier1, tier2, tier3, rendered, failed, cache_hits


def _render_director_phase(
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
    """LTX Director (V2V) render phase (GPU). Returns updated counters.

    Uses the ``ltx_director_23.json`` template: the panel is the timeline image
    start keyframe, the shot motion prompt is the text beat, and the LTXDirector
    node composes a directed clip. Same GPU batch, post-process, cache, and
    motion-gate discipline as the I2V phase."""
    template = getattr(config.animation, "ltx_director_workflow", "ltx_director_23.json")
    res = (_DIRECTOR_RES[0], _DIRECTOR_RES[1])
    frames = _DIRECTOR_FRAMES
    fps = _DIRECTOR_FPS
    steps = _DIRECTOR_STEPS
    cfg = _DIRECTOR_CFG

    gpu_batch = GpuBatch("stage3c", comfy)
    if not gpu_batch.acquire():
        logger.error("GPU is owned by another stage - refusing to render LTX Director")
        scores.record("stage3c", "global", "gpu_lock_contention", 1.0)
        return tier0, tier1, tier2, tier3, rendered, failed, cache_hits

    try:
        cache: dict[str, str] | None = None
        consecutive_drift = 0
        for sid in shot_order:
            d = shot_detail[sid]
            orig = d.get("planned_tier", d.get("motion_tier", 1))
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
            shot = shots_by_id.get(sid, {})
            motion_prompt = _motion_prompt(shot, orig, template)
            global_prompt = shot.get("style_global", "anime 2d illustration, cel shading, consistent character and background")

            if cache is None:
                cache = _clip_cache_load(clips_dir)
            key = _clip_cache_key(
                panel, motion_prompt, template, steps, _seed_from_id(sid),
                ai_upscale=config.animation.ai_upscale,
                enhance_panels=getattr(config.animation, "enhance_panels", True),
                strength=getattr(config.animation, "ltx_strength", 0.55),
            )
            cached_rel = cache.get(key)
            cached_clip = (clips_dir / cached_rel) if cached_rel else None
            if cached_clip is not None and cached_clip.exists():
                d["motion_tier"] = orig
                d["clip_path"] = str(cached_clip.relative_to(project_dir))
                d["ltx_template"] = template
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
                consecutive_drift = 0
                logger.info("LTX Director cache hit for %s", sid)
                continue

            try:
                render_panel = panel
                if getattr(config.animation, "enhance_panels", True):
                    render_panel = _enhance_panel(panel, project_dir, sid)
                uploaded = comfy.upload_image(render_panel, name=f"anim_director_{sid}.png")
                timeline = build_director_timeline(uploaded, motion_prompt, global_prompt, frames)
                patch_set = {
                    **timeline,
                    "GLOBAL_PROMPT": global_prompt,
                    "WIDTH": res[0], "HEIGHT": res[1],
                    "FRAMES": frames, "STEPS": steps,
                    "CFG": cfg, "SEED": _seed_from_id(sid), "FPS": fps,
                    "SAVE_PREFIX": f"pipeline/{project_dir.name}/clips/{sid}_director",
                }
                paths = comfy.generate(template, patch_set, dest=clips_dir)
                clip_path = _postprocess_clip(paths[0], skip_ffmpeg=config.animation.ai_upscale)

                motion = verify_clip_motion(clip_path)
                if not motion["motion_verified"]:
                    logger.warning(
                        "LTX Director clip %s motion gate FAILED (axis=%s) -- treating as drift",
                        sid, motion["motion_axis"],
                    )
                    d["motion_tier"] = 0
                    failed += 1
                    clip_path.unlink(missing_ok=True)
                    continue

                d["motion_tier"] = orig
                d["clip_path"] = str(clip_path.relative_to(project_dir))
                d["ltx_template"] = template
                d["motion_verified"] = motion
                d["director_render"] = True
                if s := shots_by_id.get(sid):
                    s["motion_tier"] = orig
                    s["clip_path"] = d["clip_path"]
                    s["motion_verified"] = motion
                if orig == 1:
                    tier1 += 1
                else:
                    tier2 += 1
                rendered += 1
                consecutive_drift = 0
                _clip_cache_store(clips_dir, key, clip_path)
            except ComfyError as exc:
                logger.error("LTX Director render failed for %s: %s, falling back to drift", sid, exc)
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
        orig = d.get("planned_tier", d.get("motion_tier", 1))
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

    # Phase 1: Assign tiers, render Tier 0 (drift, no GPU) - lower default tier
    consecutive_drift = 0
    for i, sid in enumerate(shot_order):
        d = shot_detail[sid]
        # Default to tier 1 (ambient motion) for animation; tier 0 (drift) as VRAM safety fallback
        orig = d.get("planned_tier", d.get("motion_tier", 1))
        if orig == 0:
            # Planned as drift, stays drift -- consistent direction per shot (not ping-pong)
            shot_hash = int(hashlib.sha256(sid.encode()).hexdigest()[:8], 16)
            direction = 1 if (shot_hash % 2 == 0) else -1
            d["drift"] = {"axis": axis, "direction": direction, "pixels": pixels, "consistent": True}
            if s := shots_by_id.get(sid):
                s["motion_tier"] = 0
            tier0 += 1
            consecutive_drift += 1
        elif orig == 1:
            # Tier 1: Ambient motion with LTX I2V
            d["motion_tier"] = 1
            d["drift"] = None
            if s := shots_by_id.get(sid):
                s["motion_tier"] = 1
            tier1 += 1
            consecutive_drift = 0
        elif orig == 2:
            # Tier 2: Director motion with LTX I2V
            d["motion_tier"] = 2
            d["drift"] = None
            if s := shots_by_id.get(sid):
                s["motion_tier"] = 2
            tier2 += 1
            consecutive_drift = 0
        elif orig == 3:
            # Tier 3: Lip-sync motion with LTX I2V
            d["motion_tier"] = 3
            d["drift"] = None
            if s := shots_by_id.get(sid):
                s["motion_tier"] = 3
            tier3 += 1
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
    elif engine == "ltx_director":
        # LTX Director (V2V) path: panel is the timeline image keyframe, the
        # shot motion prompt is the text beat, composed by the LTXDirector node.
        tier0, tier1, tier2, tier3, rendered, failed, cache_hits = _render_director_phase(
            shot_order, shot_detail, shots_by_id, storyboard,
            project_dir, config, comfy, scores,
            tier0, tier1, tier2, tier3, rendered, failed, cache_hits,
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
    planned_animated = sum(1 for d in shot_detail.values() if d.get("planned_tier", d.get("motion_tier")) in (1, 2))
    tier_degraded = sum(1 for d in shot_detail.values() if d.get("planned_tier", d.get("motion_tier")) in (1, 2, 3) and d.get("motion_tier") == 0)
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