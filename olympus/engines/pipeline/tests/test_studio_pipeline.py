"""Studio pipeline smoke tests (no GPU/services required)."""

import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline.blueprint import STAGE_ORDER, create_blueprint


def test_stage_order_matches_studio_ui():
    # Runtime order is the dependency contract; the UI can display historical IDs.
    ui_order = ["stage0", "stage0_dossier", "stage1", "stage1_world", "stage2",
                "stage4", "stage3", "stage1r", "stage3b", "stage3c",
                "stage_vlm_review", "stage5"]
    assert STAGE_ORDER == ui_order


def test_blueprint_identity():
    bp = create_blueprint("Kael holds the pass. " * 20, slug="t1", fps=25, mode="0a")
    assert bp.fps == 24  # snapped 25 -> 24
    assert bp.mode == "0a"
    assert set(bp.stages) == set(STAGE_ORDER)


def test_scene_split_and_names():
    from pipeline.stages import extract_names, split_scenes

    text = "SCENE 1 — Dusk.\n\nKael sharpens his blade.\n\nKael: We hold tonight.\n\nThe shadow wolf circles."
    scenes = split_scenes(text)
    assert len(scenes) >= 1
    assert "Kael" in extract_names(text)


def test_optimizer_requires_smoke_marker_for_gpu_profiles(tmp_path):
    from pipeline.optimizer import HardwareOptimizer

    optimizer = HardwareOptimizer.default()
    decision = optimizer.decide("stage3b", tmp_path)
    assert not decision.accepted
    assert decision.reason == "validated smoke marker missing"
    marker = tmp_path / "optimizer" / "stage3b_default-panel.json"
    marker.parent.mkdir()
    marker.write_text("{}", encoding="utf-8")
    assert optimizer.decide("stage3b", tmp_path).accepted


def test_gate_enforces_audio_first_order(tmp_path):
    """Plan acceptance: Scores.require_stage() enforces
    stage2 -> stage4 -> stage3 -> stage1r (script -> audio -> visuals)."""
    from pipeline.scores import Scores, SkippedStageError

    idx = {s: STAGE_ORDER.index(s) for s in STAGE_ORDER}
    assert idx["stage2"] < idx["stage4"] < idx["stage3"] < idx["stage1r"]

    with Scores(tmp_path / "scores.sqlite") as sc:
        sc.require_stage("stage0")  # first stage always allowed
        try:
            sc.require_stage("stage0_dossier")
            raise AssertionError("gate should block stage before its predecessor")
        except SkippedStageError:
            pass
        try:
            sc.require_stage("stage4")
            raise AssertionError("gate should block stage4 before stage2")
        except SkippedStageError:
            pass
        sc.stage_done("stage0")
        sc.require_stage("stage0_dossier")  # now allowed


def test_faithful_intake_is_verbatim(tmp_path):
    """Mode 0s: seed is stored verbatim; stage0 only splits scenes."""
    import run as runmod

    seed = tmp_path / "seed.txt"
    text = "SCENE 1 — Dusk.\n\nKael: We hold tonight.\n\nSCENE 2 — Dawn.\n\nKael: It held."
    seed.write_text(text, encoding="utf-8")
    projects = tmp_path / "projects"
    runmod.new_project("faithful_t", seed, projects_dir=projects, mode="0s")
    pdir = projects / "faithful_t"
    assert (pdir / "input" / "script.txt").read_text(encoding="utf-8") == text
    assert (pdir / "input" / "source.txt").read_text(encoding="utf-8") == text
    out = runmod.run_stage("faithful_t", "stage0", projects_dir=projects)
    assert out["scenes"] >= 2
    import json

    scenes = json.loads((pdir / "stage0_scenes.json").read_text(encoding="utf-8"))
    assert "Kael: We hold tonight." in scenes[0]["content"]


def test_storyboard_enriches_screenplay_shots(tmp_path):
    """Stage 3 must preserve the timed screenplay's shot contract."""
    import json
    from pipeline.blueprint import create_blueprint
    from pipeline.stages import run_storyboard

    project = tmp_path / "project"
    (project / "screenplay").mkdir(parents=True)
    (project / "scores.sqlite").touch()
    create_blueprint("source", slug="storyboard_t").write(project)
    screenplay = {
        "scenes": [{
            "location": "The pass",
            "summary": "A storm gathers.",
            "shots": [{
                "id": "sh-001-07",
                "description": "A close-up of Kael's hand on the hilt.",
                "narration": "The storm had arrived.",
                "dialogue": "",
                "sfx": "thunder",
            }],
        }]
    }
    (project / "screenplay" / "screenplay.json").write_text(
        json.dumps(screenplay), encoding="utf-8"
    )

    result = run_storyboard(project)

    storyboard = json.loads(
        (project / "storyboard" / "storyboard.json").read_text(encoding="utf-8")
    )
    assert result == {"shots": 1}
    assert storyboard["shot_detail"][0]["id"] == "sh-001-07"
    assert storyboard["shot_detail"][0]["narration"] == "The storm had arrived."
    assert storyboard["shot_detail"][0]["sfx"] == "thunder"


def test_canonical_artifact_identity():
    from pipeline.identity import canonical_name

    assert canonical_name("bloodline", "sh-001-02", "panel", "png") == (
        "bloodline_sc001_sh002_panel_v001.png"
    )


def test_review_unavailable_does_not_pass(monkeypatch, tmp_path):
    from pipeline import stages

    panel_dir = tmp_path / "panels"
    panel_dir.mkdir()
    stages.render_panel(panel_dir / "sh_001_01.png", "shot", seed="test")
    monkeypatch.setattr(
        "pipeline.nim_vision.review_image",
        lambda *_args, **_kwargs: {"available": False, "verdict": "UNAVAILABLE", "score": 0},
    )
    (tmp_path / "scores.sqlite").touch()
    from pipeline.blueprint import create_blueprint

    create_blueprint("source", slug="review_t").write(tmp_path)
    try:
        stages.run_review(tmp_path)
    except RuntimeError as exc:
        assert "blocked" in str(exc)
    else:
        raise AssertionError("unavailable review must block stage5")


def test_tts_provider_manifest_prefers_chatterbox():
    from pipeline.voice_client import provider_status

    status = provider_status()
    assert status["recommended"] == "chatterbox-turbo"
    assert "exclusive lock" in status["gpu_policy"]
