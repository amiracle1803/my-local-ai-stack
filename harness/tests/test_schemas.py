import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from harness.core import models as m

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _schema(name):
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_all_schemas_are_valid_draft7():
    for f in SCHEMA_DIR.glob("*.schema.json"):
        Draft7Validator.check_schema(json.loads(f.read_text(encoding="utf-8")))


def _task():
    return m.Task(
        id="T-20260707-wiki-index-a3f1",
        goal="index the vault",
        state=m.TaskState.PLANNING,
        **{"class": m.Classification(domain="coding", difficulty="hard", risk="low", offline_ok=True)},
        route=m.Route(tier="T2", model="qwen3-8b@ollama", fallbacks=["ornith-9b@ollama"]),
        budget=m.Budget(max_loops=3, max_tokens=200000, max_wall_minutes=45),
        verification=m.Verification(required_score=0.8, verifier="verifier", status="pending"),
        created=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
    )


def test_task_model_matches_schema():
    data = _task().to_json_dict()
    Draft7Validator(_schema("task.schema.json")).validate(data)
    assert data["class"]["domain"] == "coding"  # alias applied


def test_task_json_roundtrip():
    task = _task()
    restored = m.Task.model_validate_json(json.dumps(task.to_json_dict()))
    assert restored.id == task.id
    assert restored.class_.domain == "coding"


def test_handoff_model_matches_schema():
    h = m.Handoff(
        handoff_id="H-20260707-a3f1-04",
        task_id="T-20260707-wiki-index-a3f1",
        step=4,
        state=m.TaskState.EXECUTION,
        **{"from": "manager"},
        to="coder",
        objective="Implement the indexer.",
        acceptance_criteria=["tests pass (evidence: pytest output)"],
        inputs=m.HandoffInputs(error_memory=[]),
        constraints=m.HandoffConstraints(side_effects=[m.SideEffect.WRITE_SCOPED], offline_ok=True),
        budget=m.HandoffBudget(max_tokens=40000, max_wall_minutes=15, max_tool_calls=30),
        route=m.HandoffRoute(tier="T1", model="ornith-9b@ollama"),
        return_schema="schemas/report.schema.json",
    )
    Draft7Validator(_schema("handoff.schema.json")).validate(h.to_json_dict())


def test_report_model_matches_schema():
    r = m.Report(
        handoff_id="H-20260707-a3f1-04",
        status="done",
        summary="did the thing",
        artifacts=[m.ReportArtifact(path="artifacts/04.py", sha256="ab" * 32, kind="code")],
        evidence=[m.ReportEvidence(claim="tests pass", ref="logs/04.txt", kind="test-output")],
        acceptance_self_check=[m.AcceptanceSelfCheck(criterion=0, met=True, evidence_idx=0)],
        confidence=0.85,
        usage=m.Usage(tokens=31200, tool_calls=18, wall_seconds=410),
    )
    Draft7Validator(_schema("report.schema.json")).validate(r.model_dump(mode="json"))


def test_scorecard_model_matches_schema():
    s = m.Scorecard(
        handoff_id="H-20260707-a3f1-04", loop=2, rubric="rubrics/code-step.yaml",
        scores={"correctness": 0.9, "simplicity": 0.7},
        weighted_total=0.88, gate=m.ScoreGate(threshold=0.8, passed=True),
    )
    Draft7Validator(_schema("scorecard.schema.json")).validate(s.model_dump(mode="json"))


def test_verdict_model_matches_schema():
    v = m.Verdict(
        handoff_id="H-20260707-a3f1-04", verifier="verifier", passed=True,
        checks=[m.VerdictCheck(name="pytest", kind="test", passed=True, detail="12 passed")],
        reasons=["all checks green"],
        created=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
    )
    Draft7Validator(_schema("verdict.schema.json")).validate(v.model_dump(mode="json"))


def test_extra_fields_forbidden():
    with pytest.raises(Exception):
        m.Classification(domain="coding", difficulty="hard", risk="low",
                         offline_ok=True, bogus="x")
