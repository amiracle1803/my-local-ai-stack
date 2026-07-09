"""run.py CLI: project creation, pollution guard on run, stage gating."""

import pytest

import run
from pipeline.blueprint import StoryPollutionError
from pipeline.scores import SkippedStageError

SCRIPT = "Rin walked into the academy at dawn. " * 30


def _make_script(tmp_path):
    p = tmp_path / "story.txt"
    p.write_text(SCRIPT, encoding="utf-8")
    return p


def test_new_project_creates_valid_dir(tmp_path):
    script = _make_script(tmp_path)
    projects = tmp_path / "projects"
    proj = run.new_project("demo", script, fps=30, projects_dir=projects)

    assert proj == projects / "demo"
    assert (proj / "blueprint.json").exists()
    assert (proj / "input" / "script.txt").exists()
    assert (proj / "scores.sqlite").exists()

    from pipeline.blueprint import Blueprint

    bp = Blueprint.load(proj)
    assert bp.slug == "demo"
    assert bp.fps == 30
    assert (proj / "input" / "script.txt").read_text(encoding="utf-8") == SCRIPT


def test_new_project_refuses_duplicate(tmp_path):
    script = _make_script(tmp_path)
    projects = tmp_path / "projects"
    run.new_project("demo", script, fps=24, projects_dir=projects)
    with pytest.raises(FileExistsError):
        run.new_project("demo", script, fps=24, projects_dir=projects)


def test_run_stage_pollution_guard_trips(tmp_path):
    script = _make_script(tmp_path)
    projects = tmp_path / "projects"
    proj = run.new_project("demo", script, fps=24, projects_dir=projects)
    # Swap the script.
    (proj / "input" / "script.txt").write_text("different story entirely", encoding="utf-8")
    with pytest.raises(StoryPollutionError):
        run.run_stage("demo", "stage1", projects_dir=projects)


def test_run_stage_gate_blocks_before_notimplemented(tmp_path):
    script = _make_script(tmp_path)
    projects = tmp_path / "projects"
    run.new_project("demo", script, fps=24, projects_dir=projects)
    # stage1 without stage0 done -> gate trips (not NotImplementedError).
    with pytest.raises(SkippedStageError):
        run.run_stage("demo", "stage1", projects_dir=projects)


def test_run_stage0_reaches_stub(tmp_path):
    script = _make_script(tmp_path)
    projects = tmp_path / "projects"
    run.new_project("demo", script, fps=24, projects_dir=projects)
    # stage0 has no predecessor -> passes gate -> hits the M1+ stub.
    with pytest.raises(NotImplementedError):
        run.run_stage("demo", "stage0", projects_dir=projects)


def test_report_returns_ledger(tmp_path):
    script = _make_script(tmp_path)
    projects = tmp_path / "projects"
    run.new_project("demo", script, fps=24, projects_dir=projects)
    data = run.report("demo", projects_dir=projects)
    assert data["blueprint"]["slug"] == "demo"
    assert "stage0" in data["scores"]["stages"]
