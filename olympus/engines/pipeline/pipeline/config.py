"""Pipeline config — reads from the unified stack.toml."""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

STACK_ROOT = Path(__file__).resolve().parents[4]
if str(STACK_ROOT) not in sys.path:
    sys.path.insert(0, str(STACK_ROOT))
from stack.config import cfg as _cfg

ENGINE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ENGINE_ROOT / "pipeline.toml"


class BannedModelError(ValueError):
    """Raised when a banned checkpoint is selected."""


class ModelsConfig(BaseModel):
    llm_script: str = ""
    llm_vision: str = ""
    llm_vision_fallback: str = ""
    llm_review: str = ""
    llm_default: str = ""
    image_primary: str = ""
    image_fallback: str = ""
    image_floor: str = ""
    image_panel: str = ""
    image_character: str = ""
    tts: str = "kokoro"
    animation_primary: str = ""
    banned: list[str] = Field(default_factory=list)


class AutomationConfig(BaseModel):
    auto_approve_blueprint: bool = True
    auto_approve_transform_map: bool = True
    auto_approve_identity: bool = True
    auto_resolve_contradictions: bool = True
    auto_advance_stages: bool = True
    allow_missing_loras: bool = True


class AnimationConfig(BaseModel):
    drift_axis: str = "vertical"
    max_animated_seconds_per_block: float = 60.0
    default_motion_tier: int = 1
    fail_on_repeat: bool = True
    panel_denoise: float = 0.2
    panel_max_attempts: int = 4
    # Fine-tune knobs for panel_i2img_plate_krea2.json (patchable SAMPLER/
    # SCHEDULER/STEPS/CFG/SHARPEN_*). Defaults preserve krea2-Turbo recipe.
    panel_sampler: str = "euler"
    panel_scheduler: str = "simple"
    panel_steps: int = 12
    panel_cfg: float = 1.5
    panel_sharpen_radius: int = 1
    panel_sharpen_sigma: float = 1.0
    panel_sharpen_alpha: float = 0.35

    # ControlNet (pose/composition guidance from reference)
    controlnet_enabled: bool = False
    controlnet_strength: float = 0.8
    controlnet_default_model: str = "control_v11p_sd15_openpose.safetensors"

    # Regional prompting (composable per-region prompt overrides)
    regional_prompt_a_enabled: bool = False
    regional_prompt_a_text: str = ""
    regional_prompt_b_enabled: bool = False
    regional_prompt_b_text: str = ""

    # Style LoRA (per-shot art style variation)
    style_lora_enabled: bool = False
    style_lora_name: str = ""
    style_lora_strength_model: float = 0.7
    style_lora_strength_clip: float = 0.7

    # Character mask (masked compositing for clean character insertion)
    character_mask_enabled: bool = False

    # Color grading / lighting adjustment (per-shot)
    color_grade_enabled: bool = True
    color_temp: int = 6500
    color_saturation: float = 1.0
    color_contrast: float = 1.0
    color_gamma: float = 1.0
    color_lift_r: float = 0.0
    color_lift_g: float = 0.0
    color_lift_b: float = 0.0
    color_gain_r: float = 1.0
    color_gain_g: float = 1.0
    color_gain_b: float = 1.0
    
    # krea2 Identity/Style Reference (M-AP-7) — native IPAdapter identity/style locking
    # Requires krea2-compatible IPAdapter models for 16-channel Qwen-Image latent space
    krea2_ref_enabled: bool = False
    krea2_ref_identity_strength: float = 0.6
    krea2_ref_style_strength: float = 0.4
    krea2_ref_identity_model: str = "krea2_identity_plus.safetensors"
    krea2_ref_style_model: str = "krea2_style_plus.safetensors"
    
    # Real-ESRGAN anime 2x on LTX clips (stage3c post-process)
    ai_upscale: bool = True
    ai_upscale_scale: int = 2
    ai_upscale_model: str = "realesr-animevideov3-x2"

    # Real-ESRGAN 2x on source PANELS before I2V (2026-08-20): under-detailed
    # input panels cause LTX/Wan to distort faces & character design, so a
    # higher-detail input reduces that distortion.
    enhance_panels: bool = True

    # Per-panel character-reference conditioning (stage3b): when a shot's
    # character has a stage1r reference sheet on disk, re-render the panel
    # through panel_ref_flux_klein.json conditioning on the character ref +
    # the base panel, so the character stays on-model (fixes downstream
    # LTX/Wan face + design drift).
    panel_char_ref: bool = True
    panel_char_ref_denoise: float = 0.55
    panel_char_ref_steps: int = 24

    # LTX-2B I2V identity/motion tradeoff. Lower strength pins the start frame
    # harder (less face/design drift) at the cost of motion; higher gives more
    # motion but drifts identity. 0.55 is the verified-passing default.
    ltx_strength: float = 0.55

    # Animation engine selection: "ltx_director" (primary, best quality) |
    # "ltx2b" (LTX-2B I2V fallback) | "hailuo23" | "svd_xt" | "wan22" | "ltx23"
    engine: str = "ltx_director"
    # Hailuo 2.3 i2v (if engine = "hailuo23")
    hailuo_api_endpoint: str = ""
    hailuo_model: str = "i2v-pro"
    hailuo_api_key: str = ""
    # LTX Director 2.3 (if engine = "ltx_director")
    ltx_director_workflow: str = "ltx_director_23.json"

    # LoRA paths (character + style)
    character_lora_dir: str = "models/loras/characters/"
    style_lora: str = "models/loras/anime_style.safetensors"


class PathsConfig(BaseModel):
    projects: str = "projects"
    loras: str = "loras"
    comfyui: str = "../../../ComfyUI"


class AgiConfig(BaseModel):
    """AGI script scorer wiring (from stack.toml ``[agi]``)."""

    enabled: bool = True
    checkpoint_path: str = ""
    device: str = "auto"
    sbert_model: str = "all-MiniLM-L6-v2"
    min_vram_free_mb: int = 3072


class NimConfig(BaseModel):
    """NVIDIA NIM hosted judge (OpenAI-compatible, from stack.toml ``[nim]``).

    ``enabled`` + a resolved API key gate whether the judge uses NIM. The key
    resolution (env var ``NVIDIA_API_KEY``/``NVIDIA_NIM_API_KEY`` then
    ``api_key``) lives in the nim_client; this just carries the configured
    values so stages can build the client.
    """
    enabled: bool = False
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"
    api_key: str = ""
    timeout_seconds: int = 120


class PipelineConfig(BaseModel):
    """Top-level typed view of configuration — bridges legacy code to stack.toml."""

    models: ModelsConfig = Field(default_factory=ModelsConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    animation: AnimationConfig = Field(default_factory=AnimationConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    agi: AgiConfig = Field(default_factory=AgiConfig)
    nim: NimConfig = Field(default_factory=NimConfig)
    num_ctx: int = 16384

    config_path: Path = Field(default=DEFAULT_CONFIG_PATH, exclude=True)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "PipelineConfig":
        if path is not None:
            raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
            cfg = cls.model_validate(raw)
            cfg.config_path = Path(path).resolve()
            return cfg
        return cls(
            models=ModelsConfig(
                llm_script=_cfg.ollama.models.script,
                llm_vision=_cfg.ollama.models.vision,
                llm_vision_fallback=_cfg.ollama.models.vision_fallback,
                llm_review=_cfg.ollama.models.review,
                llm_default=_cfg.ollama.models.default,
                image_primary=_cfg.comfyui.models.primary,
                image_fallback=_cfg.comfyui.models.fallback,
                image_floor=_cfg.comfyui.models.floor,
                image_panel=_cfg.comfyui.models.panel,
                image_character=_cfg.comfyui.models.character,
                tts="kokoro",
                animation_primary=_cfg.comfyui.models.animation_primary,
                banned=_cfg.comfyui.models.banned_checkpoints,
            ),
            automation=AutomationConfig(
                auto_advance_stages=_cfg.automation.auto_advance_stages,
                allow_missing_loras=_cfg.automation.allow_missing_loras,
            ),
            animation=AnimationConfig(
                drift_axis=_cfg.animation.drift_axis,
                max_animated_seconds_per_block=_cfg.animation.max_animated_seconds_per_block,
                default_motion_tier=_cfg.animation.default_motion_tier,
                fail_on_repeat=_cfg.animation.fail_on_repeat,
                panel_denoise=_cfg.animation.panel_denoise,
                panel_max_attempts=getattr(_cfg.animation, "panel_max_attempts", 4),
                panel_sampler=getattr(_cfg.animation, "panel_sampler", "euler"),
                panel_scheduler=getattr(_cfg.animation, "panel_scheduler", "simple"),
                panel_steps=getattr(_cfg.animation, "panel_steps", 8),
                panel_cfg=getattr(_cfg.animation, "panel_cfg", 1.0),
                panel_sharpen_radius=getattr(_cfg.animation, "panel_sharpen_radius", 1),
                panel_sharpen_sigma=getattr(_cfg.animation, "panel_sharpen_sigma", 1.0),
                panel_sharpen_alpha=getattr(_cfg.animation, "panel_sharpen_alpha", 0.35),
                controlnet_enabled=getattr(_cfg.animation, "controlnet_enabled", False),
                controlnet_strength=getattr(_cfg.animation, "controlnet_strength", 0.8),
                controlnet_default_model=getattr(_cfg.animation, "controlnet_default_model", "control_v11p_sd15_openpose.safetensors"),
                krea2_ref_enabled=getattr(_cfg.animation, "krea2_ref_enabled", False),
                krea2_ref_identity_strength=getattr(_cfg.animation, "krea2_ref_identity_strength", 0.6),
                krea2_ref_style_strength=getattr(_cfg.animation, "krea2_ref_style_strength", 0.4),
                krea2_ref_identity_model=getattr(_cfg.animation, "krea2_ref_identity_model", "krea2_identity_plus.safetensors"),
                krea2_ref_style_model=getattr(_cfg.animation, "krea2_ref_style_model", "krea2_style_plus.safetensors"),
                regional_prompt_a_enabled=getattr(_cfg.animation, "regional_prompt_a_enabled", False),
                regional_prompt_a_text=getattr(_cfg.animation, "regional_prompt_a_text", ""),
                regional_prompt_b_enabled=getattr(_cfg.animation, "regional_prompt_b_enabled", False),
                regional_prompt_b_text=getattr(_cfg.animation, "regional_prompt_b_text", ""),
                style_lora_enabled=getattr(_cfg.animation, "style_lora_enabled", False),
                style_lora_name=getattr(_cfg.animation, "style_lora_name", ""),
                style_lora_strength_model=getattr(_cfg.animation, "style_lora_strength_model", 0.7),
                style_lora_strength_clip=getattr(_cfg.animation, "style_lora_strength_clip", 0.7),
                character_mask_enabled=getattr(_cfg.animation, "character_mask_enabled", False),
                color_grade_enabled=getattr(_cfg.animation, "color_grade_enabled", True),
                color_temp=getattr(_cfg.animation, "color_temp", 6500),
                color_saturation=getattr(_cfg.animation, "color_saturation", 1.0),
                color_contrast=getattr(_cfg.animation, "color_contrast", 1.0),
                color_gamma=getattr(_cfg.animation, "color_gamma", 1.0),
                color_lift_r=getattr(_cfg.animation, "color_lift_r", 0.0),
                color_lift_g=getattr(_cfg.animation, "color_lift_g", 0.0),
                color_lift_b=getattr(_cfg.animation, "color_lift_b", 0.0),
                color_gain_r=getattr(_cfg.animation, "color_gain_r", 1.0),
                color_gain_g=getattr(_cfg.animation, "color_gain_g", 1.0),
                color_gain_b=getattr(_cfg.animation, "color_gain_b", 1.0),
                ai_upscale=getattr(_cfg.animation, "ai_upscale", True),
                ai_upscale_scale=getattr(_cfg.animation, "ai_upscale_scale", 2),
                ai_upscale_model=getattr(_cfg.animation, "ai_upscale_model", "realesr-animevideov3-x2"),
                enhance_panels=getattr(_cfg.animation, "enhance_panels", True),
                panel_char_ref=getattr(_cfg.animation, "panel_char_ref", True),
                panel_char_ref_denoise=getattr(_cfg.animation, "panel_char_ref_denoise", 0.55),
                panel_char_ref_steps=getattr(_cfg.animation, "panel_char_ref_steps", 24),
                ltx_strength=getattr(_cfg.animation, "ltx_strength", 0.55),
                engine=getattr(_cfg.animation, "engine", "ltx_director"),
                hailuo_api_endpoint=getattr(_cfg.animation, "hailuo_api_endpoint", ""),
                hailuo_model=getattr(_cfg.animation, "hailuo_model", "i2v-pro"),
                hailuo_api_key=getattr(_cfg.animation, "hailuo_api_key", ""),
                ltx_director_workflow=getattr(_cfg.animation, "ltx_director_workflow", "ltx_director_23.json"),
                character_lora_dir=getattr(_cfg.animation, "character_lora_dir", "models/loras/characters/"),
                style_lora=getattr(_cfg.animation, "style_lora", "models/loras/anime_style.safetensors"),
            ),
            paths=PathsConfig(),
            agi=AgiConfig(
                enabled=_cfg.agi.enabled,
                checkpoint_path=_cfg.agi.checkpoint_path,
                device=_cfg.agi.device,
                sbert_model=_cfg.agi.sbert_model,
                min_vram_free_mb=_cfg.agi.min_vram_free_mb,
            ),
            nim=NimConfig(
                enabled=getattr(_cfg.nim, "enabled", False),
                base_url=getattr(_cfg.nim, "base_url", "https://integrate.api.nvidia.com/v1"),
                model=getattr(_cfg.nim, "model", "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"),
                api_key=getattr(_cfg.nim, "api_key", ""),
                timeout_seconds=getattr(_cfg.nim, "timeout_seconds", 120),
            ),
            num_ctx=getattr(_cfg.ollama, "num_ctx", 16384),
        )

    def resolve_image_model(self, role: str = "primary") -> str:
        mapping = {"primary": self.models.image_primary, "fallback": self.models.image_fallback, "floor": self.models.image_floor, "panel": self.models.image_panel, "character": self.models.image_character}
        if role not in mapping:
            raise ValueError(f"unknown image model role {role!r} (expected primary|fallback|floor|panel|character)")
        name = mapping[role]
        if name in self.models.banned:
            raise BannedModelError(f"image model {name!r} is banned: {self.models.banned}")
        return name

    def _resolve_path(self, raw: str) -> Path:
        p = Path(raw)
        return p if p.is_absolute() else (self.config_path.parent / p).resolve()

    def projects_dir(self) -> Path:
        return self._resolve_path(self.paths.projects)

    def loras_dir(self) -> Path:
        return self._resolve_path(self.paths.loras)

    def comfyui_dir(self) -> Path:
        return self._resolve_path(self.paths.comfyui)
