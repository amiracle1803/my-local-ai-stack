"""Image template router (design 5.3b + M-AP-7).

krea2 is the mandated ``image_primary`` model, but its weights may still be
mid-download (or wiped). ``pick_template`` is the single choke point every
image stage must call ONCE per run -- it decides whether to route to the
krea2 workflow or the design-permitted flux fallback, so no stage hardcodes
either template name directly.

Anima 1.0 (2026-08-08): anime-tuned checkpoint adopted for PANELS. When its
weights are on disk AND the model_lab anima gate has passed, ``panels`` route
to ``image_txt2img_anima.json`` (plates) / ``panel_i2img_plate_anima.json``
(reference-first img2img from the scene plate) -- same gate convention as
krea2, so a half-downloaded or unvalidated Anima never takes over a stage.

M-AP-7 (2026-08-09): krea2 identity/style reference (``panel_i2img_identity_ref_krea2.json``)
adds native IPAdapter-based character identity and style locking, replacing
the prompt-only ``_count_clause`` trick. Requires krea2-compatible IPAdapter
models (16-channel Qwen-Image latent space) and a separate smoke gate.
"""
from __future__ import annotations

import logging

from .comfy_client import ComfyClient
from .config import PipelineConfig

logger = logging.getLogger(__name__)

# krea2_turbo-Q4_K_S.gguf is ~7.6 GB complete; a partial/in-progress download
# must not be mistaken for usable weights.
_MIN_PRIMARY_BYTES = 7_000_000_000

_KREA2_TEMPLATE = "image_txt2img_krea2.json"
_KREA2_CONTROLNET_TEMPLATE = "image_txt2img_krea2_controlnet.json"
_KREA2_EDIT_TEMPLATE = "image_inpaint_krea2.json"
_PANEL_IMG2IMG_TEMPLATE = "panel_i2img_plate_krea2.json"
# M-AP-7: krea2 identity/style reference panel (requires IPAdapter models)
_PANEL_KREA2_REF_TEMPLATE = "panel_i2img_identity_ref_krea2.json"
_KREA2_WEIGHTS_REL = "models/unet/krea2_turbo-Q4_K_S.gguf"
_FALLBACK_TEMPLATE = "image_txt2img_flux_fallback.json"

# Anima 1.0 (panel model): full safetensors ~4.2 GB + a 1.2 GB text encoder.
_ANIMA_TEMPLATE = "image_txt2img_anima.json"
_ANIMA_PANEL_IMG2IMG = "panel_i2img_plate_anima.json"
_ANIMA_UNET_REL = "models/diffusion_models/anima-base-v1.0.safetensors"
_ANIMA_CLIP_REL = "models/text_encoders/qwen_3_06b_base.safetensors"
_MIN_ANIMA_BYTES = 4_000_000_000
_MIN_ANIMA_CLIP_BYTES = 1_000_000_000

# krea2 model name prefix (config may have full filename like krea2_turbo-Q4_K_S.gguf)
_KREA2_PREFIX = "krea2"
# Anima panel model prefix (config's image_panel role).
_ANIMA_PREFIX = "anima"
# Character sheet model prefix (flux-based for VRAM efficiency)
_CHARACTER_PREFIX = "flux"

# Character sheet flux workflow (flux-2-klein-4b for 8GB VRAM, higher quality)
_CHARACTER_TEMPLATE = "char_ref_character_sheet_flux.json"
_CHARACTER_UNET_REL = "models/unet/flux-2-klein-4b-Q4_K_M.gguf"
_CHARACTER_CLIP1_REL = "models/clip/clip_l.safetensors"
_CHARACTER_CLIP2_REL = "models/clip/t5xxl_fp8_e4m3fn.safetensors"
_CHARACTER_VAE_REL = "models/vae/ae.safetensors"
_MIN_CHARACTER_UNET_BYTES = 5_000_000_000
_MIN_CHARACTER_CLIP_BYTES = 200_000_000
_MIN_CHARACTER_VAE_BYTES = 200_000_000

# model_lab gate marker (design 5.3b: krea2 "must pass the model_lab gate
# before Stage 1R/3B can run at all"). tools/model_smoke.py writes this file
# on a successful krea2 render; until then krea2 routes to the fallback even
# with weights on disk. 2026-08-03 status: PASSING -- smoke render 49.1s with
# qwen3vl_4b_fp8_scaled.safetensors (the earlier 4B text-encoder blocker was
# resolved once the fp8_scaled repack landed).

# M-AP-7: krea2 identity/style reference gate marker
_KREA2_REF_IPADAPTER_IDENTITY_REL = "models/ipadapter/krea2_identity_plus.safetensors"
_KREA2_REF_IPADAPTER_STYLE_REL = "models/ipadapter/krea2_style_plus.safetensors"
_MIN_IPADAPTER_BYTES = 50_000_000  # ~50 MB minimum


def pick_template(config: PipelineConfig, comfy: ComfyClient, role: str = "primary") -> tuple[str, str]:
    """Resolve (template_name, model_name) for one stage run.

    Resolves ``config.resolve_image_model(role)`` -- ``BannedModelError``
    propagates unmodified; ban enforcement stays config's job, not ours.
    Routes to the krea2 template only when krea2 is primary AND its weights
    are fully on disk; otherwise falls back to the permitted flux template.
    """
    model = config.resolve_image_model(role)
    is_krea2 = model.startswith(_KREA2_PREFIX)
    if is_krea2 and _krea2_weights_ready(config) and _krea2_lab_passed():
        return _KREA2_TEMPLATE, model

    fallback = config.resolve_image_model("fallback") if role != "fallback" else model
    if is_krea2:
        logger.warning(
            "image_router: krea2 weights absent/incomplete at %s; using "
            "permitted fallback %s (design 5.3b).",
            config.comfyui_dir() / _KREA2_WEIGHTS_REL, fallback,
        )
    else:
        logger.warning(
            "image_router: no workflow template mapped for model %r; "
            "using permitted fallback %s (design 5.3b).", model, fallback,
        )
    return _FALLBACK_TEMPLATE, fallback
def pick_panel_template(config: PipelineConfig, comfy: ComfyClient) -> tuple[str, str]:
    """Route the per-shot panel generation (reference-first design).

    Candidate paths, resolved in this order:

    1. Anima 1.0 (anime-tuned faces/eyes) ->
    ``panel_i2img_plate_anima.json`` -- the default when the
    ``comfyui.models.panel`` role is an ``anima*`` model and its weights
    are on disk AND the smoke gate passed. Anima is a full diffuser
    checkpoint and supports img2img plate conditioning.
    2. krea2 is a txt2img-only turbo model -- it has no img2img plate-encode
    path and no img2video path. Panels for krea2 therefore use the same
    txt2img workflow as stage 1R character refs
    (``image_txt2img_krea2.json``), with the shot prompt as the only
    conditioning. Character/style consistency relies on the world-bible
    sd_prompt anchors plus per-shot seeds, the same documented fallback
    already used for the flux route.
    3. flux txt2img fallback (``image_txt2img_flux_fallback.json``) -- the
    permitted fallback when neither Anima nor krea2 is available.

    The krea2 identity/style IPAdapter path (``panel_i2img_identity_ref_krea2.json``)
    is img2img-based (plate encode + IPAdapter conditioning) and is also
    incompatible with krea2's txt2img-only capability, so it is not
    selected for krea2 panels.

    Returns ``(template_name, model_name)``.
    """
    model = config.resolve_image_model("panel")
    if model.startswith(_ANIMA_PREFIX):
        if _anima_weights_ready(config) and _anima_lab_passed():
            return _ANIMA_PANEL_IMG2IMG, model
        logger.warning(
            "image_router: anima weights/gate incomplete for %r; falling "
            "back to txt2img.",
            model,
        )
    is_krea2 = model.startswith(_KREA2_PREFIX)
    if is_krea2:
        if _krea2_weights_ready(config) and _krea2_lab_passed():
            logger.info(
                "image_router: krea2 txt2img panel path (krea2 has no img2img "
                "plate-encode path)."
            )
            return _KREA2_TEMPLATE, model
        logger.warning(
            "image_router: krea2 weights/gate incomplete for %r; falling "
            "back to txt2img flux.",
            model,
        )
    return _FALLBACK_TEMPLATE, model

def pick_character_template(config: PipelineConfig, comfy: ComfyClient) -> tuple[str, str]:
    """Route the character sheet generation (design 5.3b + AGENTS.md model table).

    krea2 is the mandated primary and, per the AGENTS.md image-model table, the
    lighter model on the 8GB card (~5GB vs flux ~6GB + T5 text encoder, which
    has crashed on load). When the character role names a krea2 model and its
    weights + smoke gate are ready, route to ``image_txt2img_krea2.json``. The
    flux character-sheet template is only tried when the role names a flux
    model. Falls back to the permitted flux txt2img template.

    Returns ``(template_name, model_name)``.
    """
    model = config.resolve_image_model("character")
    if model.startswith(_KREA2_PREFIX):
        if _krea2_weights_ready(config) and _krea2_lab_passed():
            return _KREA2_TEMPLATE, model
        logger.warning(
            "image_router: krea2 weights/gate incomplete for %r; using fallback.",
            model,
        )
    elif model.startswith(_CHARACTER_PREFIX):
        if _character_weights_ready(config) and _character_lab_passed():
            return _CHARACTER_TEMPLATE, model
        logger.warning(
            "image_router: character flux weights/gate incomplete; using fallback."
        )
    # Fallback to standard flux txt2img
    logger.warning("image_router: character sheet falling back to flux txt2img.")
    return _FALLBACK_TEMPLATE, config.resolve_image_model("fallback")


# ---------------------------------------------------------- weight + gate checks


def _krea2_weights_ready(config: PipelineConfig) -> bool:
    """True iff the krea2 GGUF unet is fully on disk (not a partial download)."""
    path = config.comfyui_dir() / _KREA2_WEIGHTS_REL
    return path.exists() and path.stat().st_size > _MIN_PRIMARY_BYTES


def _krea2_lab_passed() -> bool:
    """True iff tools/model_smoke.py has recorded a passing krea2 render."""
    from .config import ENGINE_ROOT
    return (ENGINE_ROOT / "workflows" / ".krea2_smoke_passed").exists()


def _anima_weights_ready(config: PipelineConfig) -> bool:
    """True iff the Anima diffuser AND its qwen3_06b text encoder are fully
    on disk (not a partial download)."""
    c = config.comfyui_dir()
    unet = c / _ANIMA_UNET_REL
    clip = c / _ANIMA_CLIP_REL
    return (
        unet.exists() and unet.stat().st_size > _MIN_ANIMA_BYTES
        and clip.exists() and clip.stat().st_size > _MIN_ANIMA_CLIP_BYTES
    )


def _anima_lab_passed() -> bool:
    """True iff tools/model_smoke.py has recorded a passing Anima render."""
    from .config import ENGINE_ROOT
    return (ENGINE_ROOT / "workflows" / ".anima_smoke_passed").exists()


# M-AP-7: krea2 identity/style reference helpers


def _krea2_ref_weights_ready(config: PipelineConfig) -> bool:
    """True iff the krea2_ref IPAdapter identity AND style models are fully
    on disk (not a partial download)."""
    c = config.comfyui_dir()
    identity = c / _KREA2_REF_IPADAPTER_IDENTITY_REL
    style = c / _KREA2_REF_IPADAPTER_STYLE_REL
    return (
        identity.exists() and identity.stat().st_size > _MIN_IPADAPTER_BYTES
        and style.exists() and style.stat().st_size > _MIN_IPADAPTER_BYTES
    )


def _krea2_ref_lab_passed() -> bool:
    """True iff tools/model_smoke.py has recorded a passing krea2_ref render."""
    from .config import ENGINE_ROOT
    return (ENGINE_ROOT / "workflows" / ".krea2_ref_smoke_passed").exists()


def _character_weights_ready(config: PipelineConfig) -> bool:
    """True iff the flux character sheet unet, clip encoders, and vae are fully on disk."""
    c = config.comfyui_dir()
    unet = c / _CHARACTER_UNET_REL
    clip1 = c / _CHARACTER_CLIP1_REL
    clip2 = c / _CHARACTER_CLIP2_REL
    vae = c / _CHARACTER_VAE_REL
    return (
        unet.exists() and unet.stat().st_size > _MIN_CHARACTER_UNET_BYTES
        and clip1.exists() and clip1.stat().st_size > _MIN_CHARACTER_CLIP_BYTES
        and clip2.exists() and clip2.stat().st_size > _MIN_CHARACTER_CLIP_BYTES
        and vae.exists() and vae.stat().st_size > _MIN_CHARACTER_VAE_BYTES
    )


def _character_lab_passed() -> bool:
    """True iff tools/model_smoke.py has recorded a passing character sheet render."""
    from .config import ENGINE_ROOT
    return (ENGINE_ROOT / "workflows" / ".character_smoke_passed").exists()
