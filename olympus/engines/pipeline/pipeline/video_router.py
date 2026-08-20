"""Video template router — LTX-2B default primary, LTX-2.3 tiled tier-2, Wan2.2 optional.

Per user decision (2026-08-12):
  - LTX-2B FP8 is the DEFAULT clip renderer. Validated substitute for Wan2.2:
    weights on disk, smoke gate passed, native I2V, fits 8 GB at production
    config (768x448, 81 frames).
  - LTX-2.3 22B tiled is the TIER-2 director path. Selected when weights +
    smoke gate are ready AND (tier >= 2 OR frames > 81). The tiled VAE decode
    avoids OOMs at full resolution.
  - Wan2.2-TI2V-5B Q4_K_M is the optional higher-quality tier. Only selected
    when an HONEST full-res smoke render passes. On RTX 4070 8 GB the
    full-res VAE decode OOMs (block-swapped stack stays resident), so Wan
    will not be picked until that is fixed.

LTX-2.3 weights verified on disk:
  - Diffusion:  models/unet/ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf
  - CLIP1:      models/text_encoders/gemma-3-12b-it-qat-UD-Q3_K_XL.gguf
  - CLIP2:      models/text_encoders/ltx-2.3_text_projection_bf16.safetensors
  - VAE:        models/vae/ltx/LTX23_video_vae_bf16.safetensors
"""
from __future__ import annotations

import logging
from pathlib import Path

from .config import ENGINE_ROOT, PipelineConfig

logger = logging.getLogger(__name__)

# ── LTX-2B (default primary, validated) ───────────────────────────────────────
_DEFAULT_TEMPLATE = "video_i2v_ltx_2b.json"
_LTX2B_UNET_REL = "models/checkpoints/ltxv-2b-0.9.8-distilled-fp8-i2v.safetensors"
_LTX2B_CLIP_REL = "models/clip/t5xxl_fp8_e4m3fn.safetensors"
_MIN_UNET_BYTES = 500_000_000
_MIN_CLIP_BYTES = 100_000_000

# ── LTX-2.3 tiled (tier-2 director) ───────────────────────────────────────────
_TIER2 = 2
_TILED_TEMPLATE = "video_i2v_ltx_23b_tiled.json"
_LTX23_UNET_REL = "models/unet/ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf"
_LTX23_CLIP1_REL = "models/text_encoders/gemma-3-12b-it-qat-UD-Q3_K_XL.gguf"
_LTX23_CLIP2_REL = "models/text_encoders/ltx-2.3_text_projection_bf16.safetensors"
_LTX23_VAE_REL = "models/vae/ltx/LTX23_video_vae_bf16.safetensors"
_MIN_LTX23_UNET_BYTES = 2_000_000_000
_MIN_LTX23_CLIP_BYTES = 100_000_000
_MIN_LTX23_VAE_BYTES = 100_000_000

# ── Wan2.2 (optional tier-3) ──────────────────────────────────────────────────
_WAN_TEMPLATE = "wan_ti2v.json"
_WAN_MODEL_REL = "models/diffusion_models/Wan2.2-TI2V-5B-Q4_K_M.gguf"
_WAN_T5_REL = "models/text_encoders/umt5-xxl-enc-bf16.safetensors"
_WAN_VAE_REL = "models/vae/Wan2_2_VAE_bf16.safetensors"
_MIN_WAN_MODEL_BYTES = 3_000_000_000
_MIN_WAN_T5_BYTES = 5_000_000_000
_MIN_WAN_VAE_BYTES = 1_000_000_000


def _ltx2b_weights_ready(config: PipelineConfig) -> bool:
    """True iff the ltx2b unet + clip are fully on disk."""
    c = config.comfyui_dir()
    unet = c / _LTX2B_UNET_REL
    clip = c / _LTX2B_CLIP_REL
    return (
        unet.exists() and unet.stat().st_size > _MIN_UNET_BYTES
        and clip.exists() and clip.stat().st_size > _MIN_CLIP_BYTES
    )


def _ltx2b_lab_passed() -> bool:
    """True iff tools/ltx_smoke.py has recorded a passing ltx2b render."""
    return (ENGINE_ROOT / "workflows" / ".ltx_smoke_passed").exists()


def _ltx23_weights_ready(config: PipelineConfig) -> bool:
    """True iff the ltx23 unet + both clips + vae are fully on disk."""
    c = config.comfyui_dir()
    unet = c / _LTX23_UNET_REL
    clip1 = c / _LTX23_CLIP1_REL
    clip2 = c / _LTX23_CLIP2_REL
    vae = c / _LTX23_VAE_REL
    return (
        unet.exists() and unet.stat().st_size > _MIN_LTX23_UNET_BYTES
        and clip1.exists() and clip1.stat().st_size > _MIN_LTX23_CLIP_BYTES
        and clip2.exists() and clip2.stat().st_size > _MIN_LTX23_CLIP_BYTES
        and vae.exists() and vae.stat().st_size > _MIN_LTX23_VAE_BYTES
    )


def _ltx23_lab_passed() -> bool:
    """True iff tools/ltx_smoke.py has recorded a passing ltx23 tiled render."""
    return (ENGINE_ROOT / "workflows" / ".ltx23_smoke_passed").exists()


def _wan_weights_ready(config: PipelineConfig) -> bool:
    """True iff Wan2.2 model, T5 encoder, and VAE are fully on disk."""
    c = config.comfyui_dir()
    model = c / _WAN_MODEL_REL
    t5 = c / _WAN_T5_REL
    vae = c / _WAN_VAE_REL
    return (
        model.exists() and model.stat().st_size > _MIN_WAN_MODEL_BYTES
        and t5.exists() and t5.stat().st_size > _MIN_WAN_T5_BYTES
        and vae.exists() and vae.stat().st_size > _MIN_WAN_VAE_BYTES
    )


def _wan_lab_passed() -> bool:
    """True iff tools/wan_smoke.py has recorded a passing Wan2.2 render."""
    return (ENGINE_ROOT / "workflows" / ".wan_smoke_passed").exists()


# ── SVD (Stable Video Diffusion, ComfyUI-native, 8GB-friendly) ────────────────
_SVD_TEMPLATE = "video_svd.json"
_SVD_XT_REL = "models/checkpoints/svd_xt-fp16.safetensors"
_MIN_SVD_BYTES = 3_000_000_000


def _svd_weights_ready(config: PipelineConfig) -> bool:
    """True iff the SVD-XT fp16 checkpoint is on disk."""
    ckpt = config.comfyui_dir() / _SVD_XT_REL
    return ckpt.exists() and ckpt.stat().st_size > _MIN_SVD_BYTES


def pick_ltx_template(config: PipelineConfig, tier: int, frames: int) -> str | None:
    """Resolve the I2V template for one shot.

    Priority:
      1. LTX-2.3 tiled (tier-2) — if weights + gate ready AND (tier >= 2 OR frames > 81)
      2. LTX-2B (default primary) — if weights + gate ready
      3. None — caller must handle (degrade to drift or hard-stop)

    Wan2.2 is NOT returned here; stage3c_animation.py:357 still checks
    ltx_template == "wan_ti2v.json" for its own Wan path.

    Returns template name, or None if no video engine is available.
    """
    engine = getattr(config.animation, "engine", "ltx2b")

    # Engine override (user-configurable): force SVD XT, Wan2.2, or LTX-2.3.
    if engine == "svd_xt":
        if _svd_weights_ready(config):
            return _SVD_TEMPLATE
        logger.error("video_router: engine=svd_xt but svd_xt-fp16.safetensors not on disk.")
        return None
    if engine == "ltx23":
        if _ltx23_weights_ready(config):
            # Proven working non-tiled LTX-2.3 template (tiled VAE decode).
            # The legacy _TILED_TEMPLATE (LTXVTiledSampler) crashes with the
            # v3 ComfyUI core (NoneType shape) — see wan22-checkpoint.
            return "video_i2v_ltx_23b_8gb.json"
        logger.error("video_router: engine=ltx23 but LTX-2.3 weights not on disk.")
        return None
    if engine == "wan22":
        if _wan_weights_ready(config):
            return _WAN_TEMPLATE
        logger.error("video_router: engine=wan22 but Wan2.2 weights not on disk.")
        return None
    if engine == "wan22_2f":
        if _wan_weights_ready(config):
            return "wan_ti2v_2f.json"
        logger.error("video_router: engine=wan22_2f but Wan2.2 weights not on disk.")
        return None

    # 1. LTX-2.3 tiled for director shots or long clips
    if _ltx23_weights_ready(config) and _ltx23_lab_passed():
        if tier >= _TIER2 or frames > 81:
            return _TILED_TEMPLATE

    # 2. LTX-2B default primary
    if _ltx2b_weights_ready(config) and _ltx2b_lab_passed():
        return _DEFAULT_TEMPLATE

    # 3. Wan2.2 optional tier (not returned here — see docstring)
    if _wan_weights_ready(config):
        if _wan_lab_passed():
            logger.warning(
                "video_router: Wan2.2 passed smoke but ltx path taken; "
                "stage3c will check wan_ti2v.json separately."
            )
        else:
            logger.warning(
                "video_router: Wan2.2 weights present but smoke gate not passed; "
                "no engine selected. Run tools/wan_smoke.py to validate."
            )
    else:
        logger.warning(
            "video_router: Wan2.2 weights incomplete; no engine selected."
        )

    # 4. None available
    logger.error(
        "video_router: no video engine available (LTX-2B and LTX-2.3 both unavailable)."
    )
    return None