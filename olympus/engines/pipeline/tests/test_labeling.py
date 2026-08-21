"""Labeling standard: human-readable panel/clip labels index."""
import json
from pathlib import Path

from pipeline.labeling import (
    build_labels,
    shot_label,
    shot_slug,
    write_labels,
)


def _mk_project(tmp_path: Path) -> Path:
    """Create a minimal project with one scene/shot, a panel, and a clip."""
    proj = tmp_path / "proj"
    (proj / "screenplay").mkdir(parents=True)
    (proj / "worldbible").mkdir(parents=True)
    (proj / "storyboard").mkdir(parents=True)

    (proj / "blueprint.json").write_text(
        json.dumps({"story_id": "river", "slug": "river"}), encoding="utf-8")

    (proj / "worldbible" / "world_bible.json").write_text(json.dumps({
        "locations": [{"id": "loc-shrine", "name": "Shrine"}],
        "characters": [{"id": "kana", "name": "Kana"}],
    }), encoding="utf-8")

    (proj / "screenplay" / "screenplay.json").write_text(json.dumps({
        "story_id": "river",
        "scenes": [{
            "id": "sc-001", "location": "loc-shrine", "time_of_day": "morning",
            "summary": "Kana arrives.", "shots": [{
                "id": "sh-001-01", "composition": "wide shot, low angle",
                "characters_in_frame": ["kana"], "beat": "Kana arrives at the shrine.",
                "narration": {"text": "Kana steps into silence."},
            }],
        }],
    }), encoding="utf-8")

    (proj / "storyboard" / "storyboard.json").write_text(
        json.dumps({"blocks": []}), encoding="utf-8")

    # a fake panel + fake clip
    panel_dir = proj / "panels" / "blk-001"
    panel_dir.mkdir(parents=True)
    (panel_dir / "sh-001-01.png").write_bytes(b"\x89PNG")
    (proj / "clips").mkdir()
    (proj / "clips" / "sh-001-01_director_00001.mp4").write_bytes(b"mp4")
    return proj


def test_shot_label_readable():
    shot = {"id": "sh-001-01", "composition": "wide shot, low angle",
            "characters_in_frame": ["kana"], "beat": "Kana arrives at the shrine."}
    scene = {"id": "sc-001", "location": "loc-shrine", "time_of_day": "morning"}
    wb = {"locations": [{"id": "loc-shrine", "name": "Shrine"}],
          "characters": [{"id": "kana", "name": "Kana"}]}
    label = shot_label(shot, scene, wb)
    assert "SC-001" in label
    assert "Shrine" in label
    assert "Morning" in label
    assert "Kana arrives" in label


def test_shot_slug_filesystem_safe():
    shot = {"id": "sh-001-01", "beat": "Kana arrives at the shrine!!"}
    scene = {"id": "sc-001", "location": "loc-shrine", "time_of_day": "morning"}
    wb = {"locations": [{"id": "loc-shrine", "name": "Shrine"}]}
    slug = shot_slug(shot, scene, wb)
    assert slug.startswith("sc-001-")
    assert "shrine" in slug
    assert "morning" in slug
    # no punctuation or unsafe chars
    assert slug == slug.replace("!", "").replace(" ", "-")
    assert all(c.isalnum() or c == "-" for c in slug)


def test_build_labels_indexes_panels_and_clips(tmp_path):
    proj = _mk_project(tmp_path)
    labels = build_labels(proj)
    assert labels["story_id"] == "river"
    assert len(labels["scenes"]) == 1
    assert len(labels["panels"]) == 1
    assert len(labels["clips"]) == 1
    assert labels["panels"][0]["file"] == "panels/blk-001/sh-001-01.png"
    assert labels["clips"][0]["file"].endswith(".mp4")
    assert "Kana arrives" in labels["panels"][0]["label"]


def test_write_labels_writes_three_files(tmp_path):
    proj = _mk_project(tmp_path)
    out = write_labels(proj)
    assert out.name == "labels.json"
    assert (proj / "labels.json").exists()
    assert (proj / "labels.txt").exists()
    assert (proj / "labels.html").exists()
    txt = (proj / "labels.txt").read_text(encoding="utf-8")
    assert "sh-001-01" in txt and "Kana arrives" in txt
    html_doc = (proj / "labels.html").read_text(encoding="utf-8")
    assert "<table>" in html_doc


def test_build_labels_missing_worldbible(tmp_path):
    proj = _mk_project(tmp_path)
    (proj / "worldbible" / "world_bible.json").unlink()
    labels = build_labels(proj)
    # falls back to raw ids, no crash
    assert len(labels["panels"]) == 1
    assert labels["panels"][0]["location"] == "loc-shrine"
