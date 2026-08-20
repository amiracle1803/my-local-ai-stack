"""Background task execution (ported from prime-agent's daemon-backed sessions).

`harness run --background "<goal>"` launches the manager loop in a detached
subprocess; the child writes a heartbeat (state + last emitted line) plus a
transcript to the run dir's logs/, so `harness status <task-id>` and
`harness attach <task-id>` observe a long-running task after the launching
terminal has closed.

  python -m harness run --background "goal"   # launch detached
  python -m harness status <task-id>          # one-line state + pid/alive
  python -m harness attach <task-id>          # status + live log tail
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .core.runstate import RUNS_DIR, atomic_write, mint_task_id, run_dir

REPO_ROOT = Path(__file__).resolve().parent.parent

_HEARTBEAT = "heartbeat.json"
_DAEMON_RECORD = "daemon.json"
_DAEMON_LOG = "daemon.log"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# --- launch --------------------------------------------------------------

def spawn(goal: str, *, runs_dir: Path = RUNS_DIR, task_id: Optional[str] = None,
          python: Optional[str] = None) -> dict:
    """Mint a task id, scaffold its run dir, and launch `run_task` detached.

    The child entrypoint is `python -m harness daemon-run --task-id <id> --goal "<goal>"`.
    Returns the daemon record written to logs/daemon.json.
    """
    task_id = task_id or mint_task_id(goal)
    d = run_dir(task_id, runs_dir)
    (d / "logs").mkdir(parents=True, exist_ok=True)
    py = python or sys.executable
    log_fh = open(d / "logs" / _DAEMON_LOG, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [py, "-m", "harness", "daemon-run",
         "--task-id", task_id, "--goal", goal],
        cwd=REPO_ROOT,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_fh.close()
    rec = {
        "task_id": task_id,
        "goal": goal,
        "pid": proc.pid,
        "started": _utcnow(),
        "state": "running",
    }
    atomic_write(d / "logs" / _DAEMON_RECORD, json.dumps(rec, indent=2))
    return rec


# --- child (daemon-run) --------------------------------------------------

def child_main(task_id: str, goal: str, *, runs_dir: Path = RUNS_DIR) -> int:
    """Entrypoint for the detached child: run the loop, stream to logs + heartbeat."""
    from .core.loop import run_task
    from .core.models import TaskState

    d = run_dir(task_id, runs_dir)
    log_path = d / "logs" / _DAEMON_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_path, "a", encoding="utf-8")

    def emit(line: str) -> None:
        fh.write(f"[{_stamp()}] {line}\n")
        fh.flush()
        write_heartbeat(task_id, state="running", line=line, runs_dir=runs_dir)

    try:
        task = run_task(goal, runs_dir=runs_dir, task_id=task_id, emit=emit)
        ok = task.state is TaskState.DELIVERY
        write_heartbeat(task_id, state="delivered" if ok else "failed",
                        line=f"final: {task.state.value}", runs_dir=runs_dir)
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001
        write_heartbeat(task_id, state="failed",
                        line=f"{type(exc).__name__}: {exc}", runs_dir=runs_dir)
        return 1
    finally:
        fh.close()


# --- observation ---------------------------------------------------------

def write_heartbeat(task_id: str, *, state: str, line: str, runs_dir: Path = RUNS_DIR) -> None:
    d = run_dir(task_id, runs_dir)
    (d / "logs").mkdir(parents=True, exist_ok=True)
    hb = {"task_id": task_id, "state": state, "line": line, "updated": _utcnow()}
    atomic_write(d / "logs" / _HEARTBEAT, json.dumps(hb, indent=2))


def status(task_id: str, *, runs_dir: Path = RUNS_DIR) -> dict:
    d = run_dir(task_id, runs_dir)
    rec = _read_json(d / "logs" / _DAEMON_RECORD)
    hb = _read_json(d / "logs" / _HEARTBEAT)
    pid = (rec or {}).get("pid")
    return {
        "task_id": task_id,
        "exists": d.exists(),
        "pid": pid,
        "alive": bool(pid) and _pid_alive(pid),
        "state": (hb or {}).get("state") or (rec or {}).get("state", "unknown"),
        "last_line": (hb or {}).get("line"),
        "log": d / "logs" / _DAEMON_LOG,
    }


def attach(task_id: str, *, runs_dir: Path = RUNS_DIR, tail: int = 40) -> int:
    info = status(task_id, runs_dir=runs_dir)
    print(f"task {task_id}")
    print(f"  state: {info['state']}")
    print(f"  pid:   {info['pid']}  alive: {info['alive']}")
    if info["last_line"]:
        print(f"  last:  {info['last_line']}")
    log = info["log"]
    if log and log.exists():
        lines = log.read_text(encoding="utf-8").splitlines()
        shown = lines[-tail:]
        print(f"  --- last {len(shown)}/{len(lines)} lines ---")
        print("\n".join(shown))
    else:
        print("  (no log yet)")
    return 0


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        return bool(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
