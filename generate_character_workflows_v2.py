#!/usr/bin/env python3
"""
generate_character_workflows_v2.py
Use final characters JSON and prompts to create per-character ComfyUI workflows.
"""

import json
from pathlib import Path

STORY_ROOT = Path("/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/Ai youtube story/Full ai video production/Mystic Eyes My Eyes Steal the Laws of Cultivation")
PROMPTS_JSON = STORY_ROOT / "mystic_eyes_clip_prompts_final.json"

BASE_WF = Path("/home/amire/Downloads/my-local-ai-stack/ComfyUI/workflows/ltx23_panels_first_last_improved_stages4-7.json")
OUT_DIR = Path("/home/amire/Downloads/my-local-ai-stack/ComfyUI/workflows/mystic_eyes_per_character_v2")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def safe_name(name):
    return "".join(c if c.isalnum() else "_" for c in name)

with open(PROMPTS_JSON, encoding="utf-8") as f:
    prompts = json.load(f)

with open(BASE_WF) as f:
    base = json.load(f)

count = 0
for char_name, data in prompts.items():
    wf = json.loads(json.dumps(base))
    for node in wf["nodes"]:
        if node.get("type") == "CLIPTextEncode":
            if node.get("id") == 11:
                node["widgets_values"] = [data["positive"]]
            elif node.get("id") == 12:
                node["widgets_values"] = [data["negative"]]
    safe = safe_name(char_name)
    out_path = OUT_DIR / f"ltx23_mystic_eyes_{safe}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(wf, f, indent=2)
    count += 1
    print(f"Created {out_path.name}")

print(f"Total workflows: {count}")