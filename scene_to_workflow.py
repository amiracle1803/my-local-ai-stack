#!/usr/bin/env python3
"""
scene_to_workflow.py
Generate a LTX2.3 panels-first-last workflow from a scene definition.

Scene file example:
{
  "scene_id": "ep01_s01",
  "character": "Kyrian (Early Arc — Royal Order)",
  "first_image": "/path/to/panel_first.png",
  "last_image": "/path/to/panel_last.png",
  "style_notes": "soft lighting, morning"
}
"""

import json, argparse
from pathlib import Path

STORY_ROOT = Path("/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/Ai youtube story/Full ai video production/Mystic Eyes My Eyes Steal the Laws of Cultivation")
PROMPTS_JSON = STORY_ROOT / "mystic_eyes_clip_prompts_final.json"
BASE_WF = Path("/home/amire/Downloads/my-local-ai-stack/ComfyUI/workflows/ltx23_panels_first_last_improved_stages4-7.json")

def load_prompts():
    with open(PROMPTS_JSON, encoding="utf-8") as f:
        return json.load(f)

def build_scene(scene):
    with open(BASE_WF) as f:
        wf = json.load(f)
    prompts = load_prompts()
    char = scene["character"]
    if char not in prompts:
        raise ValueError(f"Character {char} not in prompts")
    data = prompts[char]

    # Update CLIP prompts
    for node in wf["nodes"]:
        if node.get("type") == "CLIPTextEncode":
            if node.get("id") == 11:
                # inject style notes
                base = data["positive"]
                extra = scene.get("style_notes","")
                node["widgets_values"] = [f"{base}, {extra}" if extra else base]
            elif node.get("id") == 12:
                node["widgets_values"] = [data["negative"]]
        # Update first/last image loaders nodes 5 and 6
        if node.get("type") == "LoadImage":
            # nodes 5 = first, 6 = last
            if node.get("id") == 5:
                # widgets_values[0] is file path
                node["widgets_values"] = [scene["first_image"], "image"]
            elif node.get("id") == 6:
                node["widgets_values"] = [scene["last_image"], "image"]

    wf["workflow_name"] = f"scene_{scene['scene_id']}_{char}"
    return wf

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--scene", required=True, help="Path to scene JSON")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    scene = json.loads(Path(args.scene).read_text())
    wf = build_scene(scene)
    Path(args.output).write_text(json.dumps(wf, indent=2))
    print(f"Scene workflow written to {args.output}")