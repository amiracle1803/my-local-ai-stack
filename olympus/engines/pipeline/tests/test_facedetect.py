"""Anime-face bbox detector (design 3C.4): mouth-bbox math + a real-cascade
smoke test."""

import pytest

from pipeline.facedetect import CASCADE_PATH, _mouth_bbox, detect_faces


def test_mouth_bbox_is_lower_third_centered_half_width():
    mouth = _mouth_bbox(x=100, y=200, w=90, h=120)
    # lower third of height, flush to the bottom of the face box
    assert mouth["h"] == 40
    assert mouth["y"] == 200 + 120 - 40  # == 280
    # half the face width, centered
    assert mouth["w"] == 45
    assert mouth["x"] == 100 + (90 - 45) // 2  # == 122


def test_mouth_bbox_stays_within_face_box():
    face = {"x": 10, "y": 20, "w": 61, "h": 61}
    mouth = _mouth_bbox(**face)
    assert mouth["x"] >= face["x"]
    assert mouth["y"] >= face["y"]
    assert mouth["x"] + mouth["w"] <= face["x"] + face["w"]
    assert mouth["y"] + mouth["h"] <= face["y"] + face["h"]


def test_detect_faces_missing_image_raises():
    with pytest.raises(FileNotFoundError):
        detect_faces("/nonexistent/path/does-not-exist.png")


@pytest.mark.skipif(
    not CASCADE_PATH.exists(),
    reason=f"lbpcascade_animeface.xml not present at {CASCADE_PATH}",
)
def test_detect_faces_on_real_panel():
    """Integration test: run the real cascade on a generated close-up panel
    from the lantern-test project. Skips cleanly if the cascade asset or the
    panel isn't on disk (e.g. a fresh checkout before the one-time cascade
    download)."""
    from pathlib import Path

    engine_root = Path(__file__).resolve().parent.parent
    panel = (
        engine_root
        / "projects/lantern-test/panels/blk-001/sh-001-03.png"
    )
    if not panel.exists():
        pytest.skip(f"test panel not present at {panel}")

    faces = detect_faces(panel)
    assert isinstance(faces, list)
    assert len(faces) >= 1
    face = faces[0]
    assert {"x", "y", "w", "h", "mouth_bbox"} <= face.keys()
    mouth = face["mouth_bbox"]
    assert {"x", "y", "w", "h"} <= mouth.keys()
    # mouth stays inside the face box
    assert mouth["x"] >= face["x"]
    assert mouth["x"] + mouth["w"] <= face["x"] + face["w"]
    assert mouth["y"] + mouth["h"] <= face["y"] + face["h"]
