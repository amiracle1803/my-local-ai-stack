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
