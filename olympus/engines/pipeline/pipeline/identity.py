"""Stable artifact identity helpers for pipeline outputs."""

from __future__ import annotations

import re
from pathlib import Path


_SHOT_RE = re.compile(r"^sh[-_](\d{3})[-_](\d{2,3})$")


def shot_parts(shot_id: str) -> tuple[int, int]:
    match = _SHOT_RE.match(shot_id.lower())
    if not match:
        raise ValueError(f"invalid shot id: {shot_id!r}")
    return int(match.group(1)), int(match.group(2))


def canonical_name(project: str, shot_id: str, asset: str, ext: str,
                   variant: str | None = None, attempt: int | None = None,
                   version: int = 1) -> str:
    scene, shot = shot_parts(shot_id)
    parts = [project.lower(), f"sc{scene:03d}", f"sh{shot:03d}", asset.lower()]
    if variant:
        parts.append(re.sub(r"[^a-z0-9]+", "_", variant.lower()).strip("_"))
    if attempt is not None:
        parts.append(f"tk{attempt:02d}")
    parts.append(f"v{version:03d}")
    return "_".join(parts) + "." + ext.lstrip(".")


def artifact_path(root: str | Path, project: str, shot_id: str, asset: str,
                  ext: str, variant: str | None = None) -> Path:
    return Path(root) / canonical_name(project, shot_id, asset, ext, variant)


def legacy_stem(shot_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", shot_id.lower()).strip("_")
