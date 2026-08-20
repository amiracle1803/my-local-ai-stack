"""Tests for the self-critique loop (Task 5)."""

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

from pipeline.stage_critique import (
    _collect_artifacts,
    _truncate,
    CritiqueIssue,
    CritiqueSuggestion,
    StageCritiqueResult,
    STAGE_PURPOSES,
    run_stage_critique,
    should_retry_stage,
    get_retry_actions,
)
from pipeline.config import PipelineConfig


def test_truncate():
    assert _truncate("short", 10) == "short"
    long = "a" * 100
    assert _truncate(long, 50) == "a" * 50 + " ...[truncated]"


def test_stage_purposes_complete():
    expected_stages = [
        "stage0", "stage1", "stage1_world", "stage1r", "stage3",
        "stage2", "stage3b", "stage4", "stage3c", "stage_vlm_review", "stage5"
    ]
    assert list(STAGE_PURPOSES.keys()) == expected_stages
    for stage, purpose in STAGE_PURPOSES.items():
        assert purpose, f"{stage} has empty purpose"


def test_collect_artifacts_missing_dir(tmp_path):
    """_collect_artifacts returns empty dict for non-existent paths."""
    artifacts = _collect_artifacts(tmp_path, "stage0")
    assert artifacts == {}


def test_critique_result_model():
    """StageCritiqueResult model validates correctly."""
    result = StageCritiqueResult(
        stage_name="stage1",
        consistency_score=0.95,
        critical_issues=[],
        warnings=[CritiqueIssue(
            type="character",
            description="Minor voice mismatch",
            severity="minor",
            artifact_ref="voices.json",
        )],
        suggested_fixes=[CritiqueSuggestion(
            stage="stage1",
            action="tweak_prompt",
            details="Adjust voice prompt for Rin",
        )],
        passes=True,
    )
    assert result.passes is True
    assert result.consistency_score == 0.95
    assert len(result.warnings) == 1


def test_critique_result_rejects_invalid_score():
    with pytest.raises(ValueError):
        StageCritiqueResult(stage_name="stage1", consistency_score=1.5)


def test_should_retry_stage():
    config = PipelineConfig.load()

    # Critical issue -> retry
    result = StageCritiqueResult(
        stage_name="stage1",
        consistency_score=0.9,
        critical_issues=[CritiqueIssue(type="character", description="...", severity="critical", artifact_ref="x")],
        passes=False,
    )
    assert should_retry_stage(result, config) is True

    # Score below threshold -> retry
    result2 = StageCritiqueResult(
        stage_name="stage1",
        consistency_score=0.5,
        critical_issues=[],
        passes=False,
    )
    assert should_retry_stage(result2, config) is True

    # Passes -> no retry
    result3 = StageCritiqueResult(
        stage_name="stage1",
        consistency_score=0.8,
        critical_issues=[],
        passes=True,
    )
    assert should_retry_stage(result3, config) is False


def test_get_retry_actions():
    result = StageCritiqueResult(
        stage_name="stage1",
        consistency_score=0.5,
        critical_issues=[],
        suggested_fixes=[
            CritiqueSuggestion(stage="stage1", action="regenerate", details="..."),
            CritiqueSuggestion(stage="stage1", action="tweak_prompt", details="fix voice"),
        ],
        passes=False,
    )
    actions = get_retry_actions(result)
    assert "rerun stage1" in actions
    assert "tweak prompt for stage1: fix voice" in actions


def test_run_stage_critique_transport_error(tmp_path):
    """run_stage_critique handles LLM transport errors gracefully."""
    # Create minimal project structure
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "script.txt").write_text("A test script about a hero.")

    config = PipelineConfig.load()
    mock_llm = MagicMock()
    mock_llm.complete_json.side_effect = Exception("Ollama connection refused")

    from pipeline.stage_critique import run_stage_critique

    result = run_stage_critique(tmp_path, "stage1", mock_llm, config)

    assert result.stage_name == "stage1"
    assert result.consistency_score == 0.0
    assert result.passes is False
    assert len(result.critical_issues) == 1
    assert result.critical_issues[0].type == "technical"
    assert "Ollama connection refused" in result.critical_issues[0].description