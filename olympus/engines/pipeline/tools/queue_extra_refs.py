"""Queue 50 supplementary reference-image jobs for a project, AFTER the main
pipeline run finishes (polls the systemd unit so the production run is never
starved of GPU). Amir, 2026-07-11: "create 50 more jobs to be queued on top
of the ones you are already doing."

Job mix (50 total for a 2-character project):
- 15 extra frames per character (5 new expressions x variant seeds + 5 poses
  + 5 camera framings) -> 30 jobs, future LoRA dataset material
- 20 extra style-lock refs (new subjects, variant seeds)

Usage:  python tools/queue_extra_refs.py <slug> [--wait-unit pipeline-lantern-run.service]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.comfy_client import ComfyClient, ComfyError, ContingencyStop  # noqa: E402
from pipeline.config import PipelineConfig  # noqa: E402
from pipeline.schemas.worldbible import WorldBible  # noqa: E402
from pipeline.stage1r_references import _STYLE_TAIL, _seed_for  # noqa: E402

_EXTRA_EXPRESSIONS = ("surprised expression", "exhausted expression",
                      "gentle smile", "determined glare", "quiet grief")
_EXTRA_POSES = ("walking pose", "kneeling pose", "arms crossed pose",
                "reaching out pose", "looking over shoulder pose")
_EXTRA_FRAMINGS = ("extreme close-up on eyes", "cowboy shot", "silhouette backlit",
                   "low angle full body", "top-down view")
_EXTRA_STYLE_SUBJECTS = (
    "a snowbound shrine at night", "a brass workshop interior", "a caravan in a storm",
    "monastery ruins under snow", "a frozen river crossing", "an oil lamp on a wooden table",
    "prayer flags in wind", "a stone bridge in fog", "bootprints in deep snow",
    "a hearth fire in a dark room", "mountain peaks at dawn", "a rope bridge over a gorge",
    "a supply sled loaded with crates", "icicles on a temple eave", "a candle-lit map table",
    "terraced fields under frost", "a watchtower in moonlight", "wind-carved snow dunes",
    "a monk's cell with a single window", "storm clouds over a valley",
)


def wait_for_unit(unit: str) -> None:
    while True:
        state = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True, text=True,
        ).stdout.strip()
        if state != "active":
            return
        time.sleep(60)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--wait-unit", default=None)
    args = ap.parse_args()

    if args.wait_unit:
        print(f"waiting for {args.wait_unit} to finish before queueing...")
        wait_for_unit(args.wait_unit)

    project_dir = ENGINE_ROOT / "projects" / args.slug
    wb = WorldBible.model_validate_json(
        (project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8")
    )
    config = PipelineConfig.load()
    comfy = ComfyClient(config)
    comfy.unload_ollama()

    jobs: list[tuple[str, str, Path, int]] = []  # (unit, prompt, dest, seed)
    for char in wb.characters[:2]:
        dest = project_dir / "worldbible" / "refs" / char.id / "extra"
        extras = [*_EXTRA_EXPRESSIONS, *_EXTRA_POSES, *_EXTRA_FRAMINGS]
        for j, suffix in enumerate(extras):
            prompt = f"{char.sd_prompt}, {suffix}, plain background, {_STYLE_TAIL}"
            jobs.append((f"{char.id}/extra_{j:02d}", prompt, dest, _seed_for(char.id, 9) + j))
    style_dest = project_dir / "worldbible" / "refs" / "_style" / "extra"
    for j, subject in enumerate(_EXTRA_STYLE_SUBJECTS):
        jobs.append((f"_style/extra_{j:02d}", f"{subject}, {_STYLE_TAIL}",
                     style_dest, _seed_for("_style", 9) + j))

    print(f"{len(jobs)} jobs queued")
    done = failed = 0
    for unit, prompt, dest, seed in jobs:
        name = unit.replace("/", "_")
        if sorted(dest.glob(f"{name}*.png")):
            done += 1
            continue
        try:
            paths = comfy.generate(
                "image_flux_fallback.json",
                {"PROMPT_POS": prompt, "WIDTH": 832, "HEIGHT": 1216,
                 "SEED": seed, "SAVE_PREFIX": f"pipeline/{args.slug}/extra/{name}"},
                dest=dest,
            )
            paths[0].rename(dest / f"{name}_{paths[0].name}")
            done += 1
            print(f"[{done + failed}/{len(jobs)}] {unit}")
        except ContingencyStop as exc:
            print(f"CONTINGENCY STOP after {done} jobs: {exc}")
            return 2
        except ComfyError as exc:
            failed += 1
            print(f"[fail] {unit}: {exc}")
    comfy.free()
    print(f"done: {done} ok, {failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
