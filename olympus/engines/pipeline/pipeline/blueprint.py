"""Project identity + story-pollution guard (design 3.1).

The blueprint is written once at intake and is the project's immutable
identity. ``title_hash`` (sha256 of the normalized first 2k chars of the
script) is the pollution tripwire: every stage recomputes it from
``input/script.txt`` and aborts if it drifts from the blueprint -- meaning the
script was swapped underneath an in-progress project.
"""

from __future__ import annotations

import hashlib
import re
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

# Canonical stage execution order (design 3.9): 0 -> 1 -> 1R -> 2 -> 3 -> 3B
# -> 4 -> 3C -> 5. Shared with scores.py (gating) and run.py (CLI).
STAGE_ORDER: list[str] = [
    "stage0",
    "stage1",
    "stage1r",
    "stage2",
    "stage3",
    "stage3b",
    "stage4",
    "stage3c",
    "stage5",
]

# fps is fixed at intake, 24-60, snapped to a video-model-friendly rate.
SNAP_TARGETS: tuple[int, ...] = (24, 30, 60)

_HASH_CHARS = 2000  # normalized prefix length hashed for the title_hash


class StoryPollutionError(RuntimeError):
    """Raised when a project's script no longer matches its blueprint hash."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def snap_fps(fps: int) -> int:
    """Clamp to [24, 60] then snap to the nearest of 24/30/60 (ties -> lower)."""
    clamped = max(24, min(60, int(fps)))
    snapped = min(SNAP_TARGETS, key=lambda t: (abs(t - clamped), t))
    if snapped != int(fps):
        warnings.warn(
            f"fps {fps} snapped to {snapped} for video-model compatibility",
            stacklevel=2,
        )
    return snapped


def _normalize(text: str) -> str:
    """Lowercase + collapse all whitespace runs to single spaces, trimmed."""
    return re.sub(r"\s+", " ", text).strip().lower()


def compute_title_hash(script_text: str) -> str:
    """sha256 of the normalized first ``_HASH_CHARS`` chars of the script."""
    prefix = _normalize(script_text)[:_HASH_CHARS]
    return hashlib.sha256(prefix.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# models (design 3.1)
# --------------------------------------------------------------------------
class Style(BaseModel):
    name: str = "z-anime"
    lora: str | None = None
    negative: str = (
        "lowres, bad anatomy, bad hands, text, error, missing fingers, "
        "extra digit, fewer digits, cropped, worst quality, low quality, "
        "jpeg artifacts, signature, watermark, blurry"
    )


class Target(BaseModel):
    # Generation is landscape 1216x704 into a 1280x720 timeline (design 3B).
    resolution: tuple[int, int] = (1280, 720)
    max_block_seconds: int = 90


class StageEntry(BaseModel):
    status: str = "pending"  # pending | running | done | failed
    ts: str | None = None
    score: float | None = None


class Blueprint(BaseModel):
    """``blueprint.json`` -- project identity + settings + stage ledger."""

    story_id: str
    slug: str
    title_hash: str
    created: str
    fps: int
    style: Style = Field(default_factory=Style)
    target: Target = Field(default_factory=Target)
    stages: dict[str, StageEntry] = Field(default_factory=dict)

    # ---- persistence ---------------------------------------------------
    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    def write(self, project_dir: str | Path) -> Path:
        path = Path(project_dir) / "blueprint.json"
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, project_dir: str | Path) -> "Blueprint":
        path = Path(project_dir) / "blueprint.json"
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


def create_blueprint(
    script_text: str,
    slug: str,
    fps: int = 24,
    *,
    style: Style | None = None,
    target: Target | None = None,
    story_id: str | None = None,
) -> Blueprint:
    """Build a fresh Blueprint with a full pending stage ledger."""
    return Blueprint(
        story_id=story_id or str(uuid.uuid4()),
        slug=slug,
        title_hash=compute_title_hash(script_text),
        created=_now_iso(),
        fps=snap_fps(fps),
        style=style or Style(),
        target=target or Target(),
        stages={s: StageEntry() for s in STAGE_ORDER},
    )


def verify_story_guard(project_dir: str | Path) -> Blueprint:
    """Load the blueprint, recompute the title_hash from ``input/script.txt``,
    and raise :class:`StoryPollutionError` if they differ.

    Returns the loaded blueprint so callers can proceed with a trusted identity.
    """
    project_dir = Path(project_dir)
    bp = Blueprint.load(project_dir)
    script_path = project_dir / "input" / "script.txt"
    if not script_path.exists():
        raise StoryPollutionError(
            f"story guard: {script_path} is missing; cannot verify integrity."
        )
    current = compute_title_hash(script_path.read_text(encoding="utf-8"))
    if current != bp.title_hash:
        raise StoryPollutionError(
            f"story guard TRIPPED for project {bp.slug!r} (story_id={bp.story_id}): "
            f"input/script.txt hash {current[:12]}... != blueprint {bp.title_hash[:12]}.... "
            f"The script was swapped mid-project - aborting to protect existing artifacts."
        )
    return bp
