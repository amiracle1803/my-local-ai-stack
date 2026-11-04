#!/usr/bin/env python3
"""
Standalone pipeline runner — no agent, no kernel, no browser required.

Runs the Studio anime/manga pipeline (script intake -> complete video)
directly from the CLI. Same engine the dashboard drives via /api/pipeline.

Usage:
    # Full run from a brief (most common — no agent needed):
    python scripts/run_pipeline_standalone.py --slug my_episode --brief brief.md

    # From a source story (transform) or faithful script (verbatim):
    python scripts/run_pipeline_standalone.py --slug my_episode --source story.txt --mode 0a
    python scripts/run_pipeline_standalone.py --slug my_episode --source script.txt --mode 0s

    # From panel zip:
    python scripts/run_pipeline_standalone.py --slug my_episode --panels panels.zip --mode 0i

    # Resume / run remaining stages only:
    python scripts/run_pipeline_standalone.py --slug my_episode

    # Single stage:
    python scripts/run_pipeline_standalone.py --slug my_episode --stage stage3b

Local-first: Ollama for story text, Voice Studio for TTS, ffmpeg for
assembly — each with a deterministic offline fallback, so a run stays
green even when a service is down. Set OLYMPUS_REAL_COMFY=1 to render
stage3b panels through a local ComfyUI (:8188) instead of placeholders.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Resolve repo root (two levels up from scripts/)
REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_ROOT = REPO_ROOT / "olympus" / "engines" / "pipeline"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from stack.config import cfg


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Standalone Studio pipeline runner (no agent required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--slug", required=False, default=None, help="project slug (e.g. my_episode)")
    p.add_argument("--brief", default=None, help="path to brief.md (mode 0b, first run only)")
    p.add_argument("--source", default=None, help="path to source/script text (modes 0a/0s, first run only)")
    p.add_argument("--panels", default=None, help="zip or folder of panels (mode 0i, first run only)")
    p.add_argument("--stage", default=None, help="run a single stage (e.g. stage3b); omit to run all remaining stages")
    p.add_argument("--fps", type=int, default=24, help="FPS for new projects (24/30/60)")
    p.add_argument("--mode", default="0b", choices=["0b", "0a", "0s", "0i"],
                   help="stage0 intake mode for new projects")
    p.add_argument("--force", action="store_true", help="force rerun even if the stage is marked done")
    p.add_argument("--word-target", type=int, default=None, help="word budget for brief expansion (mode 0b)")
    p.add_argument("--quick", action="store_true", help="quick run: capped references")
    p.add_argument("--step", action="store_true", help="run one stage then stop (review before continuing)")
    p.add_argument("--list-models", action="store_true", help="list configured models and exit")
    return p.parse_args()


def list_models():
    print("=== Configured models (stack.toml) ===")
    print(f"  [ollama] script : {cfg.ollama.models.script}")
    print(f"  [ollama] vision : {cfg.ollama.models.vision}")
    print(f"  [ollama] review : {cfg.ollama.models.review}")
    print(f"  [ollama] default: {cfg.ollama.models.default}")
    print(f"  [voice]  engine : {cfg.voice.engine} ({cfg.voice.url})")
    print(f"  [nim]    model  : {cfg.nim.model} (opt-in judge only)")
    print(f"  [animation] enabled: {cfg.animation.enabled} (OFF = panels mode)")


def main() -> int:
    args = parse_args()

    if args.list_models:
        list_models()
        return 0

    if not args.slug:
        print("error: --slug is required (unless using --list-models)", file=sys.stderr)
        return 2

    import run as pipeline_run

    slug = args.slug
    projects_dir = PIPELINE_ROOT / "projects"

    # If project doesn't exist, create it
    project_dir = projects_dir / slug
    if not project_dir.exists():
        print(f"[info] creating new project: {slug} (mode={args.mode}, fps={args.fps})")
        seed = None
        if args.brief and Path(args.brief).exists():
            seed = Path(args.brief)
        elif args.source and Path(args.source).exists():
            seed = Path(args.source)
        else:
            import tempfile
            tmp = Path(tempfile.gettempdir()) / f"{slug}_seed.txt"
            tmp.write_text(f"Project {slug} — seed for mode {args.mode}\n", encoding="utf-8")
            seed = tmp
        pipeline_run.new_project(slug, seed, fps=args.fps, mode=args.mode,
                                 panel_upload=args.panels, projects_dir=projects_dir)
        print(f"[ok] project created at {project_dir}")

    # Run
    if args.stage:
        print(f"[run] {slug} :: {args.stage} ...")
        result = pipeline_run.run_stage(
            slug, args.stage, projects_dir=projects_dir,
            brief_path=args.brief, source_path=args.source,
            panel_upload=args.panels, word_target=args.word_target,
            force=args.force,
        )
        print(f"[done] {args.stage}: {result}")
    else:
        print(f"[run] {slug} :: all remaining stages ...")
        results = pipeline_run.run_all(
            slug, projects_dir=projects_dir,
            brief_path=args.brief, source_path=args.source,
            panel_upload=args.panels, word_target=args.word_target,
            step=args.step, quick=args.quick,
        )
        print(f"[done] stages: {sorted(results)}")

    # Show final status
    try:
        from pipeline.blueprint import Blueprint, STAGE_ORDER
        bp = Blueprint.load(project_dir)
        from pipeline.scores import Scores
        scores = Scores(project_dir / "scores.sqlite")
        print("\n=== Stage ledger ===")
        for stage in STAGE_ORDER:
            entry = bp.stages.get(stage)
            info = scores.metrics_for(stage) if scores.is_done(stage) else {}
            print(f"  {stage}: {entry.status if entry else '?'} {info}")
        scores.close()
    except Exception as e:
        print(f"[warn] could not load final ledger: {e}", file=sys.stderr)

    print(f"\n[info] artifacts: {project_dir}")
    print("[info] run again with --stage <name> to re-run a single stage, or without --stage to resume")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
