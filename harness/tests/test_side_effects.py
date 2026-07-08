import pytest

from harness.core.models import Classification, SideEffect, TaskState
from harness.core import runstate


def _task(tmp_path):
    cls = Classification(domain="coding", difficulty="standard", risk="low", offline_ok=True)
    return runstate.create_task("side effect goal", cls, runs_dir=tmp_path)


def _p(task, tmp_path, *parts):
    return runstate.run_dir(task.id, tmp_path).joinpath(*parts)


def test_planning_refuses_artifacts_write(tmp_path):
    task = _task(tmp_path)
    runstate.transition(task, TaskState.PLANNING, runs_dir=tmp_path)
    with pytest.raises(runstate.SideEffectError):
        runstate.check_side_effect(task, SideEffect.WRITE_SCOPED,
                                   _p(task, tmp_path, "artifacts", "x.py"), runs_dir=tmp_path)


def test_planning_allows_plan_write(tmp_path):
    task = _task(tmp_path)
    runstate.transition(task, TaskState.PLANNING, runs_dir=tmp_path)
    runstate.check_side_effect(task, SideEffect.WRITE_SCOPED,
                               _p(task, tmp_path, "plan", "plan.md"), runs_dir=tmp_path)


def test_execution_refuses_plan_write(tmp_path):
    task = _task(tmp_path)
    runstate.transition(task, TaskState.PLANNING, runs_dir=tmp_path)
    runstate.transition(task, TaskState.EXECUTION, runs_dir=tmp_path)
    with pytest.raises(runstate.SideEffectError):
        runstate.check_side_effect(task, SideEffect.WRITE_SCOPED,
                                   _p(task, tmp_path, "plan", "plan.md"), runs_dir=tmp_path)


def test_execution_allows_artifacts_write(tmp_path):
    task = _task(tmp_path)
    runstate.transition(task, TaskState.PLANNING, runs_dir=tmp_path)
    runstate.transition(task, TaskState.EXECUTION, runs_dir=tmp_path)
    runstate.check_side_effect(task, SideEffect.WRITE_SCOPED,
                               _p(task, tmp_path, "artifacts", "01.py"), runs_dir=tmp_path)


def test_reads_always_free(tmp_path):
    task = _task(tmp_path)
    runstate.transition(task, TaskState.PLANNING, runs_dir=tmp_path)
    runstate.check_side_effect(task, SideEffect.READ,
                               _p(task, tmp_path, "artifacts", "anything"), runs_dir=tmp_path)
