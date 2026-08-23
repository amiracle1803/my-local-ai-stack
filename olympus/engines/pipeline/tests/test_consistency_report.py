"""Self-critique loop tests: aggregate panel + clip consistency findings into a
per-character report with proposed fixes (no LLM, no GPU)."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.consistency_report import build_report, write_report
from pipeline.schemas.worldbible import Appearance, Character, WorldBible, WorldBibleMeta


def _make_project(tmp_path: Path) -> Path:
    p = tmp_path / "proj"

    # screenplay: shot -> characters_in_frame
    (p / "screenplay").mkdir(parents=True)
    (p / "screenplay" / "screenplay.json").write_text(
        json.dumps({
            "scenes": [{
                "id": "sc-001",
                "shots": [
                    {"id": "sh-001-01", "characters_in_frame": ["rei"]},
                    {"id": "sh-001-02", "characters_in_frame": ["rei"]},
                    {"id": "sh-001-03", "characters_in_frame": ["mika"]},
                ],
            }]
        })
    )

    # panel sidecar with an appearance mismatch on sh-001-01 (Rei)
    (p / "panels" / "blk-001").mkdir(parents=True)
    (p / "panels" / "blk-001" / "sh-001-01.json").write_text(json.dumps({
        "vision": {"appearance_matches": False, "appearance_issue": "eyes", "judge": "local"},
    }))
    # inconclusive panel should be ignored
    (p / "panels" / "blk-001" / "sh-001-03.json").write_text(json.dumps({
        "vision": {"inconclusive": True, "error": "timeout"},
    }))

    # clip review with low character_consistency on sh-001-02 (Rei)
    (p / "reviews").mkdir(parents=True)
    (p / "reviews" / "vlm_review.json").write_text(json.dumps({
        "reviews": {
            "sh-001-02": {"details": {"character_consistency": 5.0}, "verdict": "REVIEW"},
            "sh-001-01": {"details": {"character_consistency": 9.0}, "verdict": "PASS"},
        },
    }))

    # world bible with canonical characters
    wb = WorldBible(
        story_id="s",
        characters=[
            Character(id="rei", name="Rei", appearance=Appearance(hair="black", eyes="dark")),
            Character(id="mika", name="Mika", appearance=Appearance(hair="silver")),
        ],
        meta=WorldBibleMeta(),
    )
    (p / "worldbible").mkdir(parents=True)
    (p / "worldbible" / "world_bible.json").write_text(wb.model_dump_json())
    return p


def test_build_report_aggregates_findings(tmp_path):
    p = _make_project(tmp_path)
    report = build_report(p)

    assert report["summary"]["panel_mismatches"] == 1
    assert report["summary"]["low_consistency_clips"] == 1
    assert report["summary"]["characters_off_model"] == 1  # only Rei

    rei = report["characters"]["rei"]
    assert rei["name"] == "Rei"
    assert "hair=black" in rei["canonical_appearance"]
    # panel mismatch + clip drift both land on Rei
    assert [f["shot"] for f in rei["panel_mismatches"]] == ["sh-001-01"]
    assert [f["shot"] for f in rei["low_consistency_clips"]] == ["sh-001-02"]
    assert any("sh-001-01" in fix and "eyes" in fix for fix in rei["proposed_fixes"])
    assert any("sh-001-02" in fix for fix in rei["proposed_fixes"])

    # Mika has no findings (her panel was inconclusive, no clip)
    assert "mika" not in report["characters"]


def test_build_report_empty_when_no_findings(tmp_path):
    p = tmp_path / "empty"
    (p / "screenplay").mkdir(parents=True)
    (p / "screenplay" / "screenplay.json").write_text(json.dumps({"scenes": []}))
    report = build_report(p)
    assert report["summary"] == {
        "characters_off_model": 0, "panel_mismatches": 0, "low_consistency_clips": 0,
    }
    assert report["characters"] == {}


def test_write_report_writes_file(tmp_path):
    p = _make_project(tmp_path)
    out = write_report(p)
    assert out.exists()
    data = json.loads(out.read_text())
    assert "rei" in data["characters"]
