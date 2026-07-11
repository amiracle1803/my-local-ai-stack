#!/usr/bin/env python
"""Anime Pipeline v2 CLI (design section 1, milestone M0).

Commands::

    run.py new-project <slug> --script <file> [--fps N]
    run.py report <slug>
    run.py run <slug> <stage>

M0 stage functions are stubs: they enforce the real scores gate
(``require_stage``) and then raise ``NotImplementedError`` -- the gating and
the pollution guard are live even though no stage does work yet.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the `pipeline` package importable no matter the working directory.
_ENGINE_ROOT = Path(__file__).resolve().parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from pipeline import (  # noqa: E402
    stage0_intake,
    stage1_worldbible,
    stage1_world,
    stage1r_references,
    stage2_screenplay,
    stage3_storyboard,
    stage3b_images,
    stage3c_animation,
    stage4_audio,
    stage5_assembly,
)
from pipeline.blueprint import (  # noqa: E402
    STAGE_ORDER,
    Blueprint,
    create_blueprint,
    verify_story_guard,
)
from pipeline.blueprint import StoryPollutionError  # noqa: E402
from pipeline.config import BannedModelError, PipelineConfig  # noqa: E402
from pipeline.scores import Scores, SkippedStageError  # noqa: E402
from pipeline.stage0_intake import Stage0Error  # noqa: E402

# Known pipeline failures reported cleanly (no traceback) with exit code 2.
_CLEAN_ERRORS = (
    StoryPollutionError,
    SkippedStageError,
    BannedModelError,
    Stage0Error,
    FileExistsError,
    FileNotFoundError,
    NotImplementedError,
    ValueError,
)


def _projects_root(projects_dir: str | Path | None) -> Path:
    if projects_dir is not None:
        return Path(projects_dir)
    return PipelineConfig.load().projects_dir()


# --------------------------------------------------------------------------
# new-project
# --------------------------------------------------------------------------
def new_project(
    slug: str,
    script_path: str | Path,
    fps: int = 24,
    *,
    projects_dir: str | Path | None = None,
) -> Path:
    """Create ``projects/<slug>/`` with input/script.txt + blueprint.json +
    an initialized scores.sqlite. Returns the project directory."""
    script_path = Path(script_path)
    if not script_path.exists():
        raise FileNotFoundError(f"script file not found: {script_path}")

    root = _projects_root(projects_dir)
    project_dir = root / slug
    if project_dir.exists():
        raise FileExistsError(f"project already exists: {project_dir}")

    (project_dir / "input").mkdir(parents=True)
    (project_dir / "logs").mkdir(parents=True)

    script_text = script_path.read_text(encoding="utf-8")
    (project_dir / "input" / "script.txt").write_text(script_text, encoding="utf-8")

    bp = create_blueprint(script_text, slug=slug, fps=fps)
    bp.write(project_dir)

    # Initialize the scorecard db so the gate has a store from the start.
    Scores(project_dir / "scores.sqlite").close()

    return project_dir


# --------------------------------------------------------------------------
# stage stubs (M0): real gate, no work yet
# --------------------------------------------------------------------------
def run_stage(
    slug: str,
    stage: str,
    *,
    projects_dir: str | Path | None = None,
    brief_path: str | Path | None = None,
    config: PipelineConfig | None = None,
) -> dict | None:
    """Run one stage. M1: stage0 (mode 0B, generate-from-brief) is real. M2a:
    stage1 runs Steps 1-2 (character scan + profiles) and writes a partial
    world bible, but does not mark stage1 done -- M2b completes it. All other
    stages remain pollution-guard -> gate -> ``NotImplementedError`` stubs
    until their milestone lands."""
    if stage not in STAGE_ORDER:
        raise ValueError(f"unknown stage {stage!r}; valid: {STAGE_ORDER}")
    project_dir = _projects_root(projects_dir) / slug
    if not project_dir.exists():
        raise FileNotFoundError(f"no such project: {project_dir}")

    # 1. Pollution guard runs FIRST (before the gate) so a swapped script is
    #    caught regardless of ledger state.
    verify_story_guard(project_dir)

    # 2. Structural stage gate, then (for implemented stages) the real work --
    #    both share one Scores handle so the stage can record metrics.
    scores = Scores(project_dir / "scores.sqlite")
    try:
        scores.require_stage(stage)

        cfg = config or PipelineConfig.load()
        if stage == "stage0":
            return stage0_intake.run(project_dir, cfg, scores, brief_path=brief_path)

        if stage == "stage1":
            # M2a (characters) then M2b (world/relationships/contradictions/
            # expansion) -- one stage, two passes; M2b marks stage1 done.
            partial = stage1_worldbible.run(project_dir, cfg, scores)
            full = stage1_world.run(project_dir, cfg, scores)
            return {"m2a": partial, "m2b": full}

        dispatch = {
            "stage1r": stage1r_references.run,
            "stage2": stage2_screenplay.run,
            "stage3": stage3_storyboard.run,
            "stage3b": stage3b_images.run,
            "stage4": stage4_audio.run,
            "stage3c": stage3c_animation.run,
            "stage5": stage5_assembly.run,
        }
        return dispatch[stage](project_dir, cfg, scores)
    finally:
        scores.close()


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
def report(slug: str, *, projects_dir: str | Path | None = None) -> dict:
    """Return (and, from the CLI, print) the blueprint + scorecard ledger."""
    project_dir = _projects_root(projects_dir) / slug
    if not project_dir.exists():
        raise FileNotFoundError(f"no such project: {project_dir}")
    bp = Blueprint.load(project_dir)
    scores = Scores(project_dir / "scores.sqlite")
    try:
        ledger = scores.report()
    finally:
        scores.close()
    return {"blueprint": bp.model_dump(), "scores": ledger}


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------
def _cmd_new_project(args: argparse.Namespace) -> int:
    project_dir = new_project(args.slug, args.script, fps=args.fps)
    print(f"[ok] created project: {project_dir}")
    print(f"     blueprint: {project_dir / 'blueprint.json'}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    data = report(args.slug)
    bp = data["blueprint"]
    print(f"Project: {bp['slug']}  (story_id={bp['story_id']}, fps={bp['fps']})")
    print(f"title_hash: {bp['title_hash']}")
    print("Stage ledger:")
    for stage, info in data["scores"]["stages"].items():
        flag = "DONE" if info["complete"] else ("partial" if info["done"] else "pending")
        extra = ""
        if info["metrics"]:
            extra = "  metrics=" + json.dumps(info["metrics"])
        if info["missing_metrics"]:
            extra += f"  missing={info['missing_metrics']}"
        print(f"  {stage:8s} {flag:8s}{extra}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    result = run_stage(args.slug, args.stage, brief_path=args.brief)
    if result is not None:
        print(json.dumps(result, indent=2))
    return 0


def run_all(
    slug: str,
    *,
    projects_dir: str | Path | None = None,
    brief_path: str | Path | None = None,
) -> list[dict | None]:
    """``run.py all`` (design 0.2): run every stage in STAGE_ORDER unattended,
    skipping stages the scorecard already proves complete (resume-safe)."""
    project_dir = _projects_root(projects_dir) / slug
    results: list[dict | None] = []
    for stage in STAGE_ORDER:
        scores = Scores(project_dir / "scores.sqlite")
        try:
            complete = scores.is_done(stage) and not scores.missing_metrics(stage)
        finally:
            scores.close()
        if complete:
            print(f"[skip] {stage} already complete")
            continue
        print(f"[run ] {stage} ...")
        results.append(
            run_stage(slug, stage, projects_dir=projects_dir, brief_path=brief_path)
        )
    return results


def _cmd_all(args: argparse.Namespace) -> int:
    run_all(args.slug, brief_path=args.brief)
    print("[ok] all stages complete")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run.py", description="Anime Pipeline v2 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new-project", help="create a new project")
    p_new.add_argument("slug")
    p_new.add_argument("--script", required=True, help="path to the source script .txt")
    p_new.add_argument("--fps", type=int, default=24, help="24-60, snapped to 24/30/60")
    p_new.set_defaults(func=_cmd_new_project)

    p_rep = sub.add_parser("report", help="print blueprint + scorecard ledger")
    p_rep.add_argument("slug")
    p_rep.set_defaults(func=_cmd_report)

    p_run = sub.add_parser("run", help="run a stage (M1: stage0 real, rest gate + stub)")
    p_run.add_argument("slug")
    p_run.add_argument("stage", help=f"one of {STAGE_ORDER}")
    p_run.add_argument(
        "--brief",
        default=None,
        help=(
            "stage0 only (mode 0B): path to a creative brief file (frontmatter: "
            "word_target [required], style_exemplars [optional]). Omit on reruns "
            "once input/brief.md already exists for the project."
        ),
    )
    p_run.set_defaults(func=_cmd_run)

    p_all = sub.add_parser("all", help="run every remaining stage in order (design 0.2)")
    p_all.add_argument("slug")
    p_all.add_argument("--brief", default=None, help="stage0 brief (first run only)")
    p_all.set_defaults(func=_cmd_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except _CLEAN_ERRORS as exc:
        print(f"ERROR [{type(exc).__name__}]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
