"""Task lifecycle & run-dir state plane (agent.md §5, 00-overview.md §6/§7).

- create_task: mint task ID, scaffold runs/<id>/{plan,artifacts,reports,scores,logs}/ + task.json
- transition: enforce the legal state machine (INTAKE -> PLANNING -> EXECUTION ->
  VERIFICATION -> DELIVERY; EXECUTION -> PLANNING replan bounded <=2; any -> FAILED)
- check_side_effect: port-layer refusal of illegal writes for the current state
- atomic write-tmp-then-rename everywhere (agent.md §7: "crash > corrupt")
- manifest.json: path + sha256 + producer ledger
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Classification, Route, Budget, Verification, Task, TaskState, SideEffect

HARNESS_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = HARNESS_ROOT / "runs"

RUN_SUBDIRS = ("plan", "artifacts", "reports", "scores", "logs")
MAX_REPLANS = 2

# Legal state machine (agent.md §5). "*" -> FAILED handled separately.
LEGAL_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.INTAKE: {TaskState.PLANNING},
    TaskState.PLANNING: {TaskState.EXECUTION},
    TaskState.EXECUTION: {TaskState.VERIFICATION, TaskState.PLANNING},  # PLANNING = replan
    TaskState.VERIFICATION: {TaskState.DELIVERY},
    TaskState.DELIVERY: set(),
    TaskState.FAILED: set(),
}


class StateTransitionError(RuntimeError):
    """Illegal state transition or exhausted replan budget."""


class SideEffectError(RuntimeError):
    """A write whose target dir is illegal for the current task state."""


# --- helpers -------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _slugify(text: str, max_len: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)[:max_len].strip("-")
    return slug or "task"


def mint_task_id(goal: str, now: Optional[datetime] = None) -> str:
    now = now or _utcnow()
    return f"T-{now:%Y%m%d}-{_slugify(goal)}-{secrets.token_hex(2)}"


def run_dir(task_id: str, runs_dir: Path = RUNS_DIR) -> Path:
    return runs_dir / task_id


def atomic_write(path: Path, data: str) -> None:
    """Write-tmp-then-rename so a crash never leaves a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{secrets.token_hex(4)}")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # atomic on Windows and POSIX


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --- task lifecycle ------------------------------------------------------

def _default_route() -> Route:
    # Phase 0 placeholder; the model-router fills this per routing.md §10 in Phase 1.
    return Route(tier="T1", model="qwen2.5-7b@ollama", fallbacks=["ornith-9b@ollama"])


def create_task(
    goal: str,
    classification: Classification,
    *,
    route: Optional[Route] = None,
    budget: Optional[Budget] = None,
    verification: Optional[Verification] = None,
    runs_dir: Path = RUNS_DIR,
) -> Task:
    now = _utcnow()
    task = Task(
        id=mint_task_id(goal, now),
        goal=goal,
        state=TaskState.INTAKE,
        **{"class": classification},
        route=route or _default_route(),
        budget=budget or Budget(max_loops=3, max_tokens=200000, max_wall_minutes=45),
        plan_ref=None,
        verification=verification or Verification(required_score=0.8, verifier="verifier", status="pending"),
        created=now,
        updated=None,
    )
    d = run_dir(task.id, runs_dir)
    for sub in RUN_SUBDIRS:
        (d / sub).mkdir(parents=True, exist_ok=True)
    _write_task(task, runs_dir)
    _write_manifest(task.id, {"task_id": task.id, "created": now.isoformat(), "artifacts": []}, runs_dir)
    return task


def _write_task(task: Task, runs_dir: Path) -> None:
    path = run_dir(task.id, runs_dir) / "task.json"
    atomic_write(path, json.dumps(task.to_json_dict(), indent=2))


def load_task(task_id: str, runs_dir: Path = RUNS_DIR) -> Task:
    path = run_dir(task_id, runs_dir) / "task.json"
    return Task.model_validate_json(path.read_text(encoding="utf-8"))


def transition(task: Task, new_state: TaskState, runs_dir: Path = RUNS_DIR) -> Task:
    current = task.state
    if new_state is TaskState.FAILED:
        allowed = current not in (TaskState.DELIVERY, TaskState.FAILED)
    else:
        allowed = new_state in LEGAL_TRANSITIONS[current]
    if not allowed:
        raise StateTransitionError(f"illegal transition {current.value} -> {new_state.value}")

    is_replan = current is TaskState.EXECUTION and new_state is TaskState.PLANNING
    if is_replan and task.replans >= MAX_REPLANS:
        raise StateTransitionError(f"replan budget exhausted ({task.replans}/{MAX_REPLANS})")

    task.state = new_state
    if is_replan:
        task.replans += 1
    task.updated = _utcnow()
    _write_task(task, runs_dir)
    return task


# --- side-effect gate ----------------------------------------------------

_STATE_FORBIDDEN_DIRS: dict[TaskState, set[str]] = {
    TaskState.PLANNING: {"artifacts"},   # no execution outputs while planning
    TaskState.EXECUTION: {"plan"},       # plan is immutable during execution
}


def check_side_effect(task: Task, effect_class: SideEffect, path: Path, runs_dir: Path = RUNS_DIR) -> None:
    """Refuse illegal writes at the port layer (agent.md §5). Reads are always free."""
    if effect_class is SideEffect.READ:
        return
    if effect_class not in (SideEffect.WRITE_SCOPED, SideEffect.WRITE_SHARED,
                            SideEffect.EXTERNAL, SideEffect.IRREVERSIBLE):
        return

    forbidden = _STATE_FORBIDDEN_DIRS.get(task.state, set())
    if not forbidden:
        return

    base = run_dir(task.id, runs_dir).resolve()
    target = Path(path).resolve()
    try:
        rel = target.relative_to(base)
    except ValueError:
        return  # outside this run dir — not this gate's concern (external/irreversible gates handle it)
    top = rel.parts[0] if rel.parts else ""
    if top in forbidden:
        raise SideEffectError(
            f"{effect_class.value} to {top}/ is illegal in state {task.state.value}"
        )


# --- manifest ------------------------------------------------------------

def _manifest_path(task_id: str, runs_dir: Path) -> Path:
    return run_dir(task_id, runs_dir) / "manifest.json"


def _write_manifest(task_id: str, data: dict, runs_dir: Path) -> None:
    atomic_write(_manifest_path(task_id, runs_dir), json.dumps(data, indent=2))


def load_manifest(task_id: str, runs_dir: Path = RUNS_DIR) -> dict:
    return json.loads(_manifest_path(task_id, runs_dir).read_text(encoding="utf-8"))


def record_artifact(
    task_id: str,
    artifact_path: Path,
    producer: str,
    *,
    superseded_by: Optional[str] = None,
    runs_dir: Path = RUNS_DIR,
) -> dict:
    """Append an artifact to manifest.json with its sha256 and producer (handoff.md §6)."""
    manifest = load_manifest(task_id, runs_dir)
    base = run_dir(task_id, runs_dir).resolve()
    ap = Path(artifact_path).resolve()
    try:
        rel = str(ap.relative_to(base)).replace("\\", "/")
    except ValueError:
        rel = str(ap)
    entry = {
        "path": rel,
        "sha256": sha256_file(ap),
        "producer": producer,
        "superseded_by": superseded_by,
        "recorded": _utcnow().isoformat(),
    }
    manifest.setdefault("artifacts", []).append(entry)
    _write_manifest(task_id, manifest, runs_dir)
    return entry
