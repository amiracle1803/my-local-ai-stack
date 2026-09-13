"""Immutable source and story-beat contracts for the audio-first pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SourceManifest(BaseModel):
    path: str = "input/script.txt"
    sha256: str
    word_count: int
    title: str = ""
    scene_count: int = 0
    estimated_beat_count: int = 0
    structure_version: int = 4


class SourceSpan(BaseModel):
    id: str
    text: str
    start: int = 0
    end: int = 0


class StoryBeat(BaseModel):
    id: str
    scene_id: str
    order: int
    event: str
    source_span_ids: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    location: str = ""
    emotional_before: str = ""
    emotional_after: str = ""
    causal_role: str = "action"
    required: bool = True


def source_path(project_dir: Path) -> Path:
    # The intake script is the immutable project source. input/source.txt is
    # optional transform-mode provenance and must never replace this authority.
    return project_dir / "input" / "script.txt"


def write_source_manifest(project_dir: Path) -> SourceManifest:
    manifest = _build_manifest(project_dir)
    out = project_dir / "input" / "source_manifest.json"
    if out.exists():
        existing = SourceManifest.model_validate_json(out.read_text(encoding="utf-8"))
        if existing.sha256 != manifest.sha256:
            raise RuntimeError("immutable source changed after source_manifest.json was written")
        if existing.scene_count != manifest.scene_count or existing.estimated_beat_count != manifest.estimated_beat_count:
            out.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
            return manifest
        return existing
    out.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def repin_source_manifest(project_dir: Path) -> SourceManifest:
    """Re-write the source manifest to fingerprint the *current* intake script.

    This is the deliberate exception to source immutability: mode 0B GENERATE
    writes a brand-new ``input/script.txt`` from a brief at intake time, and the
    generated script *becomes* the immutable source for every downstream stage.
    Unlike :func:`write_source_manifest` (which refuses a sha change), this
    overwrites unconditionally -- it must only be called from the intake stage
    that legitimately produces the script, never from downstream stages.
    """
    out = project_dir / "input" / "source_manifest.json"
    manifest = _build_manifest(project_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def _build_manifest(project_dir: Path) -> SourceManifest:
    path = source_path(project_dir)
    text = path.read_text(encoding="utf-8")
    markers = re.findall(
        r"^\s*(?:---\s*\[SCENE\s+\d+\s*:|Chapter\s+[^\n]+$)",
        text, re.MULTILINE | re.IGNORECASE,
    )
    return SourceManifest(
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        word_count=len(text.split()),
        title=(text.splitlines()[0].strip() if text.splitlines() else ""),
        scene_count=len(markers),
        estimated_beat_count=max(1, round(len(text.split()) / 80)),
    )


def verify_source_manifest(project_dir: Path) -> SourceManifest:
    path = project_dir / "input" / "source_manifest.json"
    if not path.exists():
        return write_source_manifest(project_dir)
    expected = SourceManifest.model_validate_json(path.read_text(encoding="utf-8"))
    current_path = project_dir / expected.path
    current = hashlib.sha256(current_path.read_bytes()).hexdigest()
    if current != expected.sha256:
        from .blueprint import StoryPollutionError

        raise StoryPollutionError("immutable intake script changed after source_manifest.json was written")
    return expected


def collect_beats(screenplay: dict[str, Any]) -> list[StoryBeat]:
    beats: list[StoryBeat] = []
    order = 0
    for scene in screenplay.get("scenes", []):
        scene_id = str(scene.get("id", f"sc-{len(beats) + 1:03d}"))
        for shot in scene.get("shots", []):
            order += 1
            beat_id = f"beat-{order:04d}"
            beat = StoryBeat(
                id=beat_id,
                scene_id=scene_id,
                order=order,
                event=shot.get("beat", "") or shot.get("summary", ""),
                source_span_ids=list(shot.get("source_span_ids", [])),
                characters=list(shot.get("characters_in_frame", [])),
                location=str(scene.get("location", "")),
                emotional_before=str(shot.get("emotional_before", "")),
                emotional_after=str(shot.get("emotional_after", "")),
                causal_role=str(shot.get("causal_role", "action")),
            )
            beats.append(beat)
            shot.setdefault("beat_ids", []).append(beat_id)
    return beats


def write_beats(project_dir: Path, screenplay: dict[str, Any]) -> list[StoryBeat]:
    beats = collect_beats(screenplay)
    screenplay_path = project_dir / "screenplay" / "screenplay.json"
    screenplay_path.write_text(json.dumps(screenplay, indent=2, ensure_ascii=False), encoding="utf-8")
    path = project_dir / "screenplay" / "story_beats.json"
    path.write_text(json.dumps({"beats": [b.model_dump() for b in beats]}, indent=2, ensure_ascii=False), encoding="utf-8")
    return beats
