"""Image template router (design 5.3b).

krea2 is the mandated ``image_primary`` model, but its weights may still be
mid-download (or wiped). ``pick_template`` is the single choke point every
image stage must call ONCE per run -- it decides whether to route to the
krea2 workflow or the design-permitted flux fallback, so no stage hardcodes
either template name directly.
"""

from __future__ import annotations

import logging

from .comfy_client import ComfyClient
from .config import PipelineConfig

logger = logging.getLogger(__name__)

# krea2_turbo-Q4_K_S.gguf is ~7.6 GB complete; a partial/in-progress download
# must not be mistaken for usable weights.
_MIN_PRIMARY_BYTES = 7_000_000_000

_KREA2_TEMPLATE = "image_krea2.json"
_KREA2_WEIGHTS_REL = "models/unet/krea2_turbo-Q4_K_S.gguf"
_FALLBACK_TEMPLATE = "image_flux_fallback.json"

# model_lab gate marker (design 5.3b: krea2 "must pass the model_lab gate
# before Stage 1R/3B can run at all"). tools/model_smoke.py writes this file
# on a successful krea2 render; until then krea2 routes to the fallback even
# with weights on disk. 2026-07-11 status: weights + VAE OK, but the required
# Qwen3-VL-4B 'fp8_scaled' text encoder has no published repack (4B GGUF is
# not llama.cpp-layout; the 8B encoder's width is rejected by the sampler),
# so the gate cannot pass yet -- hard-stop + report, never a banned substitute.


def pick_template(config: PipelineConfig, comfy: ComfyClient) -> tuple[str, str]:
    """Resolve (template_name, model_name) for one stage run.

    Resolves ``config.resolve_image_model("primary")`` -- ``BannedModelError``
    propagates unmodified; ban enforcement stays config's job, not ours.
    Routes to the krea2 template only when krea2 is primary AND its weights
    are fully on disk; otherwise falls back to the permitted flux template.
    """
    primary = config.resolve_image_model("primary")
    if primary == "krea2" and _krea2_weights_ready(config) and _krea2_lab_passed():
        return _KREA2_TEMPLATE, primary

    fallback = config.resolve_image_model("fallback")
    if primary == "krea2":
        logger.warning(
            "image_router: krea2 weights absent/incomplete at %s; using "
            "permitted fallback %s (design 5.3b).",
            config.comfyui_dir() / _KREA2_WEIGHTS_REL, fallback,
        )
    else:
        logger.warning(
            "image_router: no workflow template mapped for primary model %r; "
            "using permitted fallback %s (design 5.3b).", primary, fallback,
        )
    return _FALLBACK_TEMPLATE, fallback


def _krea2_weights_ready(config: PipelineConfig) -> bool:
    """True iff the krea2 GGUF unet is fully on disk (not a partial download)."""
    path = config.comfyui_dir() / _KREA2_WEIGHTS_REL
    return path.exists() and path.stat().st_size > _MIN_PRIMARY_BYTES


def _krea2_lab_passed() -> bool:
    """True iff tools/model_smoke.py has recorded a passing krea2 render."""
    from .config import ENGINE_ROOT

    return (ENGINE_ROOT / "workflows" / ".krea2_smoke_passed").exists()
