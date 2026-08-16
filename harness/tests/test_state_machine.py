import pytest

from harness.core.models import Classification, TaskState
from harness.core import runstate


def _task(tmp_path):
    cls = Classification(domain="ops", difficulty="easy", risk="low", offline_ok=True)
    return runstate.create_task("state machine goal", cls, runs_dir=tmp_path)


LEGAL_PATH = [
    TaskState.PLANNING,
    TaskState.EXECUTION,
    TaskState.VERIFICATION,
    TaskState.DELIVERY,
]


def test_full_legal_path(tmp_path):
    task = _task(tmp_path)
    assert task.state is TaskState.INTAKE
    for state in LEGAL_PATH:
        runstate.transition(task, state, runs_dir=tmp_path)
        assert task.state is state
    assert runstate.load_task(task.id, tmp_path).state is TaskState.DELIVERY


@pytest.mark.parametrize("frm,to", [
    (TaskState.INTAKE, TaskState.EXECUTION),
    (TaskState.INTAKE, TaskState.VERIFICATION),
    (TaskState.PLANNING, TaskState.VERIFICATION),
    (TaskState.PLANNING, TaskState.DELIVERY),
    (TaskState.EXECUTION, TaskState.DELIVERY),
    (TaskState.VERIFICATION, TaskState.EXECUTION),
    (TaskState.DELIVERY, TaskState.PLANNING),
])
def test_illegal_transitions_rejected(tmp_path, frm, to):
    task = _task(tmp_path)
    task.state = frm
    with pytest.raises(runstate.StateTransitionError):
        runstate.transition(task, to, runs_dir=tmp_path)


def test_replan_bounded_at_two(tmp_path):
    task = _task(tmp_path)
    runstate.transition(task, TaskState.PLANNING, runs_dir=tmp_path)
    for _ in range(2):  # two legal replans
        runstate.transition(task, TaskState.EXECUTION, runs_dir=tmp_path)
        runstate.transition(task, TaskState.PLANNING, runs_dir=tmp_path)
    assert task.replans == 2
    runstate.transition(task, TaskState.EXECUTION, runs_dir=tmp_path)
    with pytest.raises(runstate.StateTransitionError):
        runstate.transition(task, TaskState.PLANNING, runs_dir=tmp_path)  # 3rd replan refused


def test_any_state_can_fail(tmp_path):
    for frm in [TaskState.INTAKE, TaskState.PLANNING, TaskState.EXECUTION, TaskState.VERIFICATION]:
        task = _task(tmp_path)
        task.state = frm
        runstate.transition(task, TaskState.FAILED, runs_dir=tmp_path)
        assert task.state is TaskState.FAILED


def test_terminal_states_are_dead_ends(tmp_path):
    task = _task(tmp_path)
    task.state = TaskState.DELIVERY
    with pytest.raises(runstate.StateTransitionError):
        runstate.transition(task, TaskState.FAILED, runs_dir=tmp_path)
