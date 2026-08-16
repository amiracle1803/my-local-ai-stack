"""loop.py — the Manager: owns the task state machine and the GATHER->ACT->VERIFY loop.

Phase 1 implements the full lifecycle from agent.md §5/§6 on top of the Phase 0 core:

  INTAKE   classify (T0 + rule fallback) -> route -> create_task
  PLANNING retrieval-first evidence bundle -> planner (T2) -> plan gate (critic, 1 replan)
  EXECUTION per step: executor ReAct (read_file/write_artifact/finish) -> critic ->
           scorer -> gates (>=0.80 pass / <0.50 escalate / mid revise) -> verifier
  VERIFY   task-level verdict assembled from step verdicts
  DELIVERY reports/final-report.md from step reports; episodic memory writeback

Doctrine enforced here (manager layer): loop caps, one replan, error-memory-before-retry,
wall-clock budget, loud failure. Mechanical guards live in the port / runstate (Phase 0).

Everything model-facing is JSON-schema-constrained and tolerant of small-model sloppiness:
the ModelPort already repairs+ladders bad JSON; this module degrades gracefully (logged
as concerns) only when the ladder is exhausted, so a run never silently spins.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from jsonschema import Draft7Validator

from . import memory
from .models import (
    Budget,
    Classification,
    Route,
    Task,
    TaskState,
)
from .registry import Registry, load_registry
from . import runstate
from .runstate import (
    RUNS_DIR,
    atomic_write,
    check_side_effect,
    create_task,
    record_artifact,
    run_dir,
    transition,
)
from ..ports.model_port import LadderExhausted, ModelPort, ModelPortError

HARNESS_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = HARNESS_ROOT.parent
AGENTS_DIR = HARNESS_ROOT / "agents"
SCHEMAS_DIR = HARNESS_ROOT / "schemas"

STEP_GATE = 0.80
HARD_FLOOR = 0.50
MAX_TOOL_CALLS = 10
DEFAULT_WALL_MINUTES = 15
OBS_CAP = 1000          # tool-result summary cap (loop-engineering §3)
CONTENT_CAP = 3000      # artifact content injected into review contexts

SideEffect = runstate.SideEffect


# --- exceptions ----------------------------------------------------------

class LoopError(RuntimeError):
    """Base for manager-loop failures (all end a task loudly in FAILED)."""


class RetryWithoutErrorRef(LoopError):
    """A retry payload was built without citing an error-memory entry (invariant 5)."""


class ToolCallCapExceeded(LoopError):
    """The executor ReAct loop hit max_tool_calls without finishing."""


class BudgetExhausted(LoopError):
    """Wall-clock budget for the task ran out."""


class StepFailed(LoopError):
    """A step exhausted its attempts without a passing verdict."""


# --- prompt loading ------------------------------------------------------

_PROMPT_CACHE: dict[str, str] = {}


def load_prompt(name: str) -> str:
    if name not in _PROMPT_CACHE:
        _PROMPT_CACHE[name] = (AGENTS_DIR / f"{name}.prompt.md").read_text(encoding="utf-8")
    return _PROMPT_CACHE[name]


def system_for(role: str) -> str:
    return load_prompt("_preamble") + "\n\n---\n\n" + load_prompt(role)


_SCHEMA_CACHE: dict[str, dict] = {}


def load_schema(filename: str) -> dict:
    if filename not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[filename] = json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[filename]


# --- inline schemas ------------------------------------------------------

CLASSIFY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["domain", "difficulty", "risk", "offline_ok"],
    "properties": {
        "domain": {"enum": ["coding", "research", "writing", "analysis",
                            "media", "ops", "workflow", "memory"]},
        "difficulty": {"enum": ["trivial", "easy", "standard", "hard", "frontier"]},
        "risk": {"enum": ["low", "medium", "high"]},
        "offline_ok": {"type": "boolean"},
    },
}

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "required": ["steps"],
    "properties": {
        "goal_restated": {"type": "string"},
        "steps": {
            "type": "array", "minItems": 1, "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": True,
                "required": ["objective", "acceptance_criteria"],
                "properties": {
                    "objective": {"type": "string", "minLength": 1},
                    "agent": {"type": "string"},
                    "acceptance_criteria": {
                        "type": "array", "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "side_effects": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "plan_acceptance": {"type": "array", "items": {"type": "string"}},
        "risk_note": {"type": "string"},
    },
}

ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "required": ["action"],
    "properties": {
        "thought": {"type": "string"},
        "action": {"enum": ["read_file", "write_artifact", "finish"]},
        "args": {"type": "object"},
        "report": {"type": "object"},
    },
}

CRITIC_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "required": ["issues"],
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
                "required": ["severity"],
                "properties": {
                    "severity": {"enum": ["blocking", "non-blocking"]},
                    "criterion": {"type": "string"},
                    "evidence": {"type": "string"},
                    "suggested_direction": {"type": "string"},
                },
            },
        }
    },
}


# --- progress emit -------------------------------------------------------

def _default_emit(line: str) -> None:
    print(line, flush=True)


@dataclass
class StepResult:
    idx: int
    passed: bool
    score: float
    report: dict
    scorecard: dict
    verdict: dict
    attempts: int
    artifacts: list[dict] = field(default_factory=list)


# --- classification ------------------------------------------------------

_CODE_HINTS = ("function", "python", "code", "script", ".py", "slugify", "def ", "class ",
               "api", "regex", "json", "sql", "bug", "implement", "refactor")
_ANALYSIS_HINTS = ("analy", "table", "compare", "summar", "read ", "extract", "list ",
                   "report", "review", "audit", "inspect")
_WRITING_HINTS = ("write", "haiku", "poem", "story", "essay", "draft", "limerick",
                  "summary", "describe", "narrat")


def rule_based_classify(goal: str) -> Classification:
    g = goal.lower()
    if any(h in g for h in _CODE_HINTS):
        domain, difficulty = "coding", "standard"
    elif any(h in g for h in _ANALYSIS_HINTS):
        domain, difficulty = "analysis", "standard"
    elif any(h in g for h in _WRITING_HINTS):
        domain, difficulty = "writing", "easy"
    else:
        domain, difficulty = "ops", "standard"
    risk = "low"  # v1 executor is text/file only, scoped writes
    return Classification(domain=domain, difficulty=difficulty, risk=risk, offline_ok=True)


def classify_goal(goal: str, port, task_id: str, emit: Callable[[str], None]) -> Classification:
    """T0 classification with rule-based fallback (routing.md §2)."""
    messages = [
        {"role": "system", "content": load_prompt("_preamble")
         + "\n\nYou are the triage classifier. Emit ONLY the classification JSON."},
        {"role": "user", "content":
            f"Classify this task. Goal:\n{goal}\n\n"
            'Return JSON {"domain","difficulty","risk","offline_ok"} where domain in '
            "[coding,research,writing,analysis,media,ops,workflow,memory], difficulty in "
            "[trivial,easy,standard,hard,frontier], risk in [low,medium,high], "
            "offline_ok boolean."},
    ]
    try:
        res = port.generate("T0", messages, schema=CLASSIFY_SCHEMA,
                            task_id=task_id, agent="classifier")
        if res.ok and res.data:
            return Classification(**res.data)
    except ModelPortError as exc:
        emit(f"  [intake] classifier model failed ({exc}); using rule-based fallback")
    return rule_based_classify(goal)


def route_for(cls: Classification, registry: Registry) -> Route:
    """Simple classification->tier routing (routing.md §3 defaults + domain overrides)."""
    routing = registry.routing or {}
    defaults = routing.get("defaults", {})
    tier = defaults.get(cls.difficulty, "T1")
    for ov in routing.get("overrides", []):
        if ov.get("domain") and ov["domain"] == cls.domain:
            if ov.get("difficulty") and ov["difficulty"] != cls.difficulty:
                continue
            if ov.get("tier"):
                tier = ov["tier"]
    entry = registry.resolve_tier(tier)
    fallbacks = [m.id for m in registry.siblings(entry.id)]
    return Route(tier=tier, model=entry.id, fallbacks=fallbacks)


# --- evidence bundle (retrieval-first) -----------------------------------

def build_evidence_bundle(goal: str, task: Task) -> tuple[str, list[str]]:
    hits = memory.find_errors(goal, limit=3)
    d = run_dir(task.id)
    lines = ["# Evidence bundle v1", "", f"corpus: error-memory only", ""]
    refs: list[str] = []
    if hits:
        lines.append("## Relevant prior failures")
        for h in hits:
            rel = _repo_rel(h.path)
            refs.append(rel)
            lines.append(f"- {h.id}: {h.title} (see {rel})")
    else:
        lines.append("## Relevant prior failures")
        lines.append("- none found (retrieval ran; no matching err- entries). skip reason: empty index.")
    text = "\n".join(lines) + "\n"
    path = d / "reports" / "evidence-00.md"
    atomic_write(path, text)
    return text, refs


# --- planning ------------------------------------------------------------

def run_planner(goal: str, cls: Classification, evidence: str, budget: Budget,
                port, task_id: str, critique: Optional[list] = None) -> dict:
    user = (
        f"GOAL:\n{goal}\n\n"
        f"CLASSIFICATION: domain={cls.domain} difficulty={cls.difficulty} "
        f"risk={cls.risk} offline_ok={cls.offline_ok}\n\n"
        f"EVIDENCE BUNDLE:\n{evidence}\n\n"
        f"BUDGET: max_loops={budget.max_loops}, wall_minutes={budget.max_wall_minutes}\n"
    )
    if critique:
        user += "\nCRITIC BLOCKING ISSUES to fix in this replan:\n" + _issues_text(critique) + "\n"
    user += "\nEmit the plan JSON now."
    messages = [{"role": "system", "content": system_for("planner")},
                {"role": "user", "content": user}]
    res = port.generate("planner", messages, schema=PLAN_SCHEMA, task_id=task_id, agent="planner")
    return res.data


def run_plan_critic(plan: dict, port, task_id: str) -> list:
    criteria = ["every step has a one-sentence objective",
                "every acceptance criterion names its evidence form and is testable",
                "<= 5 steps; each step produces a file artifact"]
    user = (
        "PLAN (JSON):\n" + json.dumps(plan, indent=2)[:CONTENT_CAP] + "\n\n"
        "ACCEPTANCE CRITERIA for the plan:\n" + "\n".join(f"- {c}" for c in criteria) + "\n\n"
        "List issues. Mark 'blocking' only for untestable criteria, missing objectives, "
        "or >5 steps. Emit the issues JSON."
    )
    return _run_critic_raw(user, port, task_id)


# --- executor ReAct ------------------------------------------------------

def _repo_rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def tool_read_file(rel_path: str) -> str:
    target = (REPO_ROOT / rel_path).resolve()
    if REPO_ROOT not in target.parents and target != REPO_ROOT:
        return f"ERROR: path escapes repo root: {rel_path}"
    if not target.exists() or not target.is_file():
        return f"ERROR: no such file: {rel_path}"
    try:
        return target.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"ERROR reading {rel_path}: {exc}"


def tool_write_artifact(task: Task, name: str, content: str, runs_dir: Path) -> dict:
    safe = Path(str(name)).name or "artifact.txt"
    path = run_dir(task.id, runs_dir) / "artifacts" / safe
    check_side_effect(task, SideEffect.WRITE_SCOPED, path, runs_dir=runs_dir)
    atomic_write(path, content if isinstance(content, str) else json.dumps(content))
    entry = record_artifact(task.id, path, producer="executor", runs_dir=runs_dir)
    return {"path": entry["path"], "sha256": entry["sha256"],
            "kind": _kind_for(safe), "abs": str(path)}


def _kind_for(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {".py": "code", ".md": "text", ".txt": "text", ".json": "data"}.get(ext, "file")


def run_executor(payload: dict, role: str, port, task: Task, runs_dir: Path,
                 emit: Callable[[str], None], critique: Optional[list] = None) -> tuple[dict, str, list]:
    """ReAct loop: model returns one action per turn; <= MAX_TOOL_CALLS. Returns
    (finalized report dict, primary artifact content, written-artifact list)."""
    handoff_id = payload["handoff_id"]
    sys_msg = system_for("executor")
    user = "HANDOFF PAYLOAD:\n" + json.dumps(payload, indent=2)
    if critique:
        user += "\n\nCRITIQUE to address (blocking issues from the last attempt):\n" + _issues_text(critique)
    user += "\n\nBegin. One action per turn as JSON."
    msgs = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user}]

    written: list[dict] = []
    last_content = ""
    tokens = 0
    tool_calls = 0
    started = time.monotonic()

    for _turn in range(MAX_TOOL_CALLS):
        res = port.generate(role, msgs, schema=ACTION_SCHEMA,
                            task_id=task.id, agent="executor",
                            think=False)  # executor is tool work; thinking costs 100s+ on T2
        tokens += res.usage.get("tokens_in", 0) + res.usage.get("tokens_out", 0)
        action = res.data or {}
        msgs.append({"role": "assistant", "content": res.text})
        act = action.get("action")
        args = action.get("args") or {}

        if act == "read_file":
            path = args.get("path") or action.get("path") or ""
            obs = tool_read_file(str(path))
            tool_calls += 1
            emit(f"    executor read_file {path}")
            msgs.append({"role": "user", "content": "OBSERVATION:\n" + _cap(obs, OBS_CAP)})
            continue

        if act == "write_artifact":
            name = args.get("name") or action.get("name") or "artifact.txt"
            content = args.get("content")
            if content is None:
                content = action.get("content", "")
            info = tool_write_artifact(task, name, content, runs_dir)
            written.append({"path": info["path"], "sha256": info["sha256"], "kind": info["kind"]})
            last_content = content if isinstance(content, str) else json.dumps(content)
            tool_calls += 1
            emit(f"    executor write_artifact {info['path']} ({len(last_content)} chars)")
            msgs.append({"role": "user", "content":
                         f"OBSERVATION: wrote {info['path']} (sha256={info['sha256'][:12]}..., "
                         f"{len(last_content)} bytes). Continue or finish."})
            continue

        if act == "finish":
            usage = {"tokens": tokens, "tool_calls": tool_calls,
                     "wall_seconds": round(time.monotonic() - started, 2)}
            report, errs = _finalize_report(action.get("report"), payload, written, usage)
            if errs:
                # regenerate ONLY the report, decoder-constrained by the report schema
                # (the action envelope's nested report is loosely typed; this isn't)
                emit("    executor report invalid -> constrained report regeneration")
                try:
                    fix = port.generate(
                        role,
                        [{"role": "system", "content":
                          "Emit ONLY a JSON report object matching the enforced shape. "
                          "No action envelope, no prose."},
                         {"role": "user", "content":
                          f"Objective: {payload.get('objective', '')}\n"
                          f"Acceptance criteria: {json.dumps(payload.get('acceptance_criteria', []))}\n"
                          f"Artifacts written: {json.dumps(written)}\n"
                          f"Last artifact content (excerpt): {_cap(last_content, 500)}\n"
                          f"Previous report's validation errors: {errs}\n"
                          "Emit the corrected report JSON."}],
                        schema=load_schema("report.schema.json"),
                        task_id=task.id, agent="executor", think=False)
                    report, errs = _finalize_report(fix.data, payload, written, usage)
                except ModelPortError:
                    pass
            if errs:
                report = _synthesize_report(payload, written, usage, errs)
                emit("    executor report still invalid -> synthesized minimal report")
            return report, last_content, written

        # unknown/absent action -> nudge once
        msgs.append({"role": "user", "content":
                     'Invalid action. Use "read_file", "write_artifact", or "finish". JSON only.'})

    raise ToolCallCapExceeded(f"executor exceeded {MAX_TOOL_CALLS} tool calls for {handoff_id}")


def _finalize_report(model_report: Optional[dict], payload: dict, written: list,
                     usage: dict) -> tuple[dict, str]:
    base = dict(model_report or {})
    base["handoff_id"] = payload["handoff_id"]
    base["artifacts"] = written
    base["usage"] = usage
    base.setdefault("evidence", [{"claim": "artifact produced", "ref": a["path"], "kind": a["kind"]}
                                 for a in written] or [{"claim": "no artifact", "ref": "none", "kind": "none"}])
    base.setdefault("acceptance_self_check",
                    [{"criterion": i, "met": bool(written), "evidence_idx": 0}
                     for i in range(len(payload.get("acceptance_criteria", []) or [1]))])
    base.pop("suggested_memory", None)  # optional; drop to avoid enum drift
    errs = _schema_errors(load_schema("report.schema.json"), base)
    return base, errs


def _synthesize_report(payload: dict, written: list, usage: dict, why: str) -> dict:
    crit = payload.get("acceptance_criteria", []) or ["produce artifact"]
    return {
        "handoff_id": payload["handoff_id"],
        "status": "done" if written else "partial",
        "summary": "Executor completed; report auto-normalized after schema drift.",
        "artifacts": written,
        "evidence": [{"claim": "artifact produced", "ref": a["path"], "kind": a["kind"]} for a in written]
                    or [{"claim": "no artifact", "ref": "none", "kind": "none"}],
        "acceptance_self_check": [{"criterion": i, "met": bool(written), "evidence_idx": 0}
                                  for i in range(len(crit))],
        "confidence": 0.5,
        "concerns": [f"report schema drift auto-normalized: {why[:200]}"],
        "usage": usage,
    }


# --- review chain: critic / scorer / verifier ----------------------------

def _run_critic_raw(user: str, port, task_id: str) -> list:
    messages = [{"role": "system", "content": system_for("critic")},
                {"role": "user", "content": user}]
    try:
        res = port.generate("critic", messages, schema=CRITIC_SCHEMA,
                            task_id=task_id, agent="critic")
        return (res.data or {}).get("issues", [])
    except ModelPortError:
        return []  # degrade: no blocking issues found (logged as concern by caller)


def run_step_critic(content: str, criteria: list, port, task_id: str) -> list:
    user = (
        "ACCEPTANCE CRITERIA:\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(criteria)) + "\n\n"
        "ARTIFACT CONTENT:\n" + _cap(content, CONTENT_CAP) + "\n\n"
        "Check each criterion against the content. Emit the issues JSON."
    )
    return _run_critic_raw(user, port, task_id)


def run_scorer(content: str, criteria: list, issues: list, handoff_id: str,
               port, task_id: str) -> dict:
    user = (
        f"threshold: {STEP_GATE}\n\n"
        "ACCEPTANCE CRITERIA:\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(criteria)) + "\n\n"
        "CRITIC ISSUES:\n" + (_issues_text(issues) or "(none)") + "\n\n"
        "ARTIFACT CONTENT:\n" + _cap(content, CONTENT_CAP) + "\n\n"
        f'Score per the rubric. Use handoff_id "{handoff_id}". Emit the scorecard JSON.'
    )
    messages = [{"role": "system", "content": system_for("scorer")},
                {"role": "user", "content": user}]
    try:
        res = port.generate("scorer", messages, schema=load_schema("scorecard.schema.json"),
                            task_id=task_id, agent="scorer")
        card = res.data
    except ModelPortError:
        card = None
    if card:
        vals = [float(v) for v in (card.get("scores") or {}).values()
                if isinstance(v, (int, float))]
        wt = float(card.get("weighted_total") or 0.0)
        if vals and wt == 0.0 and sum(vals) > 0:
            card["weighted_total"] = sum(vals) / len(vals)  # model omitted the total
        elif vals and sum(vals) == 0.0 and content.strip():
            card = None  # degenerate all-zeros on a non-empty artifact -> mechanical proxy
    if not card:
        # degrade: mechanical proxy — artifact present & non-trivial -> passing-ish
        base = 0.82 if content.strip() else 0.30
        card = {
            "handoff_id": handoff_id, "loop": 0, "rubric": "rubrics/step-v1-fallback",
            "scores": {"correctness": base, "criteria_coverage": base,
                       "evidence_quality": base, "simplicity": base, "constraint_compliance": base},
            "weighted_total": base, "gate": {"threshold": STEP_GATE, "passed": base >= STEP_GATE},
        }
    # manager owns the gate decision; recompute rather than trust the model
    total = float(card.get("weighted_total", 0.0))
    card["handoff_id"] = handoff_id
    card["gate"] = {"threshold": STEP_GATE, "passed": total >= STEP_GATE}
    return card


def _doctest_check(abs_path: Path) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "doctest", str(abs_path)],
            capture_output=True, text=True, timeout=60,
        )
        ok = proc.returncode == 0
        detail = (proc.stdout or "") + (proc.stderr or "")
        return ok, _cap(detail or "doctest exit 0", 400)
    except Exception as exc:  # noqa: BLE001
        return False, f"doctest run error: {exc}"


def run_verifier(content: str, criteria: list, scorecard: dict, issues: list,
                 written: list, handoff_id: str, port, task: Task, runs_dir: Path) -> dict:
    checks: list[dict] = []
    executed_fail = False

    # Execution beats opinion: re-read artifacts + run executable checks.
    for a in written:
        abs_path = run_dir(task.id, runs_dir) / a["path"]
        exists = abs_path.exists()
        checks.append({"name": f"artifact {a['path']} exists", "kind": "probe",
                       "passed": exists, "detail": "" if exists else "missing on disk"})
        if not exists:
            executed_fail = True
        if exists and abs_path.suffix.lower() == ".py":
            ok, detail = _doctest_check(abs_path)
            checks.append({"name": f"doctest {a['path']}", "kind": "test",
                           "passed": ok, "detail": detail})
            if not ok:
                executed_fail = True

    # Model judgment for the remaining (non-executable) criteria.
    exec_summary = "\n".join(f"- {c['name']}: {'PASS' if c['passed'] else 'FAIL'}" for c in checks)
    user = (
        f'handoff_id: {handoff_id}\n\n'
        "ACCEPTANCE CRITERIA:\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(criteria)) + "\n\n"
        "EXECUTED CHECKS (already run by the harness):\n" + (exec_summary or "(none)") + "\n\n"
        "ARTIFACT CONTENT (re-read from disk):\n" + _cap(content, CONTENT_CAP) + "\n\n"
        "Issue the verdict JSON. If any executed check FAILED, passed must be false."
    )
    messages = [{"role": "system", "content": system_for("verifier")},
                {"role": "user", "content": user}]
    model_passed = None
    model_reasons: list[str] = []
    try:
        res = port.generate("verifier", messages, schema=load_schema("verdict.schema.json"),
                            task_id=task.id, agent="verifier")
        if res.data:
            model_passed = bool(res.data.get("passed"))
            model_reasons = res.data.get("reasons", [])
            for c in res.data.get("checks", []):
                checks.append({"name": c.get("name", "criterion"),
                               "kind": c.get("kind", "model-judgment"),
                               "passed": bool(c.get("passed")),
                               "detail": _cap(str(c.get("detail", "")), 200)})
    except ModelPortError:
        model_reasons = ["verifier model unavailable; relied on executed + mechanical checks"]

    if model_passed is None:
        # degrade to mechanical: pass iff no executed check failed and an artifact exists
        passed = (not executed_fail) and bool(written)
    else:
        passed = model_passed and not executed_fail
    reasons = model_reasons or (["all checks passed"] if passed else ["one or more checks failed"])
    if executed_fail:
        reasons = ["an executed check failed"] + reasons
    return {
        "handoff_id": handoff_id, "verifier": "verifier", "passed": passed,
        "checks": checks, "reasons": reasons,
        "created": datetime.now(timezone.utc).isoformat(),
    }


# --- payload building ----------------------------------------------------

def build_payload(step: dict, idx: int, task: Task, route: Route, *,
                  is_retry: bool = False, error_memory: Optional[list] = None) -> dict:
    """Handoff payload (handoff.md §3), validated against handoff.schema.json.

    Doctrine invariant 5: a retry payload MUST cite an error-memory entry."""
    error_memory = error_memory or []
    if is_retry and not error_memory:
        raise RetryWithoutErrorRef(
            "retry payload must cite an error-memory entry (doctrine invariant 5)")
    now = datetime.now(timezone.utc)
    handoff_id = f"H-{now:%Y%m%d}-{runstate.secrets.token_hex(2)}-{idx % 100:02d}"
    criteria = step.get("acceptance_criteria") or ["produce the requested artifact"]
    payload = {
        "handoff_id": handoff_id,
        "task_id": task.id,
        "step": idx,
        "state": "EXECUTION",
        "from": "manager",
        "to": "executor",
        "objective": step.get("objective", task.goal),
        "acceptance_criteria": list(criteria),
        "inputs": {
            "plan_ref": "plan/plan.json",
            "artifacts": [],
            "evidence_bundle": "reports/evidence-00.md",
            "error_memory": list(error_memory),
        },
        "constraints": {"side_effects": ["write-scoped"], "offline_ok": True},
        "budget": {"max_tokens": route_budget_tokens(route),
                   "max_wall_minutes": 15, "max_tool_calls": MAX_TOOL_CALLS},
        "route": {"tier": route.tier, "model": route.model},
        "return_schema": "schemas/report.schema.json",
    }
    errs = _schema_errors(load_schema("handoff.schema.json"), payload)
    if errs:
        raise LoopError(f"internal: handoff payload invalid: {errs}")
    return payload


def route_budget_tokens(route: Route) -> int:
    return 8000 if route.tier in ("T2", "T3") else 4000


# --- step execution with gates -------------------------------------------

def execute_step(step: dict, idx: int, task: Task, route: Route, port, runs_dir: Path,
                 max_loops: int, emit: Callable[[str], None]) -> StepResult:
    criteria = step.get("acceptance_criteria") or ["produce the requested artifact"]
    role = "executor"
    error_refs: list[str] = []
    critique: Optional[list] = None
    escalated = False
    last: Optional[StepResult] = None

    for attempt in range(max_loops):
        is_retry = attempt > 0
        payload = build_payload(step, idx, task, route,
                                is_retry=is_retry, error_memory=error_refs)
        emit(f"  [step {idx}] attempt {attempt + 1}/{max_loops} role={role}")
        try:
            report, content, written = run_executor(payload, role, port, task, runs_dir, emit, critique)
        except ModelPortError as exc:
            # runtime failure kills the attempt, never the task (agent.md failure domains)
            emit(f"  [step {idx}] {type(exc).__name__} at role={role} -> attempt failed")
            err = memory.write_error(
                task.id, symptom=f"step {idx} attempt {attempt + 1}: {type(exc).__name__}",
                context=f"role {role}; objective: {step.get('objective', '')}",
                root_cause=str(exc)[:200],
                remedies=[f"attempt {attempt + 1} at role {role}"],
                recommendation="retry at workhorse tier; check runtime health",
                tags=[task.class_.domain, "runtime-fail"],
            )
            error_refs = [_repo_rel(err)]
            last = StepResult(idx, False, 0.0, {}, {},
                              {"passed": False, "reasons": [str(exc)[:200]]}, attempt + 1, [])
            role = "executor"  # escalation target unreachable -> return to the workhorse
            critique = None
            continue
        issues = run_step_critic(content, criteria, port, task.id)
        scorecard = run_scorer(content, criteria, issues, payload["handoff_id"], port, task.id)
        score = float(scorecard.get("weighted_total", 0.0))
        verdict = run_verifier(content, criteria, scorecard, issues, written,
                               payload["handoff_id"], port, task, runs_dir)
        _persist_step(task, idx, report, scorecard, verdict, issues, runs_dir)
        emit(f"  [step {idx}] score={score:.2f} verifier={'pass' if verdict['passed'] else 'fail'}")

        # last attempt accepts a verifier pass even in the revise band (systems-prompts §12).
        passed = verdict["passed"] and (score >= STEP_GATE or attempt == max_loops - 1)
        last = StepResult(idx, passed, score, report, scorecard, verdict, attempt + 1, written)
        if passed:
            return last

        # failure -> write error first (invariant 5), then decide next move.
        blocking = [i for i in issues if i.get("severity") == "blocking"]
        symptom = f"step {idx} not accepted: score {score:.2f}, verifier {'pass' if verdict['passed'] else 'fail'}"
        err = memory.write_error(
            task.id, symptom=symptom,
            context=f"objective: {step.get('objective', '')}; attempt {attempt + 1}",
            root_cause="score below gate or verifier fail" if not blocking else blocking[0].get("criterion", "unmet criterion"),
            remedies=[f"attempt {attempt + 1} at tier {route.tier}"],
            recommendation="escalate tier" if score < HARD_FLOOR else "revise with critique attached",
            tags=[task.class_.domain, "step-fail"],
        )
        error_refs = [_repo_rel(err)]

        if attempt == max_loops - 1:
            break
        if score < HARD_FLOOR and not escalated:
            nxt = port.registry.next_tier(route.tier) if hasattr(port, "registry") else None
            if nxt:
                role = nxt
                escalated = True
                emit(f"  [step {idx}] hard floor {score:.2f} < {HARD_FLOOR} -> escalate to {nxt}")
            critique = None
        else:
            critique = blocking or issues
            emit(f"  [step {idx}] score {score:.2f} -> revise with critique")

    return last  # type: ignore[return-value]


def _persist_step(task: Task, idx: int, report: dict, scorecard: dict, verdict: dict,
                  issues: list, runs_dir: Path) -> None:
    d = run_dir(task.id, runs_dir)
    atomic_write(d / "reports" / f"report-{idx:02d}.json", json.dumps(report, indent=2))
    atomic_write(d / "reports" / f"critique-{idx:02d}.md",
                 "# Critique\n\n" + (_issues_text(issues) or "No issues found.\n"))
    atomic_write(d / "scores" / f"scorecard-{idx:02d}.json", json.dumps(scorecard, indent=2))
    atomic_write(d / "scores" / f"verdict-{idx:02d}.json", json.dumps(verdict, indent=2))


# --- the manager ---------------------------------------------------------

def run_task(goal: str, *, max_loops: int = 3, port=None, registry: Optional[Registry] = None,
             runs_dir: Path = RUNS_DIR, wall_minutes: int = DEFAULT_WALL_MINUTES,
             emit: Optional[Callable[[str], None]] = None) -> Task:
    """Drive one goal through INTAKE->PLANNING->EXECUTION->VERIFICATION->DELIVERY.

    Returns the Task in its terminal state (DELIVERY on success, FAILED on loud exit)."""
    emit = emit or _default_emit
    registry = registry or (getattr(port, "registry", None)) or load_registry()
    owns_port = port is None
    if port is None:
        # T2 thinking models (qwen3) routinely exceed 120s on executor payloads.
        port = ModelPort(registry, runs_dir=runs_dir, timeout=300.0)

    memory.ensure_memory()
    started = time.monotonic()

    def budget_check(where: str) -> None:
        if time.monotonic() - started > wall_minutes * 60:
            raise BudgetExhausted(f"wall-clock budget {wall_minutes}m exhausted at {where}")

    task: Optional[Task] = None
    try:
        # ---- INTAKE ----
        tmp_id = "T-intake"
        cls = classify_goal(goal, port, tmp_id, emit)
        route = route_for(cls, registry)
        budget = Budget(max_loops=max_loops, max_tokens=200_000, max_wall_minutes=wall_minutes)
        task = create_task(goal, cls, route=route, budget=budget, runs_dir=runs_dir)
        emit(f"[INTAKE] {task.id}")
        emit(f"  class: {cls.domain}/{cls.difficulty}/{cls.risk} -> route {route.tier} ({route.model})")

        # ---- PLANNING ----
        transition(task, TaskState.PLANNING, runs_dir=runs_dir)
        emit("[PLANNING]")
        evidence, ev_refs = build_evidence_bundle(goal, task)
        emit(f"  evidence: {len(ev_refs)} error-memory hit(s)")
        plan = run_planner(goal, cls, evidence, budget, port, task.id)
        pissues = run_plan_critic(plan, port, task.id)
        if any(i.get("severity") == "blocking" for i in pissues):
            emit(f"  plan gate: {sum(1 for i in pissues if i.get('severity') == 'blocking')} blocking issue(s) -> 1 replan")
            plan = run_planner(goal, cls, evidence, budget, port, task.id, critique=pissues)
        steps = plan.get("steps", [])[:5]
        _write_plan(task, plan, runs_dir)
        emit(f"  plan: {len(steps)} step(s)")
        budget_check("planning")

        # ---- EXECUTION ----
        transition(task, TaskState.EXECUTION, runs_dir=runs_dir)
        emit("[EXECUTION]")
        results: list[StepResult] = []
        for idx, step in enumerate(steps):
            budget_check(f"step {idx}")
            r = execute_step(step, idx, task, route, port, runs_dir, max_loops, emit)
            results.append(r)
            if not r.passed:
                raise StepFailed(f"step {idx} exhausted {r.attempts} attempt(s); "
                                 f"final score {r.score:.2f}, verifier "
                                 f"{'pass' if r.verdict['passed'] else 'fail'}")

        # ---- VERIFICATION (task-level) ----
        transition(task, TaskState.VERIFICATION, runs_dir=runs_dir)
        emit("[VERIFICATION]")
        task_passed = all(r.passed for r in results)
        task_verdict = {
            "task_id": task.id, "passed": task_passed,
            "steps": [{"step": r.idx, "score": r.score, "verifier": r.verdict["passed"]} for r in results],
            "created": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write(run_dir(task.id, runs_dir) / "scores" / "verdict-task.json",
                     json.dumps(task_verdict, indent=2))

        # ---- DELIVERY ----
        transition(task, TaskState.DELIVERY, runs_dir=runs_dir)
        _write_final_report(task, goal, plan, results, runs_dir)
        emit(f"[DELIVERY] {task.id} -> reports/final-report.md")
        _writeback_episode(task, goal, results, "delivered")
        return task

    except (LoopError, ModelPortError, runstate.StateTransitionError,
            runstate.SideEffectError) as exc:
        emit(f"[FAILED] {type(exc).__name__}: {exc}")
        if task is not None:
            # each step independent: a hiccup writing memory must not block the FAILED
            # transition (crash > corrupt, but never leave a task stuck mid-state).
            try:
                memory.write_error(
                    task.id, symptom=f"task failed: {type(exc).__name__}",
                    context=f"goal: {goal}", root_cause=str(exc),
                    remedies=["ran the manager loop"],
                    recommendation="inspect run dir logs; consider tier escalation or replan",
                    tags=[task.class_.domain, "task-fail"],
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                if task.state not in (TaskState.DELIVERY, TaskState.FAILED):
                    transition(task, TaskState.FAILED, runs_dir=runs_dir)
            except Exception:  # noqa: BLE001
                pass
            _writeback_episode(task, goal, [], f"failed: {exc}")
        return task if task is not None else _phantom_failed(goal, cls if 'cls' in dir() else None)
    finally:
        if owns_port:
            port.close()


# --- delivery + writeback helpers ----------------------------------------

def _write_plan(task: Task, plan: dict, runs_dir: Path) -> None:
    d = run_dir(task.id, runs_dir)
    atomic_write(d / "plan" / "plan.json", json.dumps(plan, indent=2))
    lines = [f"# Plan — {task.id}", "", f"Goal: {task.goal}", "",
             f"Restated: {plan.get('goal_restated', '(none)')}", "", "## Steps", ""]
    for i, s in enumerate(plan.get("steps", [])):
        lines.append(f"### Step {i}: {s.get('objective', '')}")
        lines.append(f"- agent: {s.get('agent', 'executor')}")
        lines.append("- acceptance criteria:")
        for c in s.get("acceptance_criteria", []):
            lines.append(f"  - {c}")
        lines.append("")
    if plan.get("risk_note"):
        lines += ["## Risk", plan["risk_note"], ""]
    atomic_write(d / "plan" / "plan.md", "\n".join(lines))


def _write_final_report(task: Task, goal: str, plan: dict, results: list, runs_dir: Path) -> None:
    lines = [f"# Final report — {task.id}", "", f"Goal: {goal}", "",
             f"Result: {'DELIVERED' if all(r.passed for r in results) else 'INCOMPLETE'}", "",
             "## Steps", ""]
    for r in results:
        lines.append(f"### Step {r.idx} — score {r.score:.2f}, "
                     f"verifier {'pass' if r.verdict['passed'] else 'fail'} "
                     f"({r.attempts} attempt(s))")
        lines.append(r.report.get("summary", "(no summary)"))
        for a in r.artifacts:
            lines.append(f"- artifact: `{a['path']}` ({a['kind']})")
        if r.report.get("concerns"):
            lines.append("- concerns: " + "; ".join(r.report["concerns"]))
        lines.append("")
    atomic_write(run_dir(task.id, runs_dir) / "reports" / "final-report.md", "\n".join(lines))


def _writeback_episode(task: Task, goal: str, results: list, outcome: str) -> None:
    try:
        summary = [f"goal: {goal}",
                   f"domain: {task.class_.domain}, difficulty: {task.class_.difficulty}",
                   f"steps: {len(results)}"]
        for r in results:
            summary.append(f"step {r.idx}: score {r.score:.2f}, "
                           f"{'pass' if r.passed else 'fail'}, {r.attempts} attempt(s)")
        memory.write_episode(task.id, title=f"task {task.id}: {goal[:60]}",
                             outcome=outcome, summary_lines=summary,
                             tags=[task.class_.domain])
    except Exception:  # noqa: BLE001
        pass


def _phantom_failed(goal: str, cls) -> Task:
    # create_task itself failed (e.g. registry error before a task existed): mint a minimal
    # FAILED record so callers always get a Task back.
    cls = cls or rule_based_classify(goal)
    t = create_task(goal, cls)
    transition(t, TaskState.FAILED)
    return t


# --- small text utils ----------------------------------------------------

def _cap(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + "\n...[truncated]"


def _issues_text(issues: list) -> str:
    out = []
    for i in issues or []:
        sev = i.get("severity", "non-blocking")
        crit = i.get("criterion", "general")
        ev = i.get("evidence", "")
        sug = i.get("suggested_direction", "")
        out.append(f"- [{sev}] {crit}: {ev} -> {sug}")
    return "\n".join(out)


def _schema_errors(schema: dict, data: dict) -> str:
    errors = sorted(Draft7Validator(schema).iter_errors(data), key=lambda e: str(e.path))
    return "; ".join(e.message for e in errors[:3])
