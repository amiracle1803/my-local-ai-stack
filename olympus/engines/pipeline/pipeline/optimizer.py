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
    offload: Literal["none", "cpu", "novram", "block_swap", "lowvram"] = "none"
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
            StageProfile(stage="stage3b", engine="comfyui", model="flux-2-klein-4b-Q4_K_M.gguf",
                         variant="default-panel", width=832, height=512, steps=16,
                         expected_vram_gb=6.0, offload="lowvram", requires_smoke_marker=True,
                         notes="Flux.2 Klein 4B high-detail default; Anima/Krea remain experimental."),
            StageProfile(stage="stage3c", engine="comfyui",
                         model="ltxv-2b-0.9.8-distilled-fp8-i2v.safetensors",
                         variant="optional-ltx2b", width=768, height=448, steps=8,
                         expected_vram_gb=7.0, offload="block_swap", enabled=False,
                         requires_smoke_marker=True),
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
