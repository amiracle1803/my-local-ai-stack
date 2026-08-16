"""Scorecard gating: skipped stages are blocked structurally."""

import pytest

from pipeline.scores import MANDATORY_METRICS, Scores, SkippedStageError


def _scores(tmp_path):
    return Scores(tmp_path / "scores.sqlite")


def test_first_stage_needs_no_predecessor(tmp_path):
    with _scores(tmp_path) as s:
        s.require_stage("stage0")  # must not raise


def test_gate_blocks_when_predecessor_not_done(tmp_path):
    with _scores(tmp_path) as s:
        with pytest.raises(SkippedStageError):
            s.require_stage("stage1")  # stage0 not done


def test_gate_blocks_when_done_but_metrics_missing(tmp_path):
    with _scores(tmp_path) as s:
        s.stage_done("stage0")  # marker but no proof metric
        with pytest.raises(SkippedStageError):
            s.require_stage("stage1")


def test_gate_passes_when_predecessor_complete(tmp_path):
    with _scores(tmp_path) as s:
        for metric in MANDATORY_METRICS["stage0"]:
            s.record("stage0", "global", metric, 100.0)
        s.stage_done("stage0")
        s.require_stage("stage1")  # must not raise


def test_record_and_report(tmp_path):
    with _scores(tmp_path) as s:
        s.record("stage0", "global", "structure_completeness", 95.0)
        s.stage_done("stage0")
        rep = s.report()
        assert rep["stages"]["stage0"]["done"] is True
        assert rep["stages"]["stage0"]["complete"] is True
        assert rep["stages"]["stage0"]["metrics"]["structure_completeness"] == 95.0
        assert rep["stages"]["stage1"]["done"] is False


def test_persistence_across_connections(tmp_path):
    db = tmp_path / "scores.sqlite"
    s1 = Scores(db)
    s1.record("stage0", "global", "structure_completeness", 88.0)
    s1.stage_done("stage0")
    s1.close()
    s2 = Scores(db)
    assert s2.is_done("stage0")
    assert s2.has_metric("stage0", "structure_completeness")
    s2.close()


def test_unknown_stage_raises(tmp_path):
    with _scores(tmp_path) as s:
        with pytest.raises(ValueError):
            s.require_stage("stage99")


def test_stage3c_mandatory_metric_is_ltx_rendered():
    """The previous mandatory metric for stage3c was ``lipsync_overlap_avg``,
    but stage3c hardcodes that to 0.0 (lip-sync is an unimplemented
    contingency, design Stage 3C.5). The gate was vacuous -- any 0.0
    satisfied a presence check. The mandatory metric is now
    ``ltx_rendered`` (proves animation actually ran)."""
    assert "ltx_rendered" in MANDATORY_METRICS["stage3c"]
    assert "lipsync_overlap_avg" not in MANDATORY_METRICS["stage3c"]


def test_stage4_runs_when_stage3c_proves_rendered(tmp_path):
    """Downstream gate for stage4 must pass once stage3c actually rendered
    a clip (ltx_rendered >= 1), not on the vacuous lipsync_overlap_avg=0.0."""
    with _scores(tmp_path) as s:
        # Simulate stage3b/3c completion in the documented order.
        s.record("stage3b", "global", "prompt_adherence_avg", 0.92)
        s.stage_done("stage3b")
        s.record("stage3c", "global", "ltx_rendered", 3.0)
        s.stage_done("stage3c")
        # stage_vlm_review precedes stage4 per STAGE_ORDER; mark it done too
        # so stage4's require_stage call has its full chain satisfied.
        s.stage_done("stage_vlm_review")
        s.require_stage("stage4")  # must not raise
