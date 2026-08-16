"""Phase 1 manager-loop tests — fully mocked port, all pass with Ollama OFF.

A FakePort returns scripted JSON per agent (keyed by the `agent=` argument the loop
passes), so run_task is driven deterministically. Memory + runs are redirected to tmp.
"""

from __future__ import annotations

import inspect
import json

import pytest

from harness.core import loop, memory as memmod
from harness.core.loop import (
    RetryWithoutErrorRef,
    build_payload,
    run_task,
)
from harness.core.models import Route, TaskState
from harness.core.registry import load_registry
from harness.ports.model_port import Result


# --- fake port -----------------------------------------------------------

def _result(d: dict) -> Result:
    return Result(ok=True, text=json.dumps(d), model_id="fake@test", rung=0,
                  outcome="ok", usage={"tokens_in": 3, "tokens_out": 5}, data=d)


class FakePort:
    def __init__(self, registry, scripts: dict, repeat_when_empty: bool = False):
        self.registry = registry
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.repeat_when_empty = repeat_when_empty
        self._last: dict = {}
        self.calls: list[tuple] = []   # (agent, role)

    def generate(self, role, messages, schema=None, budget=None, *, task_id, agent=None, think=None):
        key = agent or role
        self.calls.append((key, role))
        queue = self.scripts.get(key, [])
        if not queue:
            if self.repeat_when_empty and key in self._last:
                return _result(self._last[key])
            raise AssertionError(f"no scripted response for agent={key} role={role}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        self._last[key] = item
        return _result(item)

    def close(self):
        pass

    def role_calls(self, agent: str) -> list:
        return [role for a, role in self.calls if a == agent]


# --- scripted json builders ----------------------------------------------

def _classify(domain="writing", difficulty="easy"):
    return {"domain": domain, "difficulty": difficulty, "risk": "low", "offline_ok": True}


def _plan(objective="Write summary.md", crit=None):
    return {
        "goal_restated": "do the thing",
        "steps": [{
            "objective": objective, "agent": "executor",
            "acceptance_criteria": crit or ["summary.md exists (evidence: artifact)",
                                            "summary.md has >= 3 lines (evidence: line count)"],
            "side_effects": ["write-scoped"],
        }],
        "plan_acceptance": ["summary.md delivered"],
        "risk_note": "low",
    }


def _write(name="summary.md", content="alpha\nbeta\ngamma\ndelta\nepsilon"):
    return {"action": "write_artifact", "args": {"name": name, "content": content}}


def _read(path="harness/registry/routing.yaml"):
    return {"action": "read_file", "args": {"path": path}}


def _finish(report=None):
    rep = report if report is not None else {
        "status": "done", "summary": "wrote the artifact", "confidence": 0.9, "concerns": []}
    return {"action": "finish", "args": {}, "report": rep}


def _issues(*, blocking=False):
    if blocking:
        return {"issues": [{"severity": "blocking", "criterion": "0",
                            "evidence": "missing", "suggested_direction": "add it"}]}
    return {"issues": []}


def _score(total=0.9):
    return {"handoff_id": "x", "loop": 0, "rubric": "r",
            "scores": {"correctness": total, "criteria_coverage": total,
                       "evidence_quality": total, "simplicity": total,
                       "constraint_compliance": total},
            "weighted_total": total, "gate": {"threshold": 0.80, "passed": total >= 0.80}}


def _verdict(passed=True):
    return {"handoff_id": "x", "verifier": "verifier", "passed": passed,
            "checks": [], "reasons": ["scripted"], "created": "2026-07-07T00:00:00Z"}


# --- fixtures ------------------------------------------------------------

def _bind_memory_dir(orig, memdir):
    """Inject memory_dir=memdir only when the caller didn't already supply it (internal
    calls pass it positionally, so a naive partial would double-bind)."""
    sig = inspect.signature(orig)

    def wrapper(*args, **kwargs):
        bound = sig.bind_partial(*args, **kwargs)
        if "memory_dir" not in bound.arguments:
            kwargs["memory_dir"] = memdir
        return orig(*args, **kwargs)
    return wrapper


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect memory + runs to tmp so tests never touch the repo tree."""
    mem = tmp_path / "memory"
    for fn in ("ensure_memory", "write_error", "write_episode", "find_errors"):
        orig = getattr(memmod, fn)
        monkeypatch.setattr(loop.memory, fn, _bind_memory_dir(orig, mem))
    runs = tmp_path / "runs"
    return runs, mem


def _run(scripts, env, **kw):
    runs, _ = env
    reg = load_registry()
    port = FakePort(reg, scripts, repeat_when_empty=kw.pop("repeat", False))
    task = run_task("Write a haiku summary and save summary.md",
                    port=port, registry=reg, runs_dir=runs,
                    emit=lambda s: None, **kw)
    return task, port, runs


# --- 1. happy path -------------------------------------------------------

def test_happy_path_reaches_delivery(env):
    scripts = {
        "classifier": [_classify()],
        "planner": [_plan()],
        "critic": [_issues(), _issues()],        # plan gate, then step 0
        "executor": [_write(), _finish()],
        "scorer": [_score(0.9)],
        "verifier": [_verdict(True)],
    }
    task, port, runs = _run(scripts, env)
    assert task.state is TaskState.DELIVERY
    art = runs / task.id / "artifacts" / "summary.md"
    assert art.exists()
    assert len(art.read_text().splitlines()) == 5
    assert (runs / task.id / "reports" / "final-report.md").exists()
    assert (runs / task.id / "plan" / "plan.json").exists()


# --- 2. retry writes error first -----------------------------------------

def test_retry_payload_requires_error_ref(env):
    reg = load_registry()
    route = Route(tier="T1", model="qwen2.5-7b@ollama", fallbacks=[])
    step = {"objective": "x", "acceptance_criteria": ["c"]}

    class _T:  # minimal stand-in with the attrs build_payload reads
        id = "T-20260707-x-abcd"
        goal = "g"
    with pytest.raises(RetryWithoutErrorRef):
        build_payload(step, 0, _T(), route, is_retry=True, error_memory=[])
    # a retry WITH a ref is accepted
    ok = build_payload(step, 0, _T(), route, is_retry=True, error_memory=["memory/errors/err-x.md"])
    assert ok["inputs"]["error_memory"] == ["memory/errors/err-x.md"]


def test_failed_attempt_writes_error_before_retry(env):
    # attempt0 fails (mid band, verifier fail) -> error written -> attempt1 passes.
    scripts = {
        "classifier": [_classify()],
        "planner": [_plan()],
        "critic": [_issues(), _issues(blocking=True), _issues()],
        "executor": [_write(), _finish(), _write(), _finish()],
        "scorer": [_score(0.65), _score(0.9)],
        "verifier": [_verdict(False), _verdict(True)],
    }
    task, port, runs = _run(scripts, env)
    assert task.state is TaskState.DELIVERY
    _, mem = env
    errs = list((mem / "errors").glob("err-*.md"))
    assert errs, "a failing attempt must write an error-memory entry before the retry"


# --- 3. hard-floor escalation --------------------------------------------

def test_hard_floor_escalates_tier(env):
    scripts = {
        "classifier": [_classify(difficulty="easy")],   # -> T1
        "planner": [_plan()],
        "critic": [_issues(), _issues(), _issues()],
        "executor": [_write(), _finish(), _write(), _finish()],
        "scorer": [_score(0.40), _score(0.9)],           # attempt0 below hard floor
        "verifier": [_verdict(True), _verdict(True)],
    }
    task, port, runs = _run(scripts, env)
    assert task.state is TaskState.DELIVERY
    exec_roles = port.role_calls("executor")
    assert "executor" in exec_roles       # attempt0 at base role
    assert "T2" in exec_roles             # attempt1 escalated one tier


# --- 4. replan is bounded to one -----------------------------------------

def test_plan_gate_replans_once(env):
    scripts = {
        "classifier": [_classify()],
        "planner": [_plan(), _plan()],           # original + exactly one replan
        "critic": [_issues(blocking=True), _issues()],   # plan blocked, step clean
        "executor": [_write(), _finish()],
        "scorer": [_score(0.9)],
        "verifier": [_verdict(True)],
    }
    task, port, runs = _run(scripts, env)
    assert task.state is TaskState.DELIVERY
    assert port.role_calls("planner") == ["planner", "planner"]  # not three


# --- 5. executor tool-call cap -------------------------------------------

def test_executor_tool_call_cap_fails_loudly(env):
    scripts = {
        "classifier": [_classify()],
        "planner": [_plan()],
        "critic": [_issues()],                  # plan gate only; step never verified
        "executor": [_read()],                  # repeats forever -> never finishes
    }
    task, port, runs = _run(scripts, env, repeat=True)
    assert task.state is TaskState.FAILED
    _, mem = env
    assert list((mem / "errors").glob("err-*.md")), "cap breach must write an error entry"


# --- 6. report schema rejection -> repair --------------------------------

def test_bad_report_is_repaired(env):
    bad = {"summary": "no status field", "confidence": 0.9}   # missing 'status' -> invalid
    scripts = {
        "classifier": [_classify()],
        "planner": [_plan()],
        "critic": [_issues(), _issues()],
        "executor": [_write(), _finish(report=bad), _finish()],  # bad finish, then repair finish
        "scorer": [_score(0.9)],
        "verifier": [_verdict(True)],
    }
    task, port, runs = _run(scripts, env)
    assert task.state is TaskState.DELIVERY
    # the loop consumed BOTH finish actions (bad one triggered a repair turn)
    assert port.role_calls("executor").count("executor") == 3
