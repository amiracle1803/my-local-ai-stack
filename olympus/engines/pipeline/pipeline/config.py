"""Pipeline configuration loader (design sections 0, 0.2, 5.3b).

Loads ``pipeline.toml`` via ``tomllib`` into typed pydantic v2 models with
accessors for the ``[models]`` (incl. the ban list), ``[automation]``,
``[animation]`` and ``[paths]`` tables. Enforces the MODEL BAN LIST:
``resolve_image_model()`` raises ``BannedModelError`` if the resolved
checkpoint name is on ``models.banned``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

# Engine root = the directory that contains pipeline.toml (parent of this
# package directory).
ENGINE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ENGINE_ROOT / "pipeline.toml"


class BannedModelError(ValueError):
    """Raised when a banned checkpoint is selected for image generation."""


class ModelsConfig(BaseModel):
    """The ``[models]`` table."""

    llm_script: str
    llm_vision: str
    llm_default: str
    image_primary: str
    image_fallback: str
    tts: str = "kokoro"
    animation_primary: str = "Wan2.2-TI2V-5B-fp8"
    banned: list[str] = Field(default_factory=list)


class AutomationConfig(BaseModel):
    """The ``[automation]`` table (design 0.2). All default true."""

    auto_approve_blueprint: bool = True
    auto_approve_transform_map: bool = True
    auto_approve_identity: bool = True
    auto_resolve_contradictions: bool = True
    auto_advance_stages: bool = True
    # Explicit, scorecard-logged deviation: lets Stage 3B run without trained
    # per-character LoRAs while kohya is unavailable on Linux (design 1R.2b
    # gate). Never silent -- stage1r records lora_training_contingency=1.
    allow_missing_loras: bool = False


class AnimationConfig(BaseModel):
    """The ``[animation]`` table (design 3C)."""

    drift_axis: str = "vertical"
    max_animated_seconds_per_block: float = 60.0
    default_motion_tier: int = 1


class PathsConfig(BaseModel):
    """The ``[paths]`` table. Relative paths resolve against the engine root."""

    projects: str = "projects"
    loras: str = "E:/AI/Models/loras"
    comfyui: str = "C:/AI/ComfyUI"


class PipelineConfig(BaseModel):
    """Top-level typed view of ``pipeline.toml``."""

    models: ModelsConfig
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    animation: AnimationConfig = Field(default_factory=AnimationConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    # Path the config was loaded from; anchors relative [paths] entries.
    config_path: Path = Field(default=DEFAULT_CONFIG_PATH, exclude=True)

    # ---- loading -------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path | None = None) -> "PipelineConfig":
        """Load and validate ``pipeline.toml`` (defaults to the engine copy)."""
        cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        if not cfg_path.exists():
            raise FileNotFoundError(f"pipeline config not found: {cfg_path}")
        with cfg_path.open("rb") as fh:
            data = tomllib.load(fh)
        cfg = cls.model_validate(data)
        cfg.config_path = cfg_path.resolve()
        return cfg

    # ---- model resolution + ban enforcement ---------------------------
    def resolve_image_model(self, role: str = "primary") -> str:
        """Resolve the image checkpoint for ``role`` ('primary' | 'fallback').

        Raises :class:`BannedModelError` if the resolved name is on the ban
        list. This is the single choke point every image stage must go
        through -- the ban is enforced in code, not by convention.
        """
        if role == "primary":
            name = self.models.image_primary
        elif role == "fallback":
            name = self.models.image_fallback
        else:
            raise ValueError(f"unknown image role: {role!r} (want 'primary'/'fallback')")
        if name in self.models.banned:
            raise BannedModelError(
                f"image model {name!r} (role={role}) is on the MODEL BAN LIST "
                f"{self.models.banned} - refusing to use it (design 5.3b)."
            )
        return name

    # ---- path helpers --------------------------------------------------
    def _resolve_path(self, raw: str) -> Path:
        p = Path(raw)
        if p.is_absolute():
            return p
        return (self.config_path.parent / p).resolve()

    def projects_dir(self) -> Path:
        """Absolute path to the projects directory."""
        return self._resolve_path(self.paths.projects)

    def loras_dir(self) -> Path:
        return self._resolve_path(self.paths.loras)

    def comfyui_dir(self) -> Path:
        return self._resolve_path(self.paths.comfyui)
