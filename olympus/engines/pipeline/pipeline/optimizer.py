"""Hardware-aware stage profiles and preflight decisions."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class StageProfile(BaseModel):
    stage: str
    engine: Literal["ollama", "comfyui", "voice", "ffmpeg", "local"]
    model: str
    variant: str = "default"
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    expected_vram_gb: float = 0.0
    offload: Literal["none", "cpu", "novram", "block_swap", "lowvram", "dynamic"] = "none"
    enabled: bool = True
    requires_smoke_marker: bool = False
    notes: str = ""


class PreflightDecision(BaseModel):
    profile: StageProfile
    available_vram_gb: float | None = None
    accepted: bool
    reason: str
    smoke_marker: str | None = None


class HardwareOptimizer(BaseModel):
    """Deterministic profile selector for the 8 GB laptop target."""

    vram_gb: float = 8.0
    smoke_width: int = 512
    smoke_height: int = 288
    profiles: list[StageProfile] = Field(default_factory=list)

    @classmethod
    def default(cls) -> "HardwareOptimizer":
        """Stage records for the manifest. GPU stages describe the active [render] profile;
        ComfyUI's DynamicVRAM streams whatever doesn't fit in 8 GB from system RAM."""
        from .comfy_client import render_profile
        rp = render_profile()
        video_model = rp.video_unet or rp.video_ckpt
        return cls(profiles=[
            StageProfile(stage="stage0", engine="ollama", model="qwen3:8b", offload="cpu"),
            StageProfile(stage="stage0_dossier", engine="ollama", model="qwen2.5vl:7b", offload="cpu"),
            StageProfile(stage="stage1", engine="ollama", model="qwen3:8b", offload="cpu"),
            StageProfile(stage="stage1_world", engine="ollama", model="qwen3:8b", offload="cpu"),
            StageProfile(stage="stage2", engine="ollama", model="qwen3:8b", offload="cpu"),
            StageProfile(stage="stage4", engine="voice", model="auto", offload="cpu"),
            StageProfile(stage="stage3", engine="ollama", model="qwen3:8b", offload="cpu"),
            StageProfile(stage="stage1r", engine="comfyui", model="anima-base-v1.0",
                         variant="vnccs-anima", width=512, height=512, steps=8,
                         expected_vram_gb=5.0, offload="novram", requires_smoke_marker=True),
            StageProfile(stage="stage3b", engine="comfyui", model=rp.panel_unet,
                         variant="default-panel", width=rp.panel_width, height=rp.panel_height,
                         steps=rp.panel_steps, expected_vram_gb=6.0, offload="dynamic",
                         requires_smoke_marker=True,
                         notes=f"text encoder {rp.panel_clip}; upscale {rp.panel_upscale or 'none'}"),
            StageProfile(stage="stage3c", engine="comfyui", model=video_model,
                         variant="ltx", width=rp.video_width, height=rp.video_height, steps=8,
                         expected_vram_gb=7.0, offload="dynamic", enabled=False,
                         requires_smoke_marker=True,
                         notes=f"latent upscale {rp.video_upscale or 'none'}; clips <= {rp.max_clip_seconds}s"),
            StageProfile(stage="stage_vlm_review", engine="ollama", model="qwen2.5vl:7b", offload="cpu"),
            StageProfile(stage="stage5", engine="ffmpeg", model="libx264", offload="cpu"),
        ])

    def profile_for(self, stage: str) -> StageProfile:
        for profile in self.profiles:
            if profile.stage == stage:
                return profile
        raise KeyError(f"no optimizer profile for {stage!r}")

    def decide(self, stage: str, project_dir: str | Path | None = None,
               available_vram_gb: float | None = None) -> PreflightDecision:
        profile = self.profile_for(stage)
        if not profile.enabled:
            return PreflightDecision(profile=profile, available_vram_gb=available_vram_gb,
                                     accepted=False, reason="profile disabled")
        if profile.expected_vram_gb > self.vram_gb:
            return PreflightDecision(profile=profile, available_vram_gb=available_vram_gb,
                                     accepted=False, reason="profile exceeds configured VRAM budget")
        if available_vram_gb is not None and profile.expected_vram_gb > available_vram_gb:
            return PreflightDecision(profile=profile, available_vram_gb=available_vram_gb,
                                     accepted=False, reason="insufficient free VRAM")
        marker = None
        if project_dir is not None:
            marker_path = Path(project_dir) / "optimizer" / f"{stage}_{profile.variant}.json"
            marker = str(marker_path)
            if profile.requires_smoke_marker and not marker_path.exists():
                return PreflightDecision(profile=profile, available_vram_gb=available_vram_gb,
                                         accepted=False, reason="validated smoke marker missing",
                                         smoke_marker=marker)
        return PreflightDecision(profile=profile, available_vram_gb=available_vram_gb,
                                 accepted=True, reason="profile accepted", smoke_marker=marker)

    def write_manifest(self, project_dir: str | Path) -> Path:
        path = Path(project_dir) / "optimizer" / "profile_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"vram_gb": self.vram_gb,
                                    "profiles": [p.model_dump() for p in self.profiles]},
                                   indent=2), encoding="utf-8")
        return path


def free_vram_gb() -> float | None:
    """Return free NVIDIA VRAM when nvidia-smi is available, else ``None``."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL,
        )
        return float(out.splitlines()[0].strip()) / 1024.0
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None
