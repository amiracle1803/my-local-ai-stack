"""Project identity + story-pollution guard.

The blueprint is written once at intake and is the project's immutable
identity. ``title_hash`` (sha256 of normalized first 2k chars of the
script) is the pollution tripwire: stages recompute it from
``input/script.txt`` and abort if it drifts.
"""

from __future__ import annotations

import hashlib
import re
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

# Canonical execution order: source -> timed audio spine -> visual planning ->
# generation -> assembly. UI stage cards may retain historical IDs, but this
# order is the dependency contract.
STAGE_ORDER: list[str] = [
    "stage0",          # intake: script.txt -> blueprint + scenes
    "stage0_dossier",  # intake enrichment: characters/locations/dialogue log
    "stage1",          # world bible: characters/outfits/relationships
    "stage1_world",    # world enrichment: locations/era/lore
    "stage2",          # screenplay: narration + dialogue + SFX
    "stage4",          # audio: TTS narration + voices
    "stage3",          # storyboard: enrich timed screenplay with shot direction
    "stage1r",         # references: per-character visual refs
    "stage3b",         # images: one panel per shot
    "stage3c",         # animation: motion clips (or skipped in panels mode)
    "stage_vlm_review",  # consistency review gate
    "stage5",          # assembly: final MP4 + SRT + chapters
]

SNAP_TARGETS: tuple[int, ...] = (24, 30, 60)
_HASH_CHARS = 2000


class StoryPollutionError(RuntimeError):
    """Raised when a project's script no longer matches its blueprint hash."""


def snap_fps(fps: int) -> int:
    clamped = max(24, min(60, int(fps)))
    return min(SNAP_TARGETS, key=lambda t: (abs(t - clamped), t))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def compute_title_hash(script_text: str) -> str:
    prefix = _normalize(script_text)[:_HASH_CHARS]
    return hashlib.sha256(prefix.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Style(BaseModel):
    name: str = "z-anime"
    lora: str | None = None
    negative: str = (
        "lowres, bad anatomy, bad hands, text, error, missing fingers, "
        "extra digit, fewer digits, cropped, worst quality, low quality, "
        "jpeg artifacts, signature, watermark, blurry"
    )


class Target(BaseModel):
    resolution: tuple[int, int] = (1280, 720)
    max_block_seconds: int = 90


class StageEntry(BaseModel):
    status: str = "pending"  # pending | running | done | failed
    ts: str | None = None
    score: float | None = None


class Blueprint(BaseModel):
    """blueprint.json — project identity + settings + stage ledger."""

    story_id: str
    slug: str
    title_hash: str
    created: str
    fps: int
    mode: str = "0b"  # 0b generate | 0a transform | 0i import
    style: Style = Field(default_factory=Style)
    target: Target = Field(default_factory=Target)
    stages: dict[str, StageEntry] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    def write(self, project_dir: str | Path) -> Path:
        path = Path(project_dir) / "blueprint.json"
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, project_dir: str | Path) -> "Blueprint":
        return cls.model_validate_json((Path(project_dir) / "blueprint.json").read_text(encoding="utf-8"))


def create_blueprint(script_text: str, slug: str, fps: int = 24, mode: str = "0b") -> Blueprint:
    snapped = snap_fps(fps)
    if snapped != int(fps):
        warnings.warn(f"fps {fps} snapped to {snapped}", stacklevel=2)
    return Blueprint(
        story_id=str(uuid.uuid4()),
        slug=slug,
        title_hash=compute_title_hash(script_text),
        created=now_iso(),
        fps=snapped,
        mode=mode,
        stages={s: StageEntry() for s in STAGE_ORDER},
    )


def verify_story_guard(project_dir: str | Path) -> None:
    """Abort if input/script.txt drifted from the blueprint hash."""
    project_dir = Path(project_dir)
    bp = Blueprint.load(project_dir)
    script_path = project_dir / "input" / "script.txt"
    if not script_path.exists():
        return
    current = compute_title_hash(script_path.read_text(encoding="utf-8", errors="replace"))
    if current != bp.title_hash:
        raise StoryPollutionError(
            f"input/script.txt no longer matches blueprint for {bp.slug!r} "
            "(script was swapped under an in-progress project)"
        )
