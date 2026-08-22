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


# ---------------------------------------------------------------------------
# LLM-output name hygiene -- the model sometimes returns placeholder strings
# ("none", "unknown", "no one") or pronouns ("her", "they") where a concrete
# name is required. These helpers let the dossier merge drop those.
# ---------------------------------------------------------------------------
_PLACEHOLDER_VALUES = {
    "", "none", "unknown", "n/a", "na", "null", "no one", "nobody",
    "none evidenced", "none found", "n o n e",
}
_PRONOUNS = {
    "he", "she", "her", "his", "him", "hers", "they", "them", "their",
    "theirs", "it", "its", "himself", "herself", "themselves",
}


def is_placeholder_name(name: str | None) -> bool:
    """True if ``name`` is empty, a placeholder, or a pronoun -- i.e. not a
    usable concrete character/location name."""
    n = (name or "").strip().lower()
    return n in _PLACEHOLDER_VALUES or n in _PRONOUNS


def clean_name_list(items: list[str]) -> list[str]:
    """Drop placeholder/pronoun entries from a list of names, preserving order."""
    return [i.strip() for i in items if not is_placeholder_name(i)]