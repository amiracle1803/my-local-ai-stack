#!/usr/bin/env python3
"""Run (or re-run) only the director pass for a project and print what it wrote.

  python tools/direct_shots.py projects/<slug>            # fill missing shots, print a summary
  python tools/direct_shots.py projects/<slug> --redo     # rewrite every shot
  python tools/direct_shots.py projects/<slug> --show sh-001-02

Writes projects/<slug>/storyboard/director.json, which stage3b (text-to-image prompt + negative)
and stage3c (image-to-video motion/camera/strength, or text-to-video with OLYMPUS_LTX_MODE=t2v)
read. Delete or --redo it to get fresh prompts; re-render panels with OLYMPUS_FORCE_RENDER=1.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE.parents[2]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--show")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    out = project / "storyboard" / "director.json"
    if a.show:
        print(json.dumps(json.loads(out.read_text())[a.show], indent=2, ensure_ascii=False))
        return 0
    if a.redo and out.exists():
        out.rename(out.with_suffix(".prev.json"))
    os.environ["OLYMPUS_DIRECTOR"] = "1"
    from pipeline import stages
    stages.direct_project(project)
    d = json.loads(out.read_text())
    print(f"{len(d)} shots  by: {dict(collections.Counter(v.get('by') for v in d.values()))}")
    for k in sorted(d)[:3]:
        print(f"\n{k}\n  t2i:    {d[k]['t2i'][:200]}\n  motion: {d[k]['motion'][:160]}"
              f"\n  camera: {d[k]['camera']}  strength {d[k]['strength']}  {d[k]['seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
