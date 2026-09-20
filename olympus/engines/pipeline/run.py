#!/usr/bin/env python
"""Studio pipeline runner: new-project / run-stage / run-all.

CLI:
    python run.py new-project <slug> --seed <file> [--fps N] [--mode 0b|0a|0i]
    python run.py run <slug> <stage>
    python run.py all <slug>
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from typing import Callable

_ENGINE_ROOT = Path(__file__).resolve().parent
_STACK_ROOT = _ENGINE_ROOT.parent.parent.parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))
if str(_STACK_ROOT) not in sys.path:
    sys.path.insert(0, str(_STACK_ROOT))

from pipeline.blueprint import STAGE_ORDER, Blueprint, create_blueprint  # noqa: E402
from pipeline.scores import Scores  # noqa: E402
from pipeline import stages as S  # noqa: E402
from pipeline.optimizer import HardwareOptimizer  # noqa: E402


def _projects_root(projects_dir: str | Path | None) -> Path:
    if projects_dir is not None:
        return Path(projects_dir)
    return _ENGINE_ROOT / "projects"


def new_project(slug: str, script_path: str | Path, fps: int = 24, *,
                projects_dir: str | Path | None = None,
                mode: str = "0b",
                panel_upload: str | Path | None = None) -> Path:
    script_path = Path(script_path)
    if not script_path.exists():
        raise FileNotFoundError(f"seed file not found: {script_path}")
    root = _projects_root(projects_dir)
    project_dir = root / slug
    if project_dir.exists():
        raise FileExistsError(f"project already exists: {project_dir}")
    (project_dir / "input").mkdir(parents=True)
    (project_dir / "logs").mkdir(parents=True)
    seed_text = script_path.read_text(encoding="utf-8", errors="replace")
    (project_dir / "input" / "script.txt").write_text(seed_text, encoding="utf-8")
    if mode == "0b":
        brief = seed_text if "word_target" in seed_text[:500] else f"---\nword_target: 800\n---\n\n{seed_text}"
        (project_dir / "input" / "brief.md").write_text(brief, encoding="utf-8")
    elif mode == "0a":
        (project_dir / "input" / "source.txt").write_text(seed_text, encoding="utf-8")
    elif mode == "0s":
        # Faithful intake: the seed IS the script, copied verbatim. Stage0
        # must not expand/transform it — it only splits scenes + repins hash.
        (project_dir / "input" / "source.txt").write_text(seed_text, encoding="utf-8")
    if mode == "0i" and panel_upload is not None:
        _copy_panels(Path(panel_upload), project_dir / "input" / "panels")
    bp = create_blueprint(seed_text, slug=slug, fps=fps, mode=mode)
    bp.write(project_dir)
    Scores(project_dir / "scores.sqlite").close()
    return project_dir


def _copy_panels(upload: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    if upload.suffix.lower() == ".zip":
        with zipfile.ZipFile(upload) as zf:
            for m in zf.namelist():
                if m.endswith("/"):
                    continue
                if Path(m).suffix.lower() in exts:
                    (dest / Path(m).name).write_bytes(zf.read(m))
    elif upload.is_dir():
        for p in sorted(upload.iterdir()):
            if p.is_file() and p.suffix.lower() in exts:
                (dest / p.name).write_bytes(p.read_bytes())


def _animation_enabled() -> bool:
    try:
        from stack.config import cfg

        return bool(getattr(getattr(cfg, "animation", None), "enabled", False))
    except Exception:
        return False


def run_stage(slug: str, stage: str, *, projects_dir: str | Path | None = None,
              brief_path: str | Path | None = None, force: bool = False,
              config=None, source_path: str | Path | None = None,
              panel_upload: str | Path | None = None,
              word_target: int | None = None, brief_text: str | None = None,
              source_text: str | None = None) -> dict | None:
    if stage not in STAGE_ORDER:
        raise ValueError(f"unknown stage {stage!r}; valid: {STAGE_ORDER}")
    project_dir = _projects_root(projects_dir) / slug
    if not (project_dir / "blueprint.json").exists():
        raise FileNotFoundError(f"no such project: {project_dir}")
    HardwareOptimizer.default().write_manifest(project_dir)
    if stage != "stage0":
        from pipeline.blueprint import verify_story_guard

        verify_story_guard(project_dir)
    scores = Scores(project_dir / "scores.sqlite")
    try:
        if not force:
            scores.require_stage(stage)
        else:
            scores.clear_stage(stage)
    finally:
        scores.close()

    brief = brief_text
    if brief_path is not None:
        brief = Path(brief_path).read_text(encoding="utf-8", errors="replace")
    source_txt = source_text
    if source_path is not None and Path(source_path).exists():
        source_txt = Path(source_path).read_text(encoding="utf-8", errors="replace")

    if stage == "stage0":
        return S.run_stage0(project_dir, brief=brief, source_text=source_txt,
                            word_target=word_target or 800)
    if stage == "stage0_dossier":
        return S.run_dossier(project_dir)
    if stage == "stage1":
        return S.run_worldbible(project_dir)
    if stage == "stage1_world":
        return S.run_world_enrich(project_dir)
    if stage == "stage1r":
        return S.run_references(project_dir)
    if stage == "stage3":
        return S.run_storyboard(project_dir)
    if stage == "stage2":
        return S.run_screenplay(project_dir)
    if stage == "stage3b":
        return S.run_images(project_dir)
    if stage == "stage4":
        return S.run_audio(project_dir)
    if stage == "stage3c":
        return S.run_animation(project_dir, enabled=_animation_enabled())
    if stage == "stage_vlm_review":
        return S.run_review(project_dir)
    if stage == "stage5":
        return S.run_assembly(project_dir)
    raise ValueError(f"no implementation for {stage!r}")


def run_all(slug: str, *, projects_dir: str | Path | None = None,
            brief_path: str | Path | None = None, source_path=None,
            panel_upload=None, word_target: int | None = None,
            run_critique: bool = False, step: bool = False, quick: bool = False,
            should_stop: Callable[[], bool] | None = None) -> dict:
    from pipeline.blueprint import verify_story_guard

    project_dir = _projects_root(projects_dir) / slug
    HardwareOptimizer.default().write_manifest(project_dir)
    results: dict[str, dict] = {}
    for stage in STAGE_ORDER:
        if should_stop and should_stop():
            results["_stopped"] = {"at": stage}
            break
        # Resume-safe: skip proven-complete stages.
        try:
            sc = Scores(project_dir / "scores.sqlite")
            done = sc.is_done(stage)
            sc.close()
        except Exception:
            done = False
        if done:
            continue
        if stage == "stage1r" and quick:
            S.run_references(project_dir, quick=True)
            results[stage] = {"quick": True}
        elif stage == "stage0":
            bp = Blueprint.load(project_dir)
            btxt = None
            if brief_path is not None and Path(brief_path).exists():
                btxt = Path(brief_path).read_text(encoding="utf-8", errors="replace")
            results[stage] = S.run_stage0(
                project_dir,
                brief=btxt or ((project_dir / "input" / "brief.md").read_text(encoding="utf-8") if (project_dir / "input" / "brief.md").exists() and bp.mode == "0b" else None),
                source_text=(Path(source_path).read_text(encoding="utf-8") if source_path and Path(source_path).exists() else None),
                word_target=word_target or (300 if quick else 800))
        else:
            results[stage] = run_stage(slug, stage, projects_dir=projects_dir) or {}
        verify_story_guard(project_dir)
        if step:
            break
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Studio pipeline runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_new = sub.add_parser("new-project")
    p_new.add_argument("slug")
    p_new.add_argument("--seed", required=True)
    p_new.add_argument("--fps", type=int, default=24)
    p_new.add_argument("--mode", default="0b")
    p_run = sub.add_parser("run")
    p_run.add_argument("slug")
    p_run.add_argument("stage")
    p_all = sub.add_parser("all")
    p_all.add_argument("slug")
    args = ap.parse_args()
    if args.cmd == "new-project":
        new_project(args.slug, args.seed, fps=args.fps, mode=args.mode)
    elif args.cmd == "run":
        print(run_stage(args.slug, args.stage))
    elif args.cmd == "all":
        print(run_all(args.slug))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
