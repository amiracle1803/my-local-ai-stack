#!/usr/bin/env python3
"""
build_mystic_eyes_workflow.py
One-command builder for Mystic Eyes LTX2.3 workflows.
Usage:
  python build_mystic_eyes_workflow.py --character "Kyrian (Wilderness Arc)" --output workflow.json
"""

import argparse, json
from pathlib import Path

STORY_ROOT = Path("/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/Ai youtube story/Full ai video production/Mystic Eyes My Eyes Steal the Laws of Cultivation")
PROMPTS_JSON = STORY_ROOT / "mystic_eyes_clip_prompts_final.json"
BASE_WF = Path("/home/amire/Downloads/my-local-ai-stack/ComfyUI/workflows/ltx23_panels_first_last_improved_stages4-7.json")

def build(character_name: str):
    with open(PROMPTS_JSON, encoding="utf-8") as f:
        prompts = json.load(f)
    if character_name not in prompts:
        raise ValueError(f"Character not found. Available: {list(prompts.keys())}")

    with open(BASE_WF) as f:
        wf = json.load(f)

    data = prompts[character_name]
    for node in wf["nodes"]:
        if node.get("type") == "CLIPTextEncode":
            if node.get("id") == 11:
                node["widgets_values"] = [data["positive"]]
            elif node.get("id") == 12:
                node["widgets_values"] = [data["negative"]]
    # Update workflow metadata name
    wf["workflow_name"] = f"mystic_eyes_{character_name}"
    return wf

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--character", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    wf = build(args.character)
    Path(args.output).write_text(json.dumps(wf, indent=2))
    print(f"Built workflow for {args.character} -> {args.output}")