"""Harness CLI.

  python -m harness models            — resolved registry vs. what Ollama actually has
  python -m harness smoke             — end-to-end self-check against live Ollama
  python -m harness run "<goal>"      — drive one goal through the full manager loop (live)
  python -m harness run --background "<goal>"  — same, in a detached daemon
  python -m harness status <task-id>  — daemon task state + pid/alive
  python -m harness attach <task-id>  — daemon status + live log tail
  python -m harness golden            — run the 3 golden tasks; print a pass/fail table
"""

from __future__ import annotations

import json
import sys

import httpx

from .core.memory import ensure_memory
from .core.models import Classification, TaskState
from .core.registry import load_registry
from .core import runstate
from .ports.model_port import ModelPort, ModelPortError

OLLAMA = "http://127.0.0.1:11434"


# --- models command ------------------------------------------------------

def cmd_models() -> int:
    reg = load_registry()
    installed = _ollama_tags()
    print("Registry (harness/registry/models.yaml) -> Ollama presence\n")
    print(f"{'model id':<26} {'tier':<5} {'ollama tag':<26} present")
    print("-" * 70)
    for tier in ["T0", "T1", "T2", "T3", "F"]:
        for mid in reg._tiers.get(tier, []):
            e = reg.entries.get(mid)
            tag = e.model if e else "?"
            present = "yes" if e and e.model in installed else "NO"
            print(f"{mid:<26} {tier:<5} {tag:<26} {present}")
    extra = sorted(installed - {e.model for e in reg.entries.values()})
    if extra:
        print("\nInstalled but unregistered:", ", ".join(extra))
    if installed is None:
        print("\n(could not reach Ollama at", OLLAMA, ")")
    return 0


def _ollama_tags() -> set[str]:
    try:
        resp = httpx.get(OLLAMA + "/api/tags", timeout=5.0)
        resp.raise_for_status()
        return {m["name"] for m in resp.json().get("models", [])}
    except Exception:
        return set()


# --- smoke command -------------------------------------------------------

_SMOKE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "confident"],
    "properties": {
        "answer": {"type": "integer"},
        "confident": {"type": "boolean"},
    },
}


def cmd_smoke() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))

    print("angelic-harness smoke test\n")

    reg = load_registry()
    check("registry loads", bool(reg.entries), f"{len(reg.entries)} models")

    ensure_memory()
    check("memory tree ensured", (runstate.HARNESS_ROOT / "memory" / "errors").exists())

    cls = Classification(domain="ops", difficulty="trivial", risk="low", offline_ok=True)
    task = runstate.create_task("harness smoke self-check", cls)
    d = runstate.run_dir(task.id)
    check("task created + scaffolded",
          all((d / s).exists() for s in runstate.RUN_SUBDIRS) and (d / "task.json").exists(),
          task.id)

    # pick smallest installed T0 model; if T0's model isn't present, fall back to any installed
    installed = _ollama_tags()
    t0 = reg.resolve_tier("T0")
    if t0.model not in installed and installed:
        print(f"  (T0 model {t0.model} absent; using an installed model for the live call)")

    port = ModelPort(reg)
    msgs = [
        {"role": "system", "content": "You return only JSON. No prose."},
        {"role": "user", "content": "What is 6 times 7? Reply as JSON "
                                     '{"answer": <int>, "confident": <bool>}.'},
    ]
    live_ok, result = False, None
    try:
        result = port.generate("T0", msgs, schema=_SMOKE_SCHEMA, task_id=task.id, agent="scorer")
        live_ok = result.ok and result.data is not None
        check("live T0 call + schema-valid JSON", live_ok,
              f"{result.model_id} rung={result.rung} -> {result.data}")
    except ModelPortError as exc:
        check("live T0 call + schema-valid JSON", False, str(exc))
    finally:
        port.close()

    # artifact + manifest
    art = d / "artifacts" / "00-smoke.json"
    runstate.transition(task, TaskState.PLANNING)
    runstate.transition(task, TaskState.EXECUTION)
    runstate.atomic_write(art, json.dumps(result.data if result else {"stub": True}, indent=2))
    entry = runstate.record_artifact(task.id, art, producer="scorer")
    check("artifact written + manifest entry", art.exists() and entry["sha256"] != "")

    # side-effect gate: writing plan/ during EXECUTION must be refused
    refused = False
    try:
        runstate.check_side_effect(task, runstate.SideEffect.WRITE_SCOPED, d / "plan" / "x.md")
    except runstate.SideEffectError:
        refused = True
    check("side-effect gate refuses plan/ write in EXECUTION", refused)

    # full state walk
    try:
        runstate.transition(task, TaskState.VERIFICATION)
        runstate.transition(task, TaskState.DELIVERY)
        check("state machine INTAKE->...->DELIVERY", task.state is TaskState.DELIVERY)
    except runstate.StateTransitionError as exc:
        check("state machine INTAKE->...->DELIVERY", False, str(exc))

    # calls.jsonl exists and is valid JSONL
    log = d / "logs" / "calls.jsonl"
    log_ok = log.exists() and all(json.loads(l) for l in log.read_text().splitlines() if l.strip())
    check("every model call logged to calls.jsonl", log_ok)

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n{'PASS' if passed == total else 'FAIL'}: {passed}/{total} checks")
    return 0 if passed == total else 1


# --- run command ---------------------------------------------------------

def cmd_run(goal: str, *, background: bool = False) -> int:
    from .core.loop import run_task
    from .core.models import TaskState

    if not goal.strip():
        print('usage: python -m harness run [--background] "<goal>"', file=sys.stderr)
        return 2
    if background:
        from . import daemon
        rec = daemon.spawn(goal)
        print(f"launched background task {rec['task_id']} (pid {rec['pid']})")
        print(f"  status: python -m harness status {rec['task_id']}")
        print(f"  attach: python -m harness attach {rec['task_id']}")
        return 0
    task = run_task(goal)
    d = runstate.run_dir(task.id)
    final = d / "reports" / "final-report.md"
    print(f"\nfinal state: {task.state.value}")
    print(f"run dir: {d}")
    if final.exists():
        print("\n--- final-report.md ---")
        print(final.read_text(encoding="utf-8"))
    return 0 if task.state is TaskState.DELIVERY else 1


# --- daemon observation commands ----------------------------------------

def cmd_status(task_id: str) -> int:
    if not task_id:
        print("usage: python -m harness status <task-id>", file=sys.stderr)
        return 2
    from . import daemon
    info = daemon.status(task_id)
    print(f"task {task_id}")
    print(f"  state: {info['state']}")
    print(f"  pid:   {info['pid']}  alive: {info['alive']}")
    if info["last_line"]:
        print(f"  last:  {info['last_line']}")
    if info["log"] and info["log"].exists():
        print(f"  log:   {len(info['log'].read_text(encoding='utf-8').splitlines())} lines")
    return 0


def cmd_attach(task_id: str) -> int:
    if not task_id:
        print("usage: python -m harness attach <task-id>", file=sys.stderr)
        return 2
    from . import daemon
    return daemon.attach(task_id)


def cmd_daemon_run(args: list[str]) -> int:
    """Hidden child entrypoint: python -m harness daemon-run --task-id <id> --goal "<goal>"."""
    task_id = goal = None
    i = 0
    while i < len(args):
        if args[i] == "--task-id" and i + 1 < len(args):
            task_id = args[i + 1]
            i += 2
        elif args[i] == "--goal" and i + 1 < len(args):
            goal = args[i + 1]
            i += 2
        else:
            i += 1
    if not task_id or not goal:
        print("daemon-run: missing --task-id/--goal", file=sys.stderr)
        return 2
    from . import daemon
    return daemon.child_main(task_id, goal)


# --- golden command ------------------------------------------------------

def cmd_golden() -> int:
    from .evals.golden_runner import run_golden
    return run_golden()


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "smoke"
    if cmd == "models":
        return cmd_models()
    if cmd == "smoke":
        return cmd_smoke()
    if cmd == "run":
        rest = argv[1:]
        background = bool(rest) and rest[0] == "--background"
        if background:
            rest = rest[1:]
        return cmd_run(" ".join(rest), background=background)
    if cmd == "golden":
        return cmd_golden()
    if cmd == "daemon-run":
        return cmd_daemon_run(argv[1:])
    if cmd == "status":
        return cmd_status(argv[1] if len(argv) > 1 else "")
    if cmd == "attach":
        return cmd_attach(argv[1] if len(argv) > 1 else "")
    print(f"unknown command: {cmd}\n"
          "usage: python -m harness [smoke|models|run [--background] \"<goal>\"|"
          "status <task-id>|attach <task-id>|golden]", file=sys.stderr)
    return 2
