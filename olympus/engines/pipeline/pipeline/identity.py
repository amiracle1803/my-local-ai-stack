"""Canonical VFX-style identity for pipeline artifacts (the naming standard).

Every artifact keeps a stable **internal machine id** (``sh-001-01`` = scene 001
+ shot 01) as the JSON-contract / cache / storyboard key — never rename what
downstream stages reference. This module derives the **canonical VFX id** from
that id and renders forward-only artifact filenames:

    {project}_sc{scene:03d}_sh{shot:03d}_{asset}_v{version:03d}.{ext}

e.g. ``olympusdemo_sc001_sh001_pn01_render_v001.png``.

A bidirectional resolver maps legacy ``sh-001-01`` names to canonical ids (and
vice versa) so existing projects keep working while new artifacts use the new
naming. ``tk##`` marks generation attempts / seed exploration; ``v###`` marks a
deliberate approved revision (starts at ``v001``, bumped only on regen).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._util import read_json

_LEGACY_SID_RE = re.compile(r"^sh-(\d{3})-(\d{2})")
# new: {project}_sc{scene:03d}_sh{shot:03d}_{asset}_v{version:03d}.{ext}
_CANONICAL_RE = re.compile(
    r"^(?P<project>[a-z0-9-]+)_sc(?P<scene>\d{3})_sh(?P<shot>\d{3})"
    r"_(?P<asset>[a-z0-9]+)(?:_(?P<variant>[a-z0-9-]+))?"
    r"_(?P<version>v\d{3})"
)
# new take suffix: ..._tk02 (no version) or ..._tk02_v002
_TAKE_RE = re.compile(r"_tk(\d{2})")


def slugify_project(name: str) -> str:
    """Sanitize a project folder name into the ``project_code`` used in ids."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "project"


def project_code(project_dir: str | Path) -> str:
    """The canonical project code from the blueprint slug (sanitized)."""
    bp = _blueprint(Path(project_dir))
    slug = bp.get("slug") or Path(project_dir).name
    return slugify_project(str(slug))


def canonical_shot_id(shot_id: str, project: str = "") -> str:
    """Map a legacy ``sh-001-01`` id to ``{project}_sc001_sh001``.

    If ``project`` is empty the returned id starts at ``sc001_sh001`` (no
    project prefix) — the prefix is added when the caller has a project dir.
    """
    m = _LEGACY_SID_RE.match(shot_id)
    if not m:
        return shot_id  # already canonical or unknown — pass through
    scene, shot = m.group(1), int(m.group(2))
    core = f"sc{scene}_sh{shot:03d}"
    return f"{slugify_project(project)}_{core}" if project else core


def scene_id_from_shot(shot_id: str) -> str:
    """The canonical scene id (``sc001``) that a shot belongs to."""
    m = _LEGACY_SID_RE.match(shot_id)
    return f"sc{m.group(1)}" if m else shot_id


def panel_id(canonical: str, n: int = 1) -> str:
    """Canonical panel id: ``{canonical}_pn{n:02d}``."""
    return f"{canonical}_pn{n:02d}"


def clip_id(canonical: str, n: int = 1) -> str:
    """Canonical clip id: ``{canonical}_cl{n:02d}``."""
    return f"{canonical}_cl{n:02d}"


def version_name(n: int = 1) -> str:
    """Version token ``v001`` (3-digit, zero-padded)."""
    return f"v{n:03d}"


def take_name(n: int = 1) -> str:
    """Take token ``tk01`` (2-digit, zero-padded)."""
    return f"tk{n:02d}"


def artifact_name(
    canonical: str,
    asset: str,
    *,
    variant: str = "",
    version: int = 1,
    ext: str = "png",
    take: int | None = None,
) -> str:
    """Render a canonical artifact filename.

    ``{canonical}_{asset}[_{variant}]_v{version:03d}.{ext}``; when ``take`` is
    given the take token is inserted before the version::
        ..._pn01_render_v001.png          (approved revision)
        ..._pn01_render_tk02_v001.png     (attempt #2, same approved rev)
    """
    base = f"{canonical}_{asset}"
    if variant:
        base += f"_{variant}"
    if take is not None:
        base += f"_{take_name(take)}"
    return f"{base}_{version_name(version)}.{ext}"


def canonical_id_from_filename(filename: str) -> str | None:
    """Reverse-resolve a canonical filename to its ``{project}_scNNN_shNNN`` id."""
    m = _CANONICAL_RE.match(Path(filename).name)
    if not m:
        return None
    return f"{m.group('project')}_sc{m.group('scene')}_sh{m.group('shot')}"


def legacy_sid_from_filename(filename: str) -> str | None:
    """Extract a legacy ``sh-001-01`` id from an old-style filename, if any."""
    m = _LEGACY_SID_RE.match(Path(filename).name)
    return m.group(0) if m else None


def sid_from_panel_name(filename: str, project: str = "") -> str:
    """Recover the internal machine sid from a panel filename.

    Handles legacy ``sh-001-01.png`` and canonical
    ``{project}_sc001_sh001_pn01_render_v001.png``."""
    legacy = legacy_sid_from_filename(filename)
    if legacy:
        return legacy
    m = re.search(r"_sc(\d{3})_sh(\d{3})", Path(filename).name)
    if m:
        return f"sh-{m.group(1)}-{int(m.group(2)):02d}"
    return Path(filename).stem


def panel_path(block_dir: Path, sid: str, project: str = "", *, version: int = 1) -> Path:
    """The canonical panel filename for a shot, falling back to the legacy
    ``<sid>.png`` when a legacy-named panel already exists (resume-safe).

    New panels are written as ``{project}_sc{scene}_sh{shot}_pn01_render_v001.png``;
    existing legacy projects keep their ``sh-001-01.png`` files untouched."""
    legacy = block_dir / f"{sid}.png"
    if not project:
        return legacy
    canonical = canonical_shot_id(sid, project)
    if canonical == sid:
        return legacy
    return block_dir / artifact_name(canonical, "pn01", variant="render", version=version, ext="png")


def resolve_panel(block_dir: Path, sid: str, project: str = "") -> Path:
    """Find the on-disk panel for a shot: canonical name preferred, then legacy.

    Canonical wins because it is the standard going forward and is never stale
    for a regenerated shot; legacy is only a fallback for untouched projects."""
    canonical = canonical_shot_id(sid, project)
    if canonical != sid:
        for p in sorted(block_dir.glob(f"{canonical}_pn*_render_v*.png")):
            return p
    legacy = block_dir / f"{sid}.png"
    return legacy


def audio_path(
    audio_dir: Path, sid: str, project: str, asset: str, version: int = 1, ext: str = "wav",
) -> Path:
    """Canonical audio filename for a shot (narration/dialogue/align).

    ``{canonical}_audio_narration_v001.wav`` / ``..._align_v001.json``. Falls back
    to the legacy ``{sid}.wav`` for existing legacy projects."""
    canonical = canonical_shot_id(sid, project)
    if canonical == sid:
        return audio_dir / f"{sid}.{ext}"
    return audio_dir / artifact_name(canonical, asset, version=version, ext=ext)


def dialogue_path(audio_dir: Path, sid: str, project: str, n: int, version: int = 1) -> Path:
    """Canonical dialogue audio for line ``n`` of a shot.

    ``{canonical}_dialogue_dl{n:02d}_v001.wav``; legacy ``{sid}_{n}.wav`` for
    existing legacy projects."""
    canonical = canonical_shot_id(sid, project)
    if canonical == sid:
        return audio_dir / f"{sid}_{n}.wav"
    return audio_dir / artifact_name(canonical, "dialogue", variant=f"dl{n:02d}", version=version, ext="wav")


def version_from_filename(filename: str) -> str | None:
    """The ``v###`` token embedded in a canonical filename, if any."""
    m = re.search(r"_v(\d{3})", Path(filename).name)
    return f"v{m.group(1)}" if m else None


def take_from_filename(filename: str) -> str | None:
    """The ``tk##`` token embedded in a canonical filename, if any."""
    m = _TAKE_RE.search(Path(filename).name)
    return f"tk{m.group(1)}" if m else None


def _blueprint(project_dir: Path) -> dict[str, Any]:
    try:
        return read_json(project_dir / "blueprint.json")
    except (OSError, ValueError):
        return {}