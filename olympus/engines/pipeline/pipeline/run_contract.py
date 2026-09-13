"""Execution contracts for the resumable story-to-video pipeline.

The pipeline is a modular monolith, but each run now has an explicit contract:
profile, provider capabilities, prompt revision, and stage artifacts. This keeps
GPU-heavy stages from discovering missing dependencies halfway through a run.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import PipelineConfig

RunProfile = Literal["smoke", "production"]


class CapabilityStatus(BaseModel):
    capability: str
    provider: str
    available: bool
    reason: str = ""
    model: str = ""


class RunContract(BaseModel):
    profile: RunProfile
    animation_enabled: bool
    required_capabilities: list[str]
    capabilities: list[CapabilityStatus]
    prompt_files: dict[str, str]
    stage_artifacts: dict[str, list[str]]
    warnings: list[str] = Field(default_factory=list)

    @property
    def blockers(self) -> list[str]:
        return [f"{c.capability}: {c.reason}" for c in self.capabilities if not c.available]


STAGE_ARTIFACTS: dict[str, list[str]] = {
    "stage0": ["input/script.txt", "stage0_scenes.json"],
    "stage0_dossier": ["intake/dossier.json"],
    "stage1": ["worldbible/world_bible.json"],
    "stage1_world": ["worldbible/world_bible.json"],
    "stage3": ["storyboard/storyboard.json"],
    "stage2": ["screenplay/screenplay.json"],
    "stage4": ["audio"],
    "stage1r": ["references/references.json"],
    "stage3b": ["panels"],
    "stage3c": ["clips"],
    "stage_vlm_review": ["reviews/vlm_review.json"],
    "stage5": ["video"],
}


def _prompt_fingerprints(prompts_dir: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        for p in sorted(prompts_dir.glob("*.md"))
    }


def _ollama_capability(config: PipelineConfig, capability: str) -> CapabilityStatus:
    selection = getattr(config.providers, capability, None)
    provider = getattr(selection, "provider", "ollama")
    model = getattr(selection, "model", "")
    if provider != "ollama":
        return CapabilityStatus(capability=capability, provider=provider, available=True, model=model)
    try:
        import requests

        data = requests.get(f"{config.ollama_url.rstrip('/')}/api/tags", timeout=5).json()
        installed = {m.get("name", "") for m in data.get("models", [])}
        configured = model or getattr(config.models, f"llm_{capability}", config.models.llm_default)
        if configured in installed:
            return CapabilityStatus(capability=capability, provider=provider, available=True, model=configured)
        fallback = next(iter(sorted(installed)), "")
        return CapabilityStatus(
            capability=capability,
            provider=provider,
            available=bool(fallback),
            model=fallback,
            reason=f"configured model {configured!r} unavailable; fallback {fallback!r}" if fallback else "no installed Ollama model",
        )
    except Exception as exc:
        return CapabilityStatus(capability=capability, provider=provider, available=False, model=model, reason=str(exc))


def _comfy_capability(config: PipelineConfig, capability: str) -> CapabilityStatus:
    try:
        import requests

        requests.get(f"{config.comfyui_url.rstrip('/')}/system_stats", timeout=5).raise_for_status()
        return CapabilityStatus(capability=capability, provider="comfyui", available=True)
    except Exception as exc:
        return CapabilityStatus(capability=capability, provider="comfyui", available=False, reason=str(exc))


def build_run_contract(config: PipelineConfig, prompts_dir: Path, profile: RunProfile) -> RunContract:
    animation = bool(config.animation.enabled)
    required = ["llm", "t2i"]
    if animation:
        required.append("i2v")
    statuses = []
    for capability in required:
        statuses.append(_comfy_capability(config, capability) if capability in {"t2i", "i2i", "i2v"} else _ollama_capability(config, capability))
    warnings: list[str] = []
    if profile == "smoke":
        warnings.append("smoke profile uses bounded image resolution and skips optional identity refinement")
    if not animation:
        warnings.append("animation disabled; stage3c and clip review will be recorded as skipped")
    return RunContract(
        profile=profile,
        animation_enabled=animation,
        required_capabilities=required,
        capabilities=statuses,
        prompt_files=_prompt_fingerprints(prompts_dir),
        stage_artifacts=STAGE_ARTIFACTS,
        warnings=warnings,
    )


def write_run_contract(project_dir: Path, contract: RunContract) -> Path:
    path = project_dir / "run_contract.json"
    path.write_text(contract.model_dump_json(indent=2), encoding="utf-8")
    return path


def artifact_contract_complete(project_dir: Path, stage: str) -> bool:
    for relative in STAGE_ARTIFACTS.get(stage, []):
        path = project_dir / relative
        if path.name in {"panels", "audio", "clips", "video"}:
            if not path.is_dir() or not any(path.rglob("*")):
                return False
        elif not path.exists():
            return False
    return True
