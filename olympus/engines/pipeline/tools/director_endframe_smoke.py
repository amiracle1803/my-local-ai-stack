#!/usr/bin/env python3
"""Single-shot stage3c director smoke: render ONE shot with the end-frame
guide (reference First & Last Frame technique) and verify the motion gate.

Usage:  python tools/director_endframe_smoke.py <project> <sid>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.comfy_client import ComfyClient  # noqa: E402
from pipeline.config import PipelineConfig  # noqa: E402
from pipeline import identity  # noqa: E402
from pipeline import stage3c_animation as m  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: director_endframe_smoke.py <project_dir> <sid>")
        return 2
    project_dir = Path(sys.argv[1])
    sid = sys.argv[2]

    config = PipelineConfig.load()
    comfy = ComfyClient(config)
    if not comfy.healthy():
        print("ComfyUI is not reachable")
        return 2
    comfy.unload_ollama()

    storyboard = json.loads((project_dir / "storyboard" / "storyboard.json").read_text(encoding="utf-8"))
    screenplay = json.loads((project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8"))
    shots_by_id = {s["id"]: s for sc in screenplay["scenes"] for s in sc["shots"]}
    shot = shots_by_id.get(sid, {})
    block_id = next(b["id"] for b in storyboard["blocks"] if sid in b["shots"])
    panel = identity.resolve_panel(project_dir / "panels" / block_id, sid, identity.project_code(project_dir))
    if not panel.exists():
        print(f"panel {panel} not found")
        return 2

    project = identity.project_code(project_dir)
    canonical = identity.canonical_shot_id(sid, project)
    res = m._DIRECTOR_RES
    frames = m._DIRECTOR_FRAMES
    fps = m._DIRECTOR_FPS
    steps = m._DIRECTOR_STEPS
    cfg = m._DIRECTOR_CFG
    motion_prompt = m._motion_prompt(shot, 1, "ltx_director_23.json")
    global_prompt = shot.get("style_global", "anime 2d illustration, cel shading, consistent character and background")

    print(f"shot={sid} panel={panel.name}")
    print(f"motion_prompt: {motion_prompt[:120]}")

    clips_dir = project_dir / "clips"
    render_panel = panel
    if getattr(config.animation, "enhance_panels", True):
        render_panel = m._enhance_panel(panel, project_dir, sid)

    uploaded = comfy.upload_image(render_panel, name=f"smoke_{sid}.png")
    t0 = time.monotonic()

    # END frame guide (First & Last Frame technique)
    end_path = m._render_end_frame(comfy, project_dir, panel, motion_prompt, sid,
                                   res=res, seed=m._seed_from_id(sid))
    end_uploaded = comfy.upload_image(end_path, name=f"smoke_{sid}_end.png")

    timeline = m.build_director_timeline(uploaded, motion_prompt, global_prompt, frames, end_frame=end_uploaded)
    patch_set = {
        **timeline,
        "GLOBAL_PROMPT": global_prompt,
        "WIDTH": res[0], "HEIGHT": res[1],
        "FRAMES": frames, "STEPS": steps,
        "CFG": cfg, "SEED": m._seed_from_id(sid), "FPS": fps,
        "SAVE_PREFIX": f"pipeline/{project_dir.name}/clips/{sid}_smoke",
    }
    paths = comfy.generate("ltx_director_23.json", patch_set, dest=clips_dir)
    clip_path = m._canonical_clip_path(paths[0], project_dir, sid, variant="ltx-director")
    elapsed = time.monotonic() - t0

    motion = m.verify_clip_motion(clip_path)
    print(f"wall={elapsed:.1f}s clip={clip_path}")
    print(f"motion_verified={motion['motion_verified']} axis={motion.get('motion_axis')} "
          f"cam={motion.get('cam_speed_px')} scene={motion.get('scene_speed_px')}")
    return 0 if motion["motion_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())