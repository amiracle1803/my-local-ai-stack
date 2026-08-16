"""Video template router — LTX-2B default primary, Wan2.2 optional tier.

Per user decision (2026-08-12):
  - LTX-2B FP8 is the DEFAULT clip renderer. It is the validated substitute
    for Wan2.2: weights on disk, smoke gate passed, native I2V, and it fits
    the 8 GB card at its production config (768x448, 81 frames).
  - Wan2.2-TI2V-5B Q4_K_M is the optional higher-quality tier. It is only
    selected when an HONEST full-res smoke render passes. On the RTX 4070
    8 GB card the full-res VAE decode OOMs (block-swapped stack stays
    resident), so Wan will not be picked until that is fixed.

Wan2.2 weights verified on disk:
  - Diffusion:  models/diffusion_models/Wan2.2-TI2V-5B-Q4_K_M.gguf (3.4 GB)
  - T5 encoder: models/clip/umt5-xxl-enc-bf16.safetensors (11.4 GB)
  - VAE:        models/vae/Wan2_2_VAE_bf16.safetensors (1.4 GB)
  - ComfyUI-WanVideoWrapper custom node installed
"""
from __future__ import annotations

import logging
from pathlib import Path

from .config import ENGINE_ROOT, PipelineConfig

logger = logging.getLogger(__name__)

# ── Wan2.2 (primary) ──────────────────────────────────────────────────────
_WAN_TEMPLATE = "wan_ti2v.json"
_WAN_MODEL_REL = "models/diffusion_models/Wan2.2-TI2V-5B-Q4_K_M.gguf"
_WAN_T5_REL = "models/text_encoders/umt5-xxl-enc-bf16.safetensors"
_WAN_VAE_REL = "models/vae/Wan2_2_VAE_bf16.safetensors"
_MIN_WAN_MODEL_BYTES = 3_000_000_000
_MIN_WAN_T5_BYTES = 5_000_000_000
_MIN_WAN_VAE_BYTES = 1_000_000_000

# ── LTX-2B (fast draft / fallback) ─────────────────────────────────────────
_LTX_TEMPLATE = "video_i2v_ltx_2b.json"
_LTX2B_UNET_REL = "models/checkpoints/ltxv-2b-0.9.8-distilled-fp8-i2v.safetensors"
_LTX2B_CLIP_REL = "models/clip/t5xxl_fp8_e4m3fn.safetensors"
_MIN_UNET_BYTES = 500_000_000
_MIN_CLIP_BYTES = 100_000_000


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


def pick_ltx_template(config: PipelineConfig, tier: int, frames: int) -> str | None:
    """Resolve the I2V template for one shot.

    Order of preference:
      1. LTX-2B (default primary, validated) — if weights + smoke gate ready
      2. Wan2.2 (optional higher-quality tier) — if weights + smoke gate ready
      3. None (caller must handle — degrade to drift or hard-stop)

    Returns template name, or None if no video engine is available.
    """
    # 1. LTX-2B default primary
    if _ltx2b_weights_ready(config) and _ltx2b_lab_passed():
        return _LTX_TEMPLATE
    logger.warning(
        "video_router: LTX-2B unavailable; checking Wan2.2 tier."
    )

    # 2. Wan2.2 optional tier
    if _wan_weights_ready(config):
        if _wan_lab_passed():
            return _WAN_TEMPLATE
        logger.warning(
            "video_router: Wan2.2 weights present but smoke gate not passed; "
            "no engine selected. Run tools/wan_smoke.py to validate."
        )
    else:
        logger.warning(
            "video_router: Wan2.2 weights incomplete; no engine selected."
        )

    # 3. None available
    logger.error(
        "video_router: no video engine available (LTX-2B and Wan2.2 both unavailable)."
    )
    return None
