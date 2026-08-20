"""Daemon (background task) tests — spawn records, child streams to heartbeat + log."""

import json

import pytest

from harness import daemon
from harness.core import runstate
from harness.core.models import TaskState


def _fixed_task(runs_dir, state=TaskState.DELIVERY):
    t = runstate.create_task("bg goal", runstate.Classification(
        domain="ops", difficulty="trivial", risk="low", offline_ok=True),
        runs_dir=runs_dir)  # scaffolded; only state matters here
    t.state = state
    return t


def test_write_heartbeat_then_status(tmp_path):
    daemon.write_heartbeat("T-bg-0001", state="running", line="started",
                           runs_dir=tmp_path)
    info = daemon.status("T-bg-0001", runs_dir=tmp_path)
    assert info["exists"] is True
    assert info["state"] == "running"
    assert info["last_line"] == "started"


def test_status_missing_task(tmp_path):
    info = daemon.status("T-nope", runs_dir=tmp_path)
    assert info["exists"] is False
    assert info["state"] == "unknown"
    assert info["alive"] is False


def test_spawn_writes_record_and_launches_child(tmp_path, monkeypatch):
    launched = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kwargs):
        launched["cmd"] = cmd
        launched["cwd"] = kwargs.get("cwd")
        return FakeProc()

    monkeypatch.setattr(daemon.subprocess, "Popen", fake_popen)
    rec = daemon.spawn("some goal", runs_dir=tmp_path, python="/usr/bin/python3")
    assert rec["task_id"].startswith("T-")
    assert rec["pid"] == 4242
    assert launched["cmd"] == ["/usr/bin/python3", "-m", "harness", "daemon-run",
                               "--task-id", rec["task_id"], "--goal", "some goal"]
    assert launched["cwd"] == daemon.REPO_ROOT
    rec_path = runstate.run_dir(rec["task_id"], tmp_path) / "logs" / "daemon.json"
    assert rec_path.exists()
    assert json.loads(rec_path.read_text(encoding="utf-8"))["pid"] == 4242


def test_spawn_uses_sys_executable_by_default(tmp_path, monkeypatch):
    launched = {}

    class FakeProc:
        pid = 7

    monkeypatch.setattr(daemon.subprocess, "Popen",
                        lambda cmd, **kw: launched.update(cmd=cmd) or FakeProc())
    rec = daemon.spawn("g", runs_dir=tmp_path)
    assert launched["cmd"][0] == daemon.sys.executable


def test_child_main_delivery_streams_heartbeat(tmp_path, monkeypatch):
    done = {}

    def fake_run_task(goal, **kw):
        done["kw"] = kw
        return _fixed_task(tmp_path, TaskState.DELIVERY)

    monkeypatch.setattr("harness.core.loop.run_task", fake_run_task)
    code = daemon.child_main("T-bg-0002", "deliver me", runs_dir=tmp_path)
    assert code == 0
    assert done["kw"]["task_id"] == "T-bg-0002"
    hb = daemon.status("T-bg-0002", runs_dir=tmp_path)
    assert hb["state"] == "delivered"
    log = runstate.run_dir("T-bg-0002", tmp_path) / "logs" / "daemon.log"
    assert log.exists()


def test_child_main_failure_writes_failed_heartbeat(tmp_path, monkeypatch):
    def boom(goal, **kw):
        raise RuntimeError("model ladder exhausted")

    monkeypatch.setattr("harness.core.loop.run_task", boom)
    code = daemon.child_main("T-bg-0003", "will fail", runs_dir=tmp_path)
    assert code == 1
    hb = daemon.status("T-bg-0003", runs_dir=tmp_path)
    assert hb["state"] == "failed"
    assert "model ladder exhausted" in hb["last_line"]


def test_attach_prints_state_and_log_tail(tmp_path, capsys):
    daemon.write_heartbeat("T-bg-0004", state="running", line="mid-flight",
                           runs_dir=tmp_path)
    d = runstate.run_dir("T-bg-0004", tmp_path)
    (d / "logs").mkdir(parents=True, exist_ok=True)
    (d / "logs" / "daemon.log").write_text("\n".join(f"line {i}" for i in range(5)))
    code = daemon.attach("T-bg-0004", runs_dir=tmp_path, tail=2)
    out = capsys.readouterr().out
    assert code == 0
    assert "running" in out
    assert "mid-flight" in out
    assert "line 4" in out
    assert "line 0" not in out
