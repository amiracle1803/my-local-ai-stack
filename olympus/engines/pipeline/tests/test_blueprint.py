"""Blueprint creation, fps snapping, and the story-pollution guard."""

import pytest

from pipeline.blueprint import (
    STAGE_ORDER,
    Blueprint,
    StoryPollutionError,
    compute_title_hash,
    create_blueprint,
    snap_fps,
    verify_story_guard,
)

SCRIPT = "Rin walked into the academy. " * 40  # ~200 words


def test_create_blueprint_basic():
    bp = create_blueprint(SCRIPT, slug="my-story", fps=24)
    assert bp.slug == "my-story"
    assert len(bp.story_id) == 36  # uuid4
    assert bp.title_hash == compute_title_hash(SCRIPT)
    assert set(bp.stages) == set(STAGE_ORDER)
    assert all(e.status == "pending" for e in bp.stages.values())


@pytest.mark.parametrize(
    "given,expected",
    [(24, 24), (30, 30), (60, 60), (25, 24), (28, 30), (50, 60), (45, 30),
     (10, 24), (100, 60), (26, 24)],
)
def test_fps_snapping(given, expected):
    assert snap_fps(given) == expected


def test_create_blueprint_snaps_fps():
    bp = create_blueprint(SCRIPT, slug="s", fps=25)
    assert bp.fps == 24


def test_title_hash_normalizes_whitespace():
    # Whitespace differences must not change the hash (normalization).
    assert compute_title_hash("Hello   world\n\n") == compute_title_hash("hello world")


def test_roundtrip_write_load(tmp_path):
    bp = create_blueprint(SCRIPT, slug="rt", fps=30)
    bp.write(tmp_path)
    loaded = Blueprint.load(tmp_path)
    assert loaded.story_id == bp.story_id
    assert loaded.title_hash == bp.title_hash
    assert loaded.fps == 30


def _make_project(tmp_path, script=SCRIPT):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "script.txt").write_text(script, encoding="utf-8")
    bp = create_blueprint(script, slug="guard", fps=24)
    bp.write(tmp_path)
    return bp


def test_pollution_guard_passes_when_unchanged(tmp_path):
    bp = _make_project(tmp_path)
    verified = verify_story_guard(tmp_path)  # must not raise
    assert verified.story_id == bp.story_id


def test_pollution_guard_trips_on_swapped_script(tmp_path):
    _make_project(tmp_path)
    # Swap the script underneath the project.
    (tmp_path / "input" / "script.txt").write_text(
        "A COMPLETELY different story about robots.", encoding="utf-8"
    )
    with pytest.raises(StoryPollutionError):
        verify_story_guard(tmp_path)


def test_pollution_guard_trips_when_script_missing(tmp_path):
    _make_project(tmp_path)
    (tmp_path / "input" / "script.txt").unlink()
    with pytest.raises(StoryPollutionError):
        verify_story_guard(tmp_path)
