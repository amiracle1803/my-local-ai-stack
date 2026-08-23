"""Self-critique loop -- aggregate on-model consistency findings into a report.

Reads the deterministic findings already produced by the QC gates and folds them
into one per-character report with proposed fixes, closing the "detect
inconsistencies and propose improvements" loop from the original spec:

- **Panel appearance mismatches** (``panels/*/<shot>.json`` -> ``vision``):
  the extract-then-compare gate records ``appearance_matches`` + ``appearance_issue``
  per panel.
- **Clip on-model drift** (``reviews/vlm_review.json``): the clip review records
  a ``character_consistency`` score per shot.

No LLM calls -- this only aggregates the evidence the gates already computed.
Writes ``consistency/consistency_report.json``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._util import load_screenplay, now_iso, read_json, _shots_by_id

_CLIP_CONSISTENCY_MIN = 7.0  # below this the clip is flagged for on-model drift


def build_report(project_dir: str | Path) -> dict[str, Any]:
    """Aggregate panel + clip consistency findings into a per-character report."""
    project_dir = Path(project_dir)

    shots = _shots_by_id(load_screenplay(project_dir)) if (
        project_dir / "screenplay" / "screenplay.json"
    ).exists() else {}

    # Canonical names + appearance specs (world bible, optional).
    id_to_name: dict[str, str] = {}
    id_to_spec: dict[str, str] = {}
    wb_path = project_dir / "worldbible" / "world_bible.json"
    if wb_path.exists():
        try:
            from .schemas.worldbible import WorldBible

            wb = WorldBible.model_validate_json(wb_path.read_text(encoding="utf-8"))
            id_to_name = {c.id: c.name for c in wb.characters}
            id_to_spec = {c.id: c.appearance_spec() for c in wb.characters}
        except (OSError, ValueError):
            pass

    # 1. Panel appearance mismatches.
    panel_findings: dict[str, list[dict[str, Any]]] = {}
    panels_root = project_dir / "panels"
    if panels_root.is_dir():
        for sidecar in panels_root.rglob("*.json"):
            try:
                data = read_json(sidecar)
            except (OSError, ValueError):
                continue
            vision = data.get("vision") or {}
            if vision.get("inconclusive"):
                continue  # transport error, no verdict
            if vision.get("appearance_matches", True):
                continue
            issue = vision.get("appearance_issue") or "appearance mismatch"
            sid = sidecar.stem
            for cid in shots.get(sid, {}).get("characters_in_frame", []) or []:
                panel_findings.setdefault(cid, []).append({"shot": sid, "issue": issue})

    # 2. Clip on-model drift (low character_consistency).
    clip_findings: dict[str, list[dict[str, Any]]] = {}
    vlm_path = project_dir / "reviews" / "vlm_review.json"
    if vlm_path.exists():
        try:
            reviews = read_json(vlm_path).get("reviews", {})
        except (OSError, ValueError):
            reviews = {}
        for sid, r in reviews.items():
            score = (r.get("details") or {}).get("character_consistency")
            if score is None or score >= _CLIP_CONSISTENCY_MIN:
                continue
            for cid in shots.get(sid, {}).get("characters_in_frame", []) or []:
                clip_findings.setdefault(cid, []).append(
                    {"shot": sid, "character_consistency": score}
                )

    # 3. Per-character aggregation + proposed fixes.
    characters: dict[str, dict[str, Any]] = {}
    for cid in sorted(set(panel_findings) | set(clip_findings)):
        panel = panel_findings.get(cid, [])
        clip = clip_findings.get(cid, [])
        fixes: list[str] = []
        for p in panel:
            fixes.append(
                f"re-render {p['shot']} with the canonical appearance ({p['issue']}), "
                "or correct the world bible if the panel is actually on-model"
            )
        for c in clip:
            fixes.append(
                f"review {c['shot']} for on-model drift "
                f"(character_consistency {c['character_consistency']:.1f}/10)"
            )
        characters[cid] = {
            "name": id_to_name.get(cid, cid),
            "canonical_appearance": id_to_spec.get(cid, ""),
            "panel_mismatches": panel,
            "low_consistency_clips": clip,
            "proposed_fixes": fixes,
        }

    return {
        "generated_at": now_iso(),
        "characters": characters,
        "summary": {
            "characters_off_model": len(characters),
            "panel_mismatches": sum(len(v) for v in panel_findings.values()),
            "low_consistency_clips": sum(len(v) for v in clip_findings.values()),
        },
    }


def write_report(project_dir: str | Path) -> Path:
    """Build the consistency report and write ``consistency/consistency_report.json``."""
    from ._util import write_json

    project_dir = Path(project_dir)
    report = build_report(project_dir)
    out = project_dir / "consistency" / "consistency_report.json"
    write_json(out, report)
    return out
