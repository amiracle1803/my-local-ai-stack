"""Stage 0S: faithful source intake.

Unlike 0A, this mode never transforms or originalizes the source. It preserves
the supplied story verbatim and creates only a deterministic scene index so the
rich dossier stage can consume the exact script.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .blueprint import Blueprint
from .config import PipelineConfig
from .scores import Scores
from ._util import now_iso
from .story_contract import write_source_manifest

_MARKER = re.compile(r"^\s*---\s*\[SCENE\s+(\d+)\s*:\s*(.*?)\]\s*---\s*$", re.I)
_CHAPTER = re.compile(r"^\s*Chapter\s+([^\n]+)$", re.I)


def run(project_dir: str | Path, config: PipelineConfig, scores: Scores) -> dict[str, Any]:
    project_dir = Path(project_dir)
    script = (project_dir / "input" / "script.txt").read_text(encoding="utf-8")
    write_source_manifest(project_dir)
    lines = script.splitlines()
    markers = [(i, int(m.group(1)), m.group(2).strip()) for i, line in enumerate(lines) if (m := _MARKER.match(line))]
    if not markers:
        chapter_markers = [(i, m.group(1).strip()) for i, line in enumerate(lines) if (m := _CHAPTER.match(line))]
        markers = [(line_no, index + 1, title) for index, (line_no, title) in enumerate(chapter_markers)]
    scenes = []
    if markers:
        for index, (line_no, number, title) in enumerate(markers):
            end = markers[index + 1][0] if index + 1 < len(markers) else len(lines)
            body = "\n".join(lines[line_no + 1:end]).strip()
            scenes.append({"number": number, "title": title, "text": body, "source_preserved": True})
    else:
        scenes = [{"number": 1, "title": "source", "text": script.strip(), "source_preserved": True}]
    out = project_dir / "stage0_scenes.json"
    manifest = write_source_manifest(project_dir)
    out.write_text(json.dumps({"mode": "0s", "source_preserved": True, "estimated_beat_count": manifest.estimated_beat_count, "scenes": scenes}, indent=2), encoding="utf-8")
    scores.record("stage0", "global", "structure_completeness", 1.0)
    scores.record("stage0", "global", "source_preserved", 1.0)
    scores.record("stage0", "global", "scene_count", float(len(scenes)))
    scores.stage_done("stage0")
    bp = Blueprint.load(project_dir)
    bp.stages["stage0"].status = "done"
    bp.stages["stage0"].ts = now_iso()
    bp.write(project_dir)
    return {"stage": "stage0", "status": "done", "source_preserved": True, "scenes": len(scenes), "path": str(out)}
