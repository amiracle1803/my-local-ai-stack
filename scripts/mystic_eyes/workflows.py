#!/usr/bin/env python3
"""
workflows.py — build ComfyUI LTX2.3 "panels-first-last" workflows from character
prompts and/or scene definitions. Consolidates five overlapping root scripts:

  build_mystic_eyes_workflow.py      → build_character (one character)
  generate_character_workflows*.py   → build_characters_batch (all characters)
  scene_to_workflow.py               → build_scene (one scene, images + style)
  episode_manifest.py                → build_episode (many scenes)
"""

import json
import copy
from pathlib import Path
from typing import Dict

from . import config
from .prompts import load_characters, build_prompts


def load_workflow() -> dict:
    """Read the base LTX workflow JSON once."""
    return json.loads(config.BASE_WORKFLOW.read_text(encoding="utf-8"))


def load_prompts(path: Path) -> Dict:
    """Read a CLIP-prompts JSON ({name: {positive, negative}})."""
    return json.loads(path.read_text(encoding="utf-8"))


def _stamp(wf: dict, positive: str, negative: str,
           first_image: str | None = None, last_image: str | None = None) -> dict:
    """Deep-copy `wf` and write the CLIP text + first/last image into its nodes.
    Returns a new workflow so callers never mutate the shared base."""
    out = copy.deepcopy(wf)
    for node in out["nodes"]:
        t = node.get("type")
        if t == "CLIPTextEncode":
            if node.get("id") == config.POS_NODE_ID:
                node["widgets_values"] = [positive]
            elif node.get("id") == config.NEG_NODE_ID:
                node["widgets_values"] = [negative]
        elif t == "LoadImage":
            if node.get("id") == config.FIRST_IMAGE_NODE_ID and first_image:
                node["widgets_values"] = [first_image, "image"]
            elif node.get("id") == config.LAST_IMAGE_NODE_ID and last_image:
                node["widgets_values"] = [last_image, "image"]
    return out


def build_character(character: str, prompts: Dict) -> dict:
    """Build a single-character workflow from an existing prompts map."""
    if character not in prompts:
        raise ValueError(f"Character not found. Available: {list(prompts)}")
    data = prompts[character]
    wf = _stamp(load_workflow(), data["positive"], data["negative"])
    wf["workflow_name"] = f"mystic_eyes_{character}"
    return wf


def build_characters_batch(prompts: Dict, outdir: Path) -> int:
    """Write one workflow file per character in `prompts` and return the count."""
    outdir.mkdir(parents=True, exist_ok=True)
    base = load_workflow()
    count = 0
    for char_name, data in prompts.items():
        wf = _stamp(base, data["positive"], data["negative"])
        out_path = outdir / f"ltx23_mystic_eyes_{config.safe_name(char_name)}.json"
        out_path.write_text(json.dumps(wf, indent=2), encoding="utf-8")
        count += 1
        print(f"Created {out_path.name}")
    print(f"Total workflows: {count}")
    return count


def build_scene(scene: dict, prompts: Dict) -> dict:
    """Build one scene workflow, injecting style notes into the positive prompt
    and pointing the image loaders at the scene's first/last panels."""
    char = scene["character"]
    if char not in prompts:
        raise ValueError(f"Character {char} not in prompts")
    data = prompts[char]
    extra = scene.get("style_notes", "")
    positive = f"{data['positive']}, {extra}" if extra else data["positive"]
    wf = _stamp(load_workflow(), positive, data["negative"],
                scene.get("first_image"), scene.get("last_image"))
    wf["workflow_name"] = f"scene_{scene['scene_id']}_{char}"
    return wf


def build_episode(manifest: dict, outdir: Path, prompts: Dict) -> int:
    """Build one workflow per scene in an episode manifest and return the count."""
    outdir.mkdir(parents=True, exist_ok=True)
    base = load_workflow()
    count = 0
    for scene in manifest.get("scenes", []):
        char = scene["character"]
        data = prompts.get(char)
        if not data:
            print(f"Warning: character {char} not found, skipping")
            continue
        extra = scene.get("style_notes", "")
        positive = f"{data['positive']}, {extra}" if extra else data["positive"]
        wf = _stamp(base, positive, data["negative"],
                    scene.get("first_image"), scene.get("last_image"))
        wf["workflow_name"] = f"{manifest['episode_id']}_{scene['scene_id']}"
        name = f"{manifest['episode_id']}_{scene['scene_id']}.json"
        (outdir / name).write_text(json.dumps(wf, indent=2), encoding="utf-8")
        count += 1
        print(f"Built {name}")
    print(f"Episode {manifest.get('episode_id')} built with {count} scenes")
    return count


def _resolve_prompts(prompts_input: str | None, characters_input: str | None) -> Dict:
    """Load CLIP prompts either directly (--prompts) or by building them from a
    characters JSON on the fly (--characters)."""
    if prompts_input:
        return load_prompts(Path(prompts_input))
    if characters_input:
        return build_prompts(load_characters(Path(characters_input)))
    raise ValueError("provide either --prompts (CLIP prompts JSON) or --characters (characters JSON)")


def main(command: str, prompts_input: str | None, characters_input: str | None,
         character: str | None, output: str, scene: str | None,
         manifest: str | None, outdir: str) -> int:
    """CLI dispatcher for the workflow-building commands."""
    prompts = _resolve_prompts(prompts_input, characters_input)

    if command == "workflows":
        out = Path(output) if output else config.WORKFLOW_OUT_DIR
        build_characters_batch(prompts, out)
    elif command == "character":
        wf = build_character(character, prompts)
        Path(output).write_text(json.dumps(wf, indent=2), encoding="utf-8")
        print(f"Built workflow for {character} -> {output}")
    elif command == "scene":
        scene_data = json.loads(Path(scene).read_text(encoding="utf-8"))
        wf = build_scene(scene_data, prompts)
        Path(output).write_text(json.dumps(wf, indent=2), encoding="utf-8")
        print(f"Scene workflow written to {output}")
    elif command == "episode":
        manifest_data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        build_episode(manifest_data, Path(outdir), prompts)
    else:
        raise ValueError(f"unknown command {command!r}")
    return 0
