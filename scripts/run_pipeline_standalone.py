#!/usr/bin/env python3
"""
Standalone pipeline runner — no agent, no kernel, no browser required.

Runs the full Anime Pipeline v2 directly from the CLI using the permanent
config in stack.toml (including the NVIDIA NIM DeepSeek model).

Usage:
    # Full run from a brief (most common — no agent needed):
    python scripts/run_pipeline_standalone.py --slug my_episode --brief brief.md

    # From source text:
    python scripts/run_pipeline_standalone.py --slug my_episode --source story.txt

    # From panel zip:
    python scripts/run_pipeline_standalone.py --slug my_episode --panels panels.zip

    # Resume / run remaining stages only:
    python scripts/run_pipeline_standalone.py --slug my_episode

    # Single stage:
    python scripts/run_pipeline_standalone.py --slug my_episode --stage stage3b

    # Override NIM model (e.g. switch to DeepSeek):
    python scripts/run_pipeline_standalone.py --slug my_episode --nim-model deepseek-ai/deepseek-v4-flash-0731

The config is permanent: stack.toml [nim] and ~/.config/opencode/opencode.json
both contain the DeepSeek model. No agent session is needed.
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

from pipeline.config import PipelineConfig
from pipeline.nim_client import resolve_api_key


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Standalone Anime Pipeline runner (no agent required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--slug", required=False, default=None, help="project slug (e.g. my_episode)")
    p.add_argument("--brief", default=None, help="path to brief.md (mode 0b, first run only)")
    p.add_argument("--source", default=None, help="path to source.txt (mode 0a, first run only)")
    p.add_argument("--panels", default=None, help="zip or folder of panels (mode 0i, first run only)")
    p.add_argument("--stage", default=None, help="run a single stage (e.g. stage3b); omit to run all remaining stages")
    p.add_argument("--fps", type=int, default=24, help="FPS for new projects (24/30/60)")
    p.add_argument("--mode", default="0b", choices=["0b", "0a", "0i"], help="stage0 intake mode for new projects")
    p.add_argument("--force", action="store_true", help="force regeneration for stage3b/stage4")
    p.add_argument("--word-target", type=int, default=None, help="word budget for mode 0a")
    p.add_argument("--nim-model", default=None, help="override NIM model (e.g. deepseek-ai/deepseek-v4-flash-0731)")
    p.add_argument("--list-models", action="store_true", help="list configured models and exit")
    p.add_argument("--no-critique", action="store_true", help="disable self-critique loop for 'all' runs")
    return p.parse_args()


def list_models():
    cfg = PipelineConfig.load()
    print("=== Configured models (stack.toml) ===")
    print(f"  [ollama] script  : {cfg.models.llm_script}")
    print(f"  [ollama] vision  : {cfg.models.llm_vision}")
    print(f"  [ollama] review  : {cfg.models.llm_review}")
    print(f"  [ollama] default : {cfg.models.llm_default}")
    print(f"  [comfyui] primary: {cfg.models.image_primary}")
    print(f"  [nim] enabled    : {cfg.nim.enabled}")
    print(f"  [nim] model      : {cfg.nim.model}")
    print(f"  [nim] models     : {cfg.nim.models}")
    key = resolve_api_key(cfg.nim)
    print(f"  [nim] key present: {bool(key)} ({'env/file' if key else 'missing — set NVIDIA_API_KEY'})")
    print(f"  [nim] base_url   : {cfg.nim.base_url}")
    # Also show opencode config if present
    try:
        import json
        oc = Path.home() / ".config" / "opencode" / "opencode.json"
        if oc.exists():
            data = json.loads(oc.read_text())
            nvidia = data.get("provider", {}).get("nvidia", {})
            print(f"  [opencode] nvidia models: {list(nvidia.get('models', {}).keys())}")
    except Exception:
        pass


def main() -> int:
    args = parse_args()

    if args.list_models:
        list_models()
        return 0

    if not args.slug:
        print("error: --slug is required (unless using --list-models)", file=sys.stderr)
        return 2

    # Optional NIM model override — patch the loaded config in-memory
    # (does not write to stack.toml; for permanent change edit stack.toml [nim] model)
    cfg = PipelineConfig.load()
    if args.nim_model:
        if args.nim_model not in cfg.nim.models:
            print(f"[warn] {args.nim_model!r} not in configured nim.models {cfg.nim.models}", file=sys.stderr)
            print("       continuing anyway — ensure the model exists on NVIDIA NIM", file=sys.stderr)
        cfg.nim.model = args.nim_model
        print(f"[info] NIM model overridden to: {cfg.nim.model}")

    # Import run helpers lazily after config is ready
    import run as pipeline_run

    slug = args.slug
    projects_dir = cfg.projects_dir()

    # If project doesn't exist, create it
    project_dir = projects_dir / slug
    if not project_dir.exists():
        print(f"[info] creating new project: {slug} (mode={args.mode}, fps={args.fps})")
        # For new projects we need a seed script; use brief/source/panels or a minimal placeholder
        seed = None
        if args.brief and Path(args.brief).exists():
            seed = Path(args.brief)
        elif args.source and Path(args.source).exists():
            seed = Path(args.source)
        else:
            # Create a minimal temp seed
            import tempfile
            tmp = Path(tempfile.gettempdir()) / f"{slug}_seed.txt"
            tmp.write_text(f"Project {slug} — seed for mode {args.mode}\n", encoding="utf-8")
            seed = tmp
        pipeline_run.new_project(slug, seed, fps=args.fps, mode=args.mode,
                                 panel_upload=args.panels, projects_dir=projects_dir)
        print(f"[ok] project created at {project_dir}")

        # Persist brief/source for stage0 if provided and not already copied
        if args.mode == "0b" and args.brief:
            brief_src = Path(args.brief)
            if brief_src.exists():
                dst = project_dir / "input" / "brief.md"
                dst.parent.mkdir(parents=True, exist_ok=True)
                text = brief_src.read_text(encoding="utf-8")
                if "word_target" not in text:
                    text = "---\nword_target: 800\n---\n\n" + text
                dst.write_text(text, encoding="utf-8")
                print(f"[ok] brief copied to {dst}")
        elif args.mode == "0a" and args.source:
            src = Path(args.source)
            if src.exists():
                dst = project_dir / "input" / "source.txt"
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"[ok] source copied to {dst}")

    # Run
    if args.stage:
        print(f"[run] {slug} :: {args.stage} ...")
        result = pipeline_run.run_stage(
            slug, args.stage, projects_dir=projects_dir,
            brief_path=args.brief, source_path=args.source,
            panel_upload=args.panels, word_target=args.word_target,
            force=args.force, config=cfg,
        )
        print(f"[done] {args.stage}: {result}")
    else:
        print(f"[run] {slug} :: all remaining stages ...")
        results = pipeline_run.run_all(
            slug, projects_dir=projects_dir,
            brief_path=args.brief, source_path=args.source,
            panel_upload=args.panels, word_target=args.word_target,
            run_critique=not args.no_critique,
        )
        print(f"[done] all stages complete for {slug}")

    # Show final status
    try:
        from pipeline.blueprint import Blueprint
        bp = Blueprint.load(project_dir)
        from pipeline.scores import Scores
        scores = Scores(project_dir / "scores.sqlite")
        print("\n=== Stage ledger ===")
        for stage in bp.stages:
            info = scores.metrics_for(stage) if scores.is_done(stage) else {}
            print(f"  {stage}: {bp.stages[stage].status} {info}")
        scores.close()
    except Exception as e:
        print(f"[warn] could not load final ledger: {e}", file=sys.stderr)

    print(f"\n[info] artifacts: {project_dir}")
    print(f"[info] run again with --stage <name> to re-run a single stage, or without --stage to resume")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
