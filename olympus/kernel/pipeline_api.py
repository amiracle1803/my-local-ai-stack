"""Pipeline endpoints -- bridge from the Olympus kernel (:4600) to the
Anime Pipeline v2 engine (``olympus/engines/pipeline``), mounted at
``/api/pipeline``.

    GET  /api/pipeline/projects              list projects (scans blueprint.json)
    POST /api/pipeline/projects               create a project (brief_text OR script_text)
    GET  /api/pipeline/{slug}/status          stage ledger + scorecard + flags
    POST /api/pipeline/{slug}/run/{stage}     background-run one stage

Imports the ``pipeline`` package and ``run`` module from the engine directly
(no shelling out) -- mirrors ``run.py``'s own ``sys.path`` bootstrap. Only
``stage0`` is implemented upstream (M1); every other stage is a gated stub
that raises ``NotImplementedError`` -- surfaced here as status ``not_built``
rather than a 500.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

# --------------------------------------------------------------------------
# sys.path bootstrap -- import the pipeline engine's `pipeline` package and
# `run` module without shelling out (mirrors run.py's own bootstrap).
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ENGINE_ROOT = REPO_ROOT / "olympus" / "engines" / "pipeline"
if str(PIPELINE_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ENGINE_ROOT))

import run as pipeline_run  # noqa: E402
from pipeline.blueprint import Blueprint, STAGE_ORDER, snap_fps  # noqa: E402
from pipeline.config import PipelineConfig  # noqa: E402
from pipeline.scores import Scores  # noqa: E402

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# Stages with a real implementation upstream (M1: stage0 only). Everything
# else in STAGE_ORDER is a pollution-guard -> gate -> NotImplementedError
# stub until its milestone lands.
IMPLEMENTED_STAGES: frozenset[str] = frozenset({"stage0"})


# --------------------------------------------------------------------------
# projects-root override (test hook)
# --------------------------------------------------------------------------
_projects_root_override: Path | None = None


def set_projects_root(path: str | Path | None) -> None:
    """Override the projects directory (tests point this at tmp_path).
    Pass ``None`` to restore the pipeline.toml-configured default."""
    global _projects_root_override
    _projects_root_override = Path(path) if path is not None else None


def get_projects_root() -> Path:
    if _projects_root_override is not None:
        return _projects_root_override
    return PipelineConfig.load().projects_dir()


# --------------------------------------------------------------------------
# background stage-run registry
# --------------------------------------------------------------------------
_lock = threading.Lock()
_running: dict[tuple[str, str], threading.Thread] = {}
# (slug, stage) -> None (last run succeeded) | {"type": "not_built"|"failed", "message": str}
_last_error: dict[tuple[str, str], dict[str, str] | None] = {}
_last_result: dict[tuple[str, str], dict[str, Any]] = {}


def reset_runtime_state() -> None:
    """Clear the in-memory run registry (test hook, e.g. between test cases)."""
    with _lock:
        _running.clear()
        _last_error.clear()
        _last_result.clear()


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------
class ProjectIn(BaseModel):
    slug: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    brief_text: str | None = None
    script_text: str | None = None
    fps: int = 24

    @model_validator(mode="after")
    def _one_source(self) -> "ProjectIn":
        has_brief = bool(self.brief_text and self.brief_text.strip())
        has_script = bool(self.script_text and self.script_text.strip())
        if has_brief == has_script:  # neither, or both
            raise ValueError("provide exactly one of brief_text or script_text")
        return self


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _project_dir(slug: str) -> Path:
    return get_projects_root() / slug


def _bp_summary(bp: Blueprint) -> dict[str, Any]:
    return {
        "slug": bp.slug,
        "story_id": bp.story_id,
        "fps": bp.fps,
        "created": bp.created,
        "stages": {stage: bp.stages[stage].status for stage in STAGE_ORDER},
    }


def _stage_status(slug: str, stage: str, bp_status: str) -> tuple[str, str | None]:
    """Merge blueprint-persisted status with the live run registry / last
    error for one stage. Returns (status, error_message)."""
    key = (slug, stage)
    with _lock:
        thread = _running.get(key)
        is_running = thread is not None and thread.is_alive()
        err = _last_error.get(key)
    if is_running:
        return "running", None
    if err is not None:
        return err["type"], err["message"]
    if bp_status in ("done", "awaiting_approval", "failed"):
        return bp_status, None
    if stage not in IMPLEMENTED_STAGES:
        return "not_built", None
    return bp_status, None


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------
@router.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    root = get_projects_root()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if not (d / "blueprint.json").exists():
            continue
        try:
            bp = Blueprint.load(d)
        except Exception:
            continue
        out.append(_bp_summary(bp))
    out.sort(key=lambda p: p["created"], reverse=True)
    return out


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn) -> dict[str, Any]:
    project_dir = _project_dir(body.slug)
    if project_dir.exists():
        raise HTTPException(409, f"project already exists: {body.slug!r}")

    fps = snap_fps(body.fps)
    seed_text = body.brief_text if body.brief_text else body.script_text
    is_brief = bool(body.brief_text)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        seed_path = Path(tmp) / "seed.txt"
        seed_path.write_text(seed_text, encoding="utf-8")
        try:
            pipeline_run.new_project(
                body.slug, seed_path, fps=fps, projects_dir=get_projects_root()
            )
        except FileExistsError as exc:
            raise HTTPException(409, str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(400, str(exc))

    if is_brief:
        # Mode 0B (design note in stage0_intake.py): new-project is seeded
        # with the brief content itself so the story-pollution guard has
        # something to fingerprint at creation time; stage0 persists the
        # brief separately to input/brief.md and later re-pins the
        # blueprint's title_hash once it generates the real script.
        (project_dir / "input" / "brief.md").write_text(seed_text, encoding="utf-8")

    bp = Blueprint.load(project_dir)
    return _bp_summary(bp)


@router.get("/{slug}/status")
def project_status(slug: str) -> dict[str, Any]:
    project_dir = _project_dir(slug)
    if not (project_dir / "blueprint.json").exists():
        raise HTTPException(404, f"no such project: {slug!r}")
    bp = Blueprint.load(project_dir)

    stages: dict[str, Any] = {}
    for stage in STAGE_ORDER:
        status, error = _stage_status(slug, stage, bp.stages[stage].status)
        stages[stage] = {"status": status, "error": error}

    scores = Scores(project_dir / "scores.sqlite")
    try:
        report = scores.report()
    finally:
        scores.close()

    flags: list[dict[str, Any]] = []
    integration_path = project_dir / "stage0_integration.json"
    if integration_path.exists():
        import json

        data = json.loads(integration_path.read_text(encoding="utf-8"))
        flags.append({"stage": "stage0", **data})

    return {
        "slug": bp.slug,
        "story_id": bp.story_id,
        "fps": bp.fps,
        "stages": stages,
        "scores": report,
        "flags": flags,
    }


@router.post("/{slug}/run/{stage}")
def run_stage(slug: str, stage: str) -> dict[str, Any]:
    project_dir = _project_dir(slug)
    if not (project_dir / "blueprint.json").exists():
        raise HTTPException(404, f"no such project: {slug!r}")
    if stage not in STAGE_ORDER:
        raise HTTPException(404, f"unknown stage {stage!r}; valid: {STAGE_ORDER}")

    key = (slug, stage)
    with _lock:
        thread = _running.get(key)
        if thread is not None and thread.is_alive():
            raise HTTPException(409, f"{slug}/{stage} is already running")

        def _worker() -> None:
            try:
                result = pipeline_run.run_stage(
                    slug, stage, projects_dir=get_projects_root()
                )
                with _lock:
                    _last_error[key] = None
                    if result is not None:
                        _last_result[key] = result
            except NotImplementedError as exc:
                with _lock:
                    _last_error[key] = {"type": "not_built", "message": str(exc)}
            except Exception as exc:  # noqa: BLE001 - surfaced via /status, never crashes the thread
                with _lock:
                    _last_error[key] = {
                        "type": "failed",
                        "message": f"{type(exc).__name__}: {exc}",
                    }
            finally:
                with _lock:
                    _running.pop(key, None)

        t = threading.Thread(target=_worker, daemon=True, name=f"pipeline-{slug}-{stage}")
        _running[key] = t
        t.start()

    return {"started": True}
