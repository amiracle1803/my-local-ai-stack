#!/usr/bin/env python3
"""
generate_character_workflows.py
Create per-character ComfyUI workflows from mystic_eyes_clip_prompts.json
using the stages4-7 improved base workflow.
"""

import json
from pathlib import Path
import shutil

STORY_ROOT = Path("/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/Ai youtube story/Full ai video production/Mystic Eyes My Eyes Steal the Laws of Cultivation")
PROMPTS_JSON = STORY_ROOT / "mystic_eyes_clip_prompts.json"

BASE_WF = Path("/home/amire/Downloads/my-local-ai-stack/ComfyUI/workflows/ltx23_panels_first_last_improved_stages4-7.json")
OUT_DIR = Path("/home/amire/Downloads/my-local-ai-stack/ComfyUI/workflows/mystic_eyes_per_character")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_base():
    with open(BASE_WF) as f:
        return json.load(f)

def safe_name(name):
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
    # then replace spaces with _

def generate():
    with open(PROMPTS_JSON, encoding="utf-8") as f:
        prompts = json.load(f)

    base = load_base()
    count = 0
    for char_name, data in prompts.items():
        wf = json.loads(json.dumps(base))  # deep copy
        # Update CLIPTextEncode nodes 11 positive, 12 negative
        for node in wf["nodes"]:
            if node["type"] == "CLIPTextEncode":
                # node inputs: text, clip
                # widgets_values[0] is text
                if node.get("id") == 11:  # positive
                    node["widgets_values"] = [data["positive"]]
                elif node.get("id") == 12:  # negative
                    node["widgets_values"] = [data["negative"]]
        # Update workflow name
        safe = safe_name(char_name).replace(" ", "_")
        out_path = OUT_DIR / f"ltx23_mystic_eyes_{safe}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(wf, f, indent=2)
        count += 1
        print(f"Created {out_path.name}")
    print(f"Total workflows: {count}")

if __name__ == "__main__":
    generate()