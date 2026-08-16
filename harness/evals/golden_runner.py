"""Golden-task runner (evals discipline, loop-engineering §1).

Loads the YAML golden tasks, runs each through the live manager loop, then applies its
own programmatic checks against the produced artifacts — the checks are the gate, not the
in-loop verifier's opinion (execution beats opinion). Prints a pass/fail table.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from ..core.loop import run_task
from ..core.runstate import run_dir

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def load_golden() -> list[dict]:
    tasks = []
    for path in sorted(GOLDEN_DIR.glob("*.yaml")):
        tasks.append(yaml.safe_load(path.read_text(encoding="utf-8")))
    return tasks


def _artifact(task_id: str, name: str) -> Path:
    return run_dir(task_id) / "artifacts" / name


def run_check(task_id: str, check: dict) -> tuple[bool, str]:
    kind = check["kind"]
    if kind == "artifact_exists":
        p = _artifact(task_id, check["name"])
        return p.exists(), f"{check['name']} {'found' if p.exists() else 'MISSING'}"
    if kind == "min_lines":
        p = _artifact(task_id, check["name"])
        if not p.exists():
            return False, f"{check['name']} missing"
        n = len([ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()])
        return n >= check["lines"], f"{n} non-empty lines (need >= {check['lines']})"
    if kind == "contains_all":
        p = _artifact(task_id, check["name"])
        if not p.exists():
            return False, f"{check['name']} missing"
        text = p.read_text(encoding="utf-8").lower()
        missing = [x for x in check["needles"] if x.lower() not in text]
        return not missing, ("all present" if not missing else f"missing: {missing}")
    if kind == "doctest":
        p = _artifact(task_id, check["name"])
        if not p.exists():
            return False, f"{check['name']} missing"
        proc = subprocess.run([sys.executable, "-m", "doctest", str(p)],
                              capture_output=True, text=True, timeout=60)
        return proc.returncode == 0, (
            "doctest exit 0" if proc.returncode == 0
            else f"doctest exit {proc.returncode}: {(proc.stdout + proc.stderr)[-200:]}")
    return False, f"unknown check kind: {kind}"


def run_golden(emit=print) -> int:
    tasks = load_golden()
    rows = []
    for t in tasks:
        emit(f"\n=== {t['id']} {t['name']} ===")
        try:
            task = run_task(t["goal"], emit=emit)
            task_id = task.id
            state = task.state.value
        except Exception as exc:  # noqa: BLE001
            rows.append((t["id"], t["name"], "ERROR", 0, len(t["checks"]), str(exc)[:60]))
            continue
        results = [run_check(task_id, c) for c in t["checks"]]
        passed = sum(1 for ok, _ in results if ok)
        total = len(results)
        detail = "; ".join(f"{c['kind']}:{'ok' if ok else 'X'}"
                           for c, (ok, _) in zip(t["checks"], results))
        rows.append((t["id"], t["name"], state, passed, total, detail))

    emit("\n" + "=" * 72)
    emit(f"{'id':<4} {'task':<24} {'state':<13} {'checks':<8} detail")
    emit("-" * 72)
    n_pass = 0
    for tid, name, state, passed, total, detail in rows:
        ok = passed == total and total > 0
        n_pass += 1 if ok else 0
        emit(f"{tid:<4} {name:<24} {state:<13} {passed}/{total:<6} {detail}")
    emit("-" * 72)
    emit(f"GOLDEN: {n_pass}/{len(rows)} tasks fully passed")
    return 0 if n_pass >= 2 else 1
