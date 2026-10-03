"""Stack configuration loader — single source of truth.

All services and scripts import this. Reads ``stack.toml`` from the repo root
and provides typed access to every setting. No more config.json vs olympus.toml
vs pipeline.toml conflicts.

    from stack.config import cfg
    print(cfg.ollama.url)                  # http://127.0.0.1:11434
    print(cfg.kernel.port)                 # 4600
"""

from __future__ import annotations

import tomllib
import os
from pathlib import Path
from typing import Any, Literal

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


ProviderKind = Literal["local", "hosted", "custom"]
ProviderCapability = Literal["llm", "vision", "t2i", "i2i", "i2v", "tts"]


class ProviderDefinition(BaseModel):
    """A capability provider exposed to the dashboard and runtime resolver."""

    display_name: str
    kind: ProviderKind = "custom"
    enabled: bool = True
    experimental: bool = False
    capabilities: list[ProviderCapability] = Field(default_factory=list)
    credential_env: str = ""
    endpoint: str = ""
    models: list[str] = Field(default_factory=list)
    integration_status: str = "registered"  # registered | experimental | unavailable
    billing_note: str = ""
    availability_note: str = ""


class ProviderConfig(BaseModel):
    """Selected provider/model for one pipeline capability."""

    provider: str
    model: str = ""


class ProvidersConfig(BaseModel):
    """Generic provider registry and per-capability selections."""

    llm: ProviderConfig = Field(default_factory=lambda: ProviderConfig(provider="ollama"))
    vision: ProviderConfig = Field(default_factory=lambda: ProviderConfig(provider="ollama"))
    t2i: ProviderConfig = Field(default_factory=lambda: ProviderConfig(provider="comfyui"))
    i2i: ProviderConfig = Field(default_factory=lambda: ProviderConfig(provider="comfyui"))
    i2v: ProviderConfig = Field(default_factory=lambda: ProviderConfig(provider="comfyui"))
    tts: ProviderConfig = Field(default_factory=lambda: ProviderConfig(provider="voice_studio"))
    registry: dict[str, ProviderDefinition] = Field(default_factory=dict)


class VoiceConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5050
    url: str = "http://127.0.0.1:5050"
    engine: str = "chatterbox-turbo"  # chatterbox-turbo | qwen3-tts-0.6b | kokoro | espeak-ng
    default_voice: str = "af_heart"
    default_speed: float = 1.0
    f5_python: str = "/home/amire/Downloads/tts/f5-venv/bin/python"
    f5_model: str = "F5TTS_v1_Base"
    f5_device: str = "cuda"
    chatterbox_python: str = "/home/amire/Downloads/tts/chatterbox-venv/bin/python"
    chatterbox_command: str = ""  # optional isolated-provider executable/script
    chatterbox_model: str = "ResembleAI/chatterbox-turbo"
    kokoro_command: str = ""  # optional isolated-provider executable/script
    qwen3_tts_python: str = ""
    qwen3_tts_command: str = ""
    qwen3_tts_model: str = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    gpu_lock_timeout_seconds: int = 900


class ComfyUIConfig(BaseModel):
    """Local ComfyUI render endpoint."""
    host: str = "127.0.0.1"
    port: int = 8188
    url: str = "http://127.0.0.1:8188"


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


class PathsConfig(BaseModel):
    vault: str = ""
    output_dir: str = ""
    wiki_root: str = ""


class ObsidianConfig(BaseModel):
    """Obsidian Local REST API plugin config.

    The API key is read from the ``OBSIDIAN_API_KEY`` env var (e.g. set in the
    gitignored ``.env``) first, then ``[obsidian] api_key`` in stack.toml --
    never commit a real token to the tracked config.
    """
    url: str = "http://127.0.0.1:27123"
    api_key: str = ""

class GPUConfig(BaseModel):
    name: str = ""
    vram_gb: int = 8


class AutomationConfig(BaseModel):
    """n8n automation plane (docker compose stack, see stack.toml [automation]).

    The compose project lives outside this repo (``compose_dir``); this is a
    registration + lifecycle hook only — nothing n8n-side moves here.
    """
    enabled: bool = False
    kind: str = "docker-compose"
    compose_dir: str = ""
    name: str = "n8n Automation Plane"
    host: str = "127.0.0.1"
    port: int = 5679
    url: str = "http://127.0.0.1:5679"
    healthcheck: str = "http://127.0.0.1:5679/healthz"
    containers: list[str] = Field(default_factory=list)
    vault_mount: str = ""
    notes: str = ""


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
    model: str = "meta/llama-3.2-11b-vision-instruct"
    api_key: str = ""
    # Long NIM timeout so slow reasoning text models (deepseek-v4-pro ~110s
    # on big world-inference prompts) finish instead of tripping local fallback.
    timeout_seconds: int = 600
    # Generation engine: "local" (Ollama + ComfyUI) or "nvidia" (offload).
    # When "nvidia", the heavy LLM / vision / image work is routed to the free
    # NVIDIA Build API and the local 8GB card stays free for ComfyUI.
    engine: str = "local"
    offload_llm: bool = False
    offload_vision: bool = False
    offload_images: bool = False
    # Verified working NIM text models (fast+reliable for JSON+prose).
    text_model: str = "deepseek-ai/deepseek-v4-pro-0813"
    # Verified working NIM vision models for panel QC.
    vision_model: str = "meta/llama-3.2-11b-vision-instruct"
    image_model: str = "google/diffusiongemma-26b-a4b-it"
# Verified 2026-09-05 by tools/nvidia_probe.py — only models that
    # successfully responded on free-tier NIM without 529 rate-limit errors.
    models: list[str] = Field(default_factory=lambda: [
        "deepseek-ai/deepseek-v4-pro-0813",
        "meta/llama-3.2-11b-vision-instruct",
    ])


class FallbackConfig(BaseModel):
    """Per-capability local-first fallback policy."""

    llm: str = "local_then_nim"
    vision: str = "local_then_nim"
    t2i: str = "local_only"
    i2i: str = "local_only"
    i2v: str = "local_only"
    tts: str = "local_only"
    max_retries: int = 1
    log_path: str = "logs/provider_fallbacks.jsonl"


class AnimationConfig(BaseModel):
    """Studio animation master switch (persisted, not localStorage)."""

    enabled: bool = False  # OFF = panels mode (Ken Burns); ON = GPU clips
    engine: str = "svd"    # svd | ltx_director (LTX-2.3 Q6_K, needs ~18GB VRAM host)


# ── top-level config ───────────────────────────────────────────────────────

class StackConfig(BaseModel):
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    kernel: KernelConfig = Field(default_factory=KernelConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    webui: WebUIConfig = Field(default_factory=WebUIConfig)
    llamacpp: LlamaCppConfig = Field(default_factory=LlamaCppConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    gpu: GPUConfig = Field(default_factory=GPUConfig)
    obsidian: ObsidianConfig = Field(default_factory=ObsidianConfig)
    nim: NIMConfig = Field(default_factory=NIMConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    fallback: FallbackConfig = Field(default_factory=FallbackConfig)
    animation: AnimationConfig = Field(default_factory=AnimationConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)

    config_path: Path = Field(default=CONFIG_PATH, exclude=True)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "StackConfig":
        path = Path(path) if path else CONFIG_PATH
        if not path.exists():
            raise FileNotFoundError(f"stack.toml not found: {path}")
        with path.open("rb") as f:
            raw = tomllib.load(f)
        cfg = cls.model_validate(raw)
        # Resolve the Obsidian token from env (gitignored .env) before the
        # (empty) toml value; never keep the real token in tracked config.
        if not cfg.obsidian.api_key:
            env_key = os.environ.get("OBSIDIAN_API_KEY", "")
            if env_key:
                cfg.obsidian.api_key = env_key
        # Same rule for NIM: env first, then the untracked
        # .agent-secrets/nvidia_invoke_key file, then the toml value.
        if not cfg.nim.api_key:
            env_key = os.environ.get("NVIDIA_API_KEY", "") or os.environ.get(
                "NVIDIA_NIM_API_KEY", "")
            if not env_key:
                try:
                    env_key = (STACK_ROOT / ".agent-secrets"
                               / "nvidia_invoke_key").read_text().strip()
                except OSError:
                    env_key = ""
            if env_key:
                cfg.nim.api_key = env_key
        return cfg


# ── singleton ──────────────────────────────────────────────────────────────

_cfg: StackConfig | None = None


def load_config(path: str | Path | None = None) -> StackConfig:
    global _cfg
    if _cfg is None:
        _cfg = StackConfig.load(path)
    return _cfg


def reload_config(path: str | Path | None = None) -> StackConfig:
    global _cfg, cfg
    _cfg = StackConfig.load(path)
    cfg = _cfg
    return _cfg


# Convenience alias for existing code
cfg = load_config()
