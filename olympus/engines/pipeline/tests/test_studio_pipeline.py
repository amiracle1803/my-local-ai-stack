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
