"""Stack configuration loader — single source of truth.

All services and scripts import this. Reads ``stack.toml`` from the repo root
and provides typed access to every setting. No more config.json vs olympus.toml
vs pipeline.toml conflicts.

    from stack.config import cfg
    print(cfg.ollama.url)                  # http://127.0.0.1:11434
    print(cfg.kernel.port)                 # 4600
    print(cfg.comfyui.models.primary)      # krea2_turbo-Q4_K_S.gguf
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

STACK_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = STACK_ROOT / "stack.toml"


# ── sub-models ─────────────────────────────────────────────────────────────

class OllamaModels(BaseModel):
    script: str = "qwen3:8b"
    vision: str = "qwen2.5vl:7b"
    vision_fallback: str = "qwen3-vl:4b-instruct-q8_0"
    review: str = "qwen2.5vl:7b"
    default: str = "qwen3:8b"
    embed: str = "nomic-embed-text"


class OllamaAgentRoles(BaseModel):
    triage: str = "llama3.2:3b"
    worker: str = "qwen3:8b"
    planner: str = "qwen3:8b"
    verifier: str = "llama3.2:3b"
    jarvis: str = "qwen3:8b"


class OllamaConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 11434
    url: str = "http://127.0.0.1:11434"
    timeout_seconds: int = 300
    num_ctx: int = 16384
    models: OllamaModels = Field(default_factory=OllamaModels)
    agents: OllamaAgentRoles = Field(default_factory=OllamaAgentRoles)


class ComfyUIModels(BaseModel):
    primary: str = "krea2_turbo-Q4_K_S.gguf"
    fallback: str = "flux-2-klein-4b-Q4_K_M.gguf"
    floor: str = "flux-2-klein-4b-Q4_K_M.gguf"
    animation_primary: str = "ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf"
    panel: str = "anima-base-v1.0.safetensors"
    character: str = "flux-2-klein-4b-Q4_K_M.gguf"
    banned_checkpoints: list[str] = Field(default_factory=list)


class ComfyUIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8188
    url: str = "http://127.0.0.1:8188"
    models: ComfyUIModels = Field(default_factory=ComfyUIModels)


class VoiceConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5050
    url: str = "http://127.0.0.1:5050"


class KernelConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 4600
    url: str = "http://127.0.0.1:4600"
    core_agents: list[str] = Field(default_factory=list)


class MCPConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4720


class WebUIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    url: str = "http://127.0.0.1:8080"


class LlamaCppConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8081
    enabled: bool = False


class PipelineAnimationConfig(BaseModel):
    drift_axis: str = "vertical"
    max_animated_seconds_per_block: float = 60.0
    default_motion_tier: int = 1
    fail_on_repeat: bool = True
    panel_denoise: float = 0.2
    # Fine-tune knobs exposed into panel_img2img_plate_krea.json (design 5.3b).
    # These land as patchable SAMPLER/SCHEDULER/STEPS/CFG/SHARPEN_* fields so
    # the user can tune the redraw + detail pass from stack.toml without
    # editing JSON. Defaults preserve the validated krea2-Turbo recipe.
    panel_sampler: str = "euler"
    panel_scheduler: str = "simple"
    panel_steps: int = 8
    panel_cfg: float = 1.0
    panel_sharpen_radius: int = 1
    panel_sharpen_sigma: float = 1.0
    panel_sharpen_alpha: float = 0.35
    
    # ControlNet (pose/composition guidance from reference)
    controlnet_enabled: bool = False
    controlnet_strength: float = 0.8
    controlnet_default_model: str = "control_v11p_sd15_openpose.safetensors"
    
    # krea2 Identity/Style Reference (M-AP-7) — native IPAdapter identity/style locking
    # Requires krea2-compatible IPAdapter models for 16-channel Qwen-Image latent space
    krea2_ref_enabled: bool = False
    krea2_ref_identity_strength: float = 0.6
    krea2_ref_style_strength: float = 0.4
    krea2_ref_identity_model: str = "krea2_identity_plus.safetensors"
    krea2_ref_style_model: str = "krea2_style_plus.safetensors"
    
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
    
    # Real-ESRGAN anime 2x on LTX clips (stage3c post-process)
    ai_upscale: bool = True
    ai_upscale_scale: int = 2
    ai_upscale_model: str = "realesr-animevideov3-x2"

    # Animation engine selection: "ltx_director" (primary) | "ltx2b" | "hailuo23"
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


class PipelineAutomationConfig(BaseModel):
    auto_approve_blueprint: bool = True
    auto_advance_stages: bool = True
    allow_missing_loras: bool = True


class AgiConfig(BaseModel):
    """AGI script scorer — relationship scoring on top of Ollama script work."""

    enabled: bool = True
    checkpoint_path: str = "olympus/engines/pipeline/models/agi_checkpoint_v3_fixed_best.pt"
    device: str = "auto"
    sbert_model: str = "all-MiniLM-L6-v2"
    min_vram_free_mb: int = 3072


class PathsConfig(BaseModel):
    vault: str = ""
    output_dir: str = ""
    wiki_root: str = ""


class ObsidianConfig(BaseModel):
    url: str = "http://127.0.0.1:27123"
    api_key: str = ""

class GPUConfig(BaseModel):
    name: str = ""
    vram_gb: int = 8


class NIMConfig(BaseModel):
    """NVIDIA NIM (hosted, OpenAI-compatible) judge configuration.

    Used as the primary output-quality judge (panel vision QC + clip review),
    with the local Ollama models kept on standby as automatic fallback. The
    API key is read from the ``NVIDIA_API_KEY`` / ``NVIDIA_NIM_API_KEY`` env
    var first, then ``[nim] api_key`` in stack.toml -- never committed to a
    tracked secret store.
    """
    enabled: bool = False
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"
    api_key: str = ""
    timeout_seconds: int = 120


# ── top-level config ───────────────────────────────────────────────────────

class StackConfig(BaseModel):
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    kernel: KernelConfig = Field(default_factory=KernelConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    webui: WebUIConfig = Field(default_factory=WebUIConfig)
    llamacpp: LlamaCppConfig = Field(default_factory=LlamaCppConfig)
    animation: PipelineAnimationConfig = Field(default_factory=PipelineAnimationConfig)
    automation: PipelineAutomationConfig = Field(default_factory=PipelineAutomationConfig)
    agi: AgiConfig = Field(default_factory=AgiConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    gpu: GPUConfig = Field(default_factory=GPUConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    nim: NIMConfig = Field(default_factory=NIMConfig)

    config_path: Path = Field(default=CONFIG_PATH, exclude=True)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "StackConfig":
        path = Path(path) if path else CONFIG_PATH
        if not path.exists():
            raise FileNotFoundError(f"stack.toml not found: {path}")
        with path.open("rb") as f:
            raw = tomllib.load(f)
        return cls.model_validate(raw)

    def banned_checkpoints(self) -> list[str]:
        return self.comfyui.models.banned_checkpoints

    def is_banned(self, checkpoint: str) -> bool:
        return checkpoint in self.comfyui.models.banned_checkpoints


# ── singleton ──────────────────────────────────────────────────────────────

_cfg: StackConfig | None = None


def load_config(path: str | Path | None = None) -> StackConfig:
    global _cfg
    if _cfg is None:
        _cfg = StackConfig.load(path)
    return _cfg


def reload_config(path: str | Path | None = None) -> StackConfig:
    global _cfg
    _cfg = StackConfig.load(path)
    return _cfg


# Convenience alias for existing code
cfg = load_config()
