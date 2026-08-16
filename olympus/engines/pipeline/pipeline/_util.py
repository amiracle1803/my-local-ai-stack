"""Shared pipeline utilities — eliminates copy-paste across stage modules.

Import from here instead of redefining ``_now_iso``, repeating
``json.loads(path.read_text(...))``, or reloading the same JSON files
in every stage.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_script(project_dir: str | Path) -> str:
    return (Path(project_dir) / "input" / "script.txt").read_text(encoding="utf-8")


def load_screenplay(project_dir: str | Path) -> dict[str, Any]:
    return read_json(Path(project_dir) / "screenplay" / "screenplay.json")


def load_storyboard(project_dir: str | Path) -> dict[str, Any]:
    return read_json(Path(project_dir) / "storyboard" / "storyboard.json")


def _shots_by_id(screenplay: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {shot["id"]: shot for scene in screenplay.get("scenes", []) for shot in scene.get("shots", [])}