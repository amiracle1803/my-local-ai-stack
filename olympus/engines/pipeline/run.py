#!/usr/bin/env python
"""Anime Pipeline v2 CLI (design section 1).

Commands::

    run.py new-project <slug> --script <file> [--fps N]
    run.py report <slug>
    run.py run <slug> <stage>

All stages (0-5) have working implementations. Known gaps (LoRA training,
lip-sync, music bed) are gated contingencies recorded in per-stage scorecards.
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
    stage0_dossier,
    stage1_worldbible,
    stage1_world,
    stage1r_references,
    stage2_screenplay,
    stage3_storyboard,
    stage3b_images,
    stage3c_animation,
    stage4_audio,
    stage5_assembly,
    stage_vlm_review,
    stage_critique,
    labeling,
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
    # ContingencyStop / ComfyError / Stage3BError / Stage5Error / the voice-
    # studio-down error all subclass RuntimeError -- report them cleanly too
    # (consistency review 2026-07-11, finding 1).
    RuntimeError,
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
    mode: str = "0b",
    panel_upload: str | Path | None = None,
) -> Path:
    """Create ``projects/<slug>/`` with input/script.txt + blueprint.json +
    an initialized scores.sqlite. Returns the project directory.

    ``mode`` selects the stage0 intake mode (0b generate-from-brief / 0a
    transform-from-source / 0i import-from-panels) and is stored on the
    blueprint. For 0i, ``panel_upload`` (zip or folder of panels) is copied
    into ``input/panels/``; the script arg seeds a placeholder identity.
    """
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

    if mode == "0i":
        # For import mode the seed script is just a placeholder identity; the
        # panels drive the real content. Copy the upload into input/panels/.
        if panel_upload is not None:
            panels_dir = project_dir / "input" / "panels"
            panels_dir.mkdir(parents=True, exist_ok=True)
            _copy_panels(Path(panel_upload), panels_dir)

    bp = create_blueprint(script_text, slug=slug, fps=fps, mode=mode)
    bp.write(project_dir)

    # Initialize the scorecard db so the gate has a store from the start.
    Scores(project_dir / "scores.sqlite").close()

    return project_dir


def _copy_panels(upload: Path, panels_dir: Path) -> None:
    """Copy panels from a zip or folder into ``panels_dir`` (flat, no nesting)."""
    import zipfile as _zipfile

    _EXTS = {".png", ".jpg", ".jpeg", ".webp"}
    if upload.suffix.lower() == ".zip":
        with _zipfile.ZipFile(upload) as zf:
            for m in zf.namelist():
                if m.endswith("/"):
                    continue
                if Path(m).suffix.lower() in _EXTS:
                    (panels_dir / Path(m).name).write_bytes(zf.read(m))
    elif upload.is_dir():
        for p in sorted(upload.iterdir()):
            if p.is_file() and p.suffix.lower() in _EXTS:
                (panels_dir / p.name).write_bytes(p.read_bytes())
    else:
        raise FileNotFoundError(f"panel upload must be a zip or folder: {upload}")


# --------------------------------------------------------------------------
# stage dispatch
# --------------------------------------------------------------------------
def run_stage(
    slug: str,
    stage: str,
    *,
    projects_dir: str | Path | None = None,
    brief_path: str | Path | None = None,
    force: bool = False,
    config: PipelineConfig | None = None,
    source_path: str | Path | None = None,
    panel_upload: str | Path | None = None,
    word_target: int | None = None,
) -> dict | None:
    """Run one stage. All stages (0-5) have real implementations. Known
    gaps (LoRA training, lip-sync, music bed) surface as gated scorecard
    contingencies rather than blocking execution."""
    if stage not in STAGE_ORDER:
        raise ValueError(f"unknown stage {stage!r}; valid: {STAGE_ORDER}")
    project_dir = _projects_root(projects_dir) / slug
    if not project_dir.exists():
        raise FileNotFoundError(f"no such project: {project_dir}")

    # 1. Pollution guard runs FIRST (before the gate) so a swapped script is
    #    caught regardless of ledger state. (stage0 itself writes/repins the
    #    hash, so it runs before the guard for intake modes.)
    if stage != "stage0":
        verify_story_guard(project_dir)

    # 2. Structural stage gate, then (for implemented stages) the real work --
    #    both share one Scores handle so the stage can record metrics.
    scores = Scores(project_dir / "scores.sqlite")
    try:
        scores.require_stage(stage)

        cfg = config or PipelineConfig.load()
        if stage == "stage0":
            from pipeline import stage0a_transform, stage0i_import

            bp = Blueprint.load(project_dir)
            mode = getattr(bp, "mode", "0b") or "0b"
            if mode == "0a":
                return stage0a_transform.run(
                    project_dir, cfg, scores,
                    source_path=source_path,
                    word_target=word_target or 900,
                )
            if mode == "0i":
                return stage0i_import.run(
                    project_dir, cfg, scores,
                    upload=panel_upload,
                )
            return stage0_intake.run(project_dir, cfg, scores, brief_path=brief_path)

        if stage == "stage1":
            # M2a (characters) then M2b (world/relationships/contradictions/
            # expansion) -- one stage, two passes; M2b marks stage1 done.
            partial = stage1_worldbible.run(project_dir, cfg, scores)
            full = stage1_world.run(project_dir, cfg, scores)
            return {"m2a": partial, "m2b": full}

        dispatch = {
            "stage0_dossier": stage0_dossier.run,
            "stage1_world": stage1_world.run,
            "stage1r": stage1r_references.run,
            "stage3": stage3_storyboard.run,
            "stage2": stage2_screenplay.run,
            "stage3b": stage3b_images.run,
            "stage4": stage4_audio.run,
            "stage3c": stage3c_animation.run,
            "stage_vlm_review": stage_vlm_review.run,
            "stage5": stage5_assembly.run,
        }
        if stage == "stage3b":
            result = dispatch[stage](project_dir, cfg, scores)
            # Panels produced -> refresh the human-readable labels index.
            labeling.write_labels(project_dir)
            return result
        if stage == "stage4":
            return dispatch[stage](project_dir, cfg, scores, force=bool(force))
        result = dispatch[stage](project_dir, cfg, scores)
        if stage in ("stage3c", "stage_vlm_review"):
            # Clips produced/edited -> refresh the labels index (panels + clips).
            labeling.write_labels(project_dir)
        return result
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
    project_dir = new_project(
        args.slug, args.script, fps=args.fps, mode=args.mode, panel_upload=args.panels
    )
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
    result = run_stage(
        args.slug, args.stage, brief_path=args.brief, force=args.force,
        source_path=args.source, panel_upload=args.panels, word_target=args.word_target,
    )
    if result is not None:
        print(json.dumps(result, indent=2))
    return 0


def run_all(
    slug: str,
    *,
    projects_dir: str | Path | None = None,
    brief_path: str | Path | None = None,
    source_path: str | Path | None = None,
    panel_upload: str | Path | None = None,
    word_target: int | None = None,
    run_critique: bool = True,
    retry_on_critique: bool = True,
) -> list[dict | None]:
    """``run.py all`` (design 0.2): run every stage in STAGE_ORDER unattended,
    skipping stages the scorecard already proves complete (resume-safe).

    ``source_path``/``panel_upload``/``word_target`` are forwarded to stage0 for
    mode 0a / 0i intake, mirroring ``run_stage`` so the Studio RUN ALL button and
    the CLI ``all`` command can drive any intake mode identically.

    If run_critique=True, runs the self-critique loop after each stage.
    If retry_on_critique=True, retries stages that fail the critique gate.
    """
    project_dir = _projects_root(projects_dir) / slug
    config = PipelineConfig.load()
    results: list[dict | None] = []

    # Initialize LLM for critique
    from pipeline.llm import PipelineLLM
    llm = PipelineLLM(config, prompts_dir=_ENGINE_ROOT / "prompts", logs_dir=project_dir / "logs")

    for stage in STAGE_ORDER:
        scores = Scores(project_dir / "scores.sqlite")
        try:
            complete = scores.is_done(stage) and not scores.missing_metrics(stage)
        finally:
            scores.close()
        if complete:
            print(f"[skip] {stage} already complete")
            results.append({"skipped": True, "stage": stage})
            continue

        # Run the stage
        print(f"[run ] {stage} ...")
        result = run_stage(
            slug, stage, projects_dir=projects_dir, brief_path=brief_path,
            source_path=source_path, panel_upload=panel_upload, word_target=word_target,
        )
        results.append(result)

        # Run critique after stage completion (if enabled)
        if run_critique:
            print(f"[critique] {stage} ...")
            critique_result = stage_critique.run_stage_critique(
                project_dir=project_dir,
                stage_name=stage,
                llm=llm,
                config=config,
            )

            # Record critique in results
            results.append({"critique": stage_critique.asdict(critique_result)})

            if not critique_result.passes:
                print(f"  [WARN] Critique score: {critique_result.consistency_score:.2f} - {len(critique_result.critical_issues)} critical issues")
                for issue in critique_result.critical_issues:
                    print(f"    - {issue.type}: {issue.description}")
                for fix in critique_result.suggested_fixes:
                    print(f"    Suggestion: {fix.action} {fix.stage} - {fix.details}")

                # Retry logic
                if retry_on_critique and stage_critique.should_retry_stage(critique_result, config):
                    print(f"  [retry] Critique below threshold, retrying {stage}...")
                    actions = stage_critique.get_retry_actions(critique_result)
                    for action in actions:
                        print(f"    Action: {action}")

                    # Re-run the stage
                    print(f"[run ] {stage} (retry) ...")
                    retry_result = run_stage(
                        slug, stage, projects_dir=projects_dir, brief_path=brief_path,
                        source_path=source_path, panel_upload=panel_upload, word_target=word_target,
                    )
                    results.append({"retry": True, "stage": stage, "result": retry_result})

                    # Run critique again on retry
                    retry_critique = stage_critique.run_stage_critique(
                        project_dir=project_dir,
                        stage_name=stage,
                        llm=llm,
                        config=config,
                    )
                    results.append({"critique_retry": stage_critique.asdict(retry_critique)})
                    if retry_critique.passes:
                        print(f"  [ok] Retry passed critique")
                    else:
                        print(f"  [FAIL] Retry still failing: score={retry_critique.consistency_score:.2f}")
            else:
                print(f"  [ok] Critique passed: {critique_result.consistency_score:.2f}")

    return results


def _cmd_all(args: argparse.Namespace) -> int:
    run_all(
        args.slug,
        brief_path=args.brief,
        source_path=args.source,
        panel_upload=args.panels,
        word_target=args.word_target,
        run_critique=not args.no_critique,
        retry_on_critique=not args.no_retry,
    )
    print("[ok] all stages complete")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run.py", description="Anime Pipeline v2 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new-project", help="create a new project")
    p_new.add_argument("slug")
    p_new.add_argument("--script", required=True, help="path to the source script .txt (or a placeholder seed for 0i)")
    p_new.add_argument("--fps", type=int, default=24, help="24-60, snapped to 24/30/60")
    p_new.add_argument("--mode", default="0b", choices=["0b", "0a", "0i"],
                       help="stage0 intake mode: 0b generate-from-brief (default) | 0a transform-from-source | 0i import-from-panels")
    p_new.add_argument("--panels", default=None, help="0i only: zip or folder of panels to import")
    p_new.set_defaults(func=_cmd_new_project)

    p_rep = sub.add_parser("report", help="print blueprint + scorecard ledger")
    p_rep.add_argument("slug")
    p_rep.set_defaults(func=_cmd_report)

    p_run = sub.add_parser("run", help="run a stage (all stages 0-5 implemented)")
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
    p_run.add_argument(
        "--force",
        action="store_true",
        help="stage3b and stage4: force regeneration of all panels or audio (bypasses the resume-safe skip)",
    )
    p_run.add_argument(
        "--source",
        default=None,
        help="stage0 mode 0a only: path to the source text to transform",
    )
    p_run.add_argument(
        "--panels",
        default=None,
        help="stage0 mode 0i only: zip or folder of panels to import (first run)",
    )
    p_run.add_argument(
        "--word-target",
        type=int,
        default=None,
        help="stage0 mode 0a only: total prose word budget for the transformed episode",
    )
    p_run.set_defaults(func=_cmd_run)

    p_all = sub.add_parser("all", help="run every remaining stage in order (design 0.2)")
    p_all.add_argument("slug")
    p_all.add_argument("--brief", default=None, help="stage0 brief (first run only)")
    p_all.add_argument("--source", default=None, help="stage0 mode 0a only: path to source text")
    p_all.add_argument("--panels", default=None, help="stage0 mode 0i only: zip/folder of panels")
    p_all.add_argument("--word-target", type=int, default=None, help="stage0 mode 0a: prose word budget")
    p_all.add_argument("--no-critique", action="store_true", help="disable self-critique loop between stages")
    p_all.add_argument("--no-retry", action="store_true", help="disable auto-retry on critique failure")
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
