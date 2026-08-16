#!/usr/bin/env python3
"""
episode_manifest.py
Build multiple scene workflows from an episode manifest.

Manifest format:
{
  "episode_id": "ep01",
  "scenes": [
    {"scene_id": "...", "character": "...", "first_image": "...", "last_image": "...", "style_notes": "..."},
    ...
  ]
}
"""

import json, argparse
from pathlib import Path
import subprocess

def build_scene(scene, out_path):
    # Use scene_to_workflow script via direct call to avoid subprocess complexity
    # We'll import the build logic
    pass

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    # Actually just call scene_to_workflow via python -c
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text())
    # Import build logic from scene_to_workflow
    # For simplicity, re-implement here
    import json
    from pathlib import Path
    STORY_ROOT = Path("/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/Ai youtube story/Full ai video production/Mystic Eyes My Eyes Steal the Laws of Cultivation")
    PROMPTS_JSON = STORY_ROOT / "mystic_eyes_clip_prompts_final.json"
    BASE_WF = Path("/home/amire/Downloads/my-local-ai-stack/ComfyUI/workflows/ltx23_panels_first_last_improved_stages4-7.json")

    with open(PROMPTS_JSON, encoding="utf-8") as f:
        prompts = json.load(f)
    with open(BASE_WF) as f:
        base_wf = json.load(f)

    for scene in manifest.get("scenes", []):
        wf = json.loads(json.dumps(base_wf))
        char = scene["character"]
        data = prompts.get(char)
        if not data:
            print(f"Warning: character {char} not found, skipping")
            continue
        for node in wf["nodes"]:
            if node.get("type") == "CLIPTextEncode":
                if node.get("id") == 11:
                    extra = scene.get("style_notes","")
                    base = data["positive"]
                    node["widgets_values"] = [f"{base}, {extra}" if extra else base]
                elif node.get("id") == 12:
                    node["widgets_values"] = [data["negative"]]
            if node.get("type") == "LoadImage":
                if node.get("id") == 5:
                    node["widgets_values"] = [scene["first_image"], "image"]
                elif node.get("id") == 6:
                    node["widgets_values"] = [scene["last_image"], "image"]
        wf["workflow_name"] = f"{manifest['episode_id']}_{scene['scene_id']}"
        out_path = outdir / f"{manifest['episode_id']}_{scene['scene_id']}.json"
        out_path.write_text(json.dumps(wf, indent=2))
        print(f"Built {out_path.name}")

    print(f"Episode {manifest.get('episode_id')} built with {len(manifest.get('scenes', []))} scenes")
