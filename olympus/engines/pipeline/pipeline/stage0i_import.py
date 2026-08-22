"""Stage 0I -- IMPORT (existing panels -> story). Original spec
``aether-studio-original-spec-stages0-2.md`` STAGE 0 -> Stage 0I; design
``anime-pipeline-v2-design.md`` 4. Stage 0 THREE MODES, 0I bullet.

Four passes:

- **Pass 1 -- Panel Inventory** (no LLM): pure filesystem -- natural-sort the
  panel files, flag likely-blank (<5KB), classify full-page/cover by size,
  enforce a 60-panel cap.
- **Pass 2 -- Per-Panel Vision Analysis** (vision model, one call per panel):
  per-panel characters / action / dialogue / mood / setting / shot_type. Tiered
  failure handling (full -> partial -> minimal + manual-review flag).
- **Pass 3 -- Character Identity Resolution**: cluster appearance descriptions
  into unique individuals so the world bible does not split one person.
- **Pass 4 -- Screenplay Synthesis**: every panel = one shot; consecutive same-
  setting panels = one scene. Writes ``screenplay/screenplay.json`` plus
  ``input/script.txt`` (a readable summary) and a fair-use score.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .blueprint import Blueprint, compute_title_hash
from .config import ENGINE_ROOT, PipelineConfig
from .llm import PipelineLLM
from .schemas.stage0 import (
    IdentityCluster,
    ImportedShot,
    PanelAnalysis,
    PanelInventoryItem,
)
from .scores import Scores
from .stage0_intake import PROMPTS_DIR
from ._util import now_iso

logger = logging.getLogger(__name__)

# Accepted image extensions for panel import.
_PANEL_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
# Files below this size are almost certainly blank/corrupt.
_BLANK_SIZE = 5 * 1024
# A panel > this multiple of the median size is likely a full-page splash.
_FULLPAGE_MULT = 3.0
# Maximum panels a single import may process (synthesis context safety).
_MAX_PANELS = 60

_PANELS_DIR = "input/panels"
_INVENTORY_PATH = "stage0i_inventory.json"
_PANEL_ANALYSES_PATH = "stage0i_panel_analyses.json"
_IDENTITY_PATH = "stage0i_identity.json"
_SYNTHESIS_PATH = "screenplay/screenplay.json"
_SCRIPT_PATH = "input/script.txt"
_FAIR_USE_PATH = "stage0i_fair_use.json"


class Stage0IError(ValueError):
    """Stage 0I-specific input problems."""


class _IdentityOutput(BaseModel):
    characters: list[IdentityCluster] = Field(default_factory=list)
    uncertain_groupings: list[dict] = Field(default_factory=list)


class _SynthesisOutput(BaseModel):
    scenes: list[dict] = Field(default_factory=list)


def _natural_sort_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def natural_sort(paths: list[Path]) -> list[Path]:
    """Sort panel files by natural (human) order: panel_1, panel_2, panel_10."""
    return sorted(paths, key=lambda p: _natural_sort_key(p.name))


def inventory_panels(panels_dir: Path) -> list[PanelInventoryItem]:
    """Pass 1 -- pure filesystem inventory, no LLM. Returns panels sorted by
    natural filename order with blank/classification flags."""
    files = [
        p for p in panels_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _PANEL_EXTS
    ]
    files = natural_sort(files)

    if not files:
        return []

    sizes = sorted(p.stat().st_size for p in files)
    median = sizes[len(sizes) // 2] if sizes else 0

    items: list[PanelInventoryItem] = []
    for i, p in enumerate(files, 1):
        size = p.stat().st_size
        flagged_blank = size < _BLANK_SIZE
        if flagged_blank:
            classification = "unknown"
        elif median and size > _FULLPAGE_MULT * median:
            classification = "full_page_splash"
        else:
            classification = "panel"
        items.append(
            PanelInventoryItem(
                path=p.name,
                size_bytes=size,
                flagged_blank=flagged_blank,
                classification=classification,
                order=i,
            )
        )
    return items


def _image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def analyze_panel(
    panel: PanelInventoryItem,
    panels_dir: Path,
    llm: PipelineLLM,
) -> PanelAnalysis:
    """Pass 2 -- one vision call per panel."""
    path = panels_dir / panel.path
    panel_id = Path(panel.path).stem
    try:
        result = llm.complete_json(
            "s0i_panel_vision.md",
            {
                "panel_name": panel.path,
                "panel_order": panel.order,
                "panel_id": panel_id,
            },
            PanelAnalysis,
            role="vision",
            stage_hint=f"stage0i_panel_{panel_id}",
            images=[_image_to_base64(path)],
        )
        return result
    except Exception as exc:  # noqa: BLE001 - tiered failure handling
        logger.warning("panel %s vision call failed: %s", panel.path, exc)
        # Tier 3: call failed -> minimal entry with manual-review note.
        return PanelAnalysis(
            panel_id=panel_id,
            tier="minimal",
            needs_manual_review=True,
            panel_notes=f"manual review required (vision call failed: {type(exc).__name__})",
        )


def resolve_identity(
    analyses: list[PanelAnalysis], llm: PipelineLLM
) -> tuple[list[IdentityCluster], list[dict]]:
    """Pass 3 -- cluster per-panel characters into unique individuals."""
    panel_chars = []
    for a in analyses:
        for c in a.characters:
            entry = dict(c)
            entry["_panel"] = a.panel_id
            panel_chars.append(entry)
    if not panel_chars:
        return [], []

    out = llm.complete_json(
        "s0i_identity.md",
        {"panel_characters_json": json.dumps(panel_chars, indent=2, ensure_ascii=False)},
        _IdentityOutput,
        role="script",
        stage_hint="stage0i_identity",
    )
    return out.characters, out.uncertain_groupings


def synthesize_screenplay(
    analyses: list[PanelAnalysis],
    characters: list[IdentityCluster],
    llm: PipelineLLM,
) -> list[dict]:
    """Pass 4 -- every panel = one shot; consecutive same-setting panels = a scene."""
    analyses_json = [a.model_dump() for a in analyses]
    characters_json = [
        {"provisional_id": c.provisional_id, "canonical_appearance": c.canonical_appearance}
        for c in characters
    ]
    out = llm.complete_json(
        "s0i_synthesis.md",
        {
            "panel_analyses_json": json.dumps(analyses_json, indent=2, ensure_ascii=False),
            "characters_json": json.dumps(characters_json, indent=2, ensure_ascii=False),
        },
        _SynthesisOutput,
        role="script",
        stage_hint="stage0i_synthesis",
    )
    return out.scenes


def _fair_use_score(analyses: list[PanelAnalysis]) -> float:
    """Heuristic fair-use / coverage score (0-1): fraction of panels that were
    fully analyzed vs. flagged manual-review."""
    if not analyses:
        return 0.0
    reviewed = sum(1 for a in analyses if not a.needs_manual_review)
    return round(reviewed / len(analyses), 3)


def _extract_panels(project_dir: Path, upload: Path | None) -> Path:
    """Place panels into ``input/panels/`` -- from a zip upload (extracted to a
    temp dir) or an existing folder. Returns the panels directory."""
    panels_dir = project_dir / _PANELS_DIR
    panels_dir.mkdir(parents=True, exist_ok=True)

    if upload is not None and upload.suffix.lower() == ".zip":
        with zipfile.ZipFile(upload) as zf:
            members = [m for m in zf.namelist() if not m.endswith("/")]
            for m in members:
                ext = Path(m).suffix.lower()
                if ext in _PANEL_EXTS:
                    target = panels_dir / Path(m).name
                    target.write_bytes(zf.read(m))
    elif upload is not None and upload.is_dir():
        for p in natural_sort(list(upload.iterdir())):
            if p.is_file() and p.suffix.lower() in _PANEL_EXTS:
                (panels_dir / p.name).write_bytes(p.read_bytes())
    return panels_dir


def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    upload: str | Path | None = None,
    llm: PipelineLLM | None = None,
) -> dict[str, Any]:
    """Run Stage 0I (IMPORT) for the project at ``project_dir``.

    ``upload`` may be a zip of panels or a folder of panels; it is copied into
    ``input/panels/`` (persisted). If omitted, an existing ``input/panels/`` is
    reused. Raises :class:`Stage0IError` if there are no panels.
    """
    project_dir = Path(project_dir)

    if upload is not None:
        upload = Path(upload)
        if not upload.exists():
            raise Stage0IError(f"upload path not found: {upload}")

    panels_dir = _extract_panels(project_dir, upload)
    inventory = inventory_panels(panels_dir)
    if not inventory:
        raise Stage0IError(
            f"no panels found in {panels_dir} (accepted: .png/.jpg/.jpeg/.webp)"
        )

    # Enforce the 60-panel cap (context safety for synthesis).
    if len(inventory) > _MAX_PANELS:
        inventory = inventory[:_MAX_PANELS]
        logger.warning("panel count exceeds %d -- truncated to the first %d", _MAX_PANELS, _MAX_PANELS)

    (project_dir / _INVENTORY_PATH).write_text(
        json.dumps([i.model_dump() for i in inventory], indent=2), encoding="utf-8"
    )

    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")

    # ---- Pass 2: per-panel vision analysis (sequential -- 8GB VRAM) ------
    analyses_path = project_dir / _PANEL_ANALYSES_PATH
    if analyses_path.exists():
        analyses = [
            PanelAnalysis.model_validate(a)
            for a in json.loads(analyses_path.read_text(encoding="utf-8"))
        ]
    else:
        analyses = [analyze_panel(i, panels_dir, llm) for i in inventory]
        (project_dir / _PANEL_ANALYSES_PATH).write_text(
            json.dumps([a.model_dump() for a in analyses], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ---- Pass 3: character identity resolution --------------------------
    identity_path = project_dir / _IDENTITY_PATH
    if identity_path.exists():
        chars = [
            IdentityCluster.model_validate(c)
            for c in json.loads(identity_path.read_text(encoding="utf-8"))["characters"]
        ]
        uncertain = json.loads(identity_path.read_text(encoding="utf-8")).get(
            "uncertain_groupings", []
        )
    else:
        chars, uncertain = resolve_identity(analyses, llm)
        (project_dir / _IDENTITY_PATH).write_text(
            json.dumps(
                {
                    "characters": [c.model_dump() for c in chars],
                    "uncertain_groupings": uncertain,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    # ---- Pass 4: screenplay synthesis ------------------------------------
    screenplay_path = project_dir / _SYNTHESIS_PATH
    if screenplay_path.exists():
        screenplay = json.loads(screenplay_path.read_text(encoding="utf-8"))
        scenes = screenplay["scenes"]
    else:
        scenes = synthesize_screenplay(analyses, chars, llm)
        screenplay = {"story_id": Blueprint.load(project_dir).story_id, "scenes": scenes}
        screenplay_path.parent.mkdir(parents=True, exist_ok=True)
        screenplay_path.write_text(
            json.dumps(screenplay, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Build a readable script.txt summary from the synthesized screenplay.
    script_parts = []
    for sc in scenes:
        loc = sc.get("location", "unknown")
        script_parts.append(f"--- [SCENE {sc.get('scene_id', '?')}: {loc}] ---\n")
        for shot in sc.get("shots", []):
            desc = shot.get("description", "")
            if desc:
                script_parts.append(desc + "\n")
            for d in shot.get("dialogue", []):
                char = d.get("character_id", "?")
                text = d.get("text", "")
                script_parts.append(f'"{text}" -- {char}\n')
        script_parts.append("\n")
    script_text = "".join(script_parts).strip() + "\n"
    (project_dir / _SCRIPT_PATH).parent.mkdir(parents=True, exist_ok=True)
    (project_dir / _SCRIPT_PATH).write_text(script_text, encoding="utf-8")

    # Fair-use / coverage score + stage completion.
    fair_use = _fair_use_score(analyses)
    (project_dir / _FAIR_USE_PATH).write_text(
        json.dumps({"score": fair_use, "manual_review": [a.panel_id for a in analyses if a.needs_manual_review]}, indent=2),
        encoding="utf-8",
    )

    total_shots = sum(len(sc.get("shots", [])) for sc in scenes)
    scores.record("stage0", "global", "panels", float(len(analyses)))
    scores.record("stage0", "global", "characters", float(len(chars)))
    scores.record("stage0", "global", "scenes", float(len(scenes)))
    scores.record("stage0", "global", "shots", float(total_shots))
    scores.record("stage0", "global", "fair_use_score", fair_use)
    scores.stage_done("stage0")

    bp = Blueprint.load(project_dir)
    bp.title_hash = compute_title_hash(script_text)
    bp.stages["stage0"].status = "done"
    bp.stages["stage0"].ts = now_iso()
    bp.write(project_dir)

    return {
        "stage": "stage0",
        "status": "done",
        "panels": len(analyses),
        "characters": len(chars),
        "scenes": len(scenes),
        "shots": total_shots,
        "fair_use_score": fair_use,
        "screenplay_path": str(screenplay_path),
        "script_path": str(project_dir / _SCRIPT_PATH),
    }
