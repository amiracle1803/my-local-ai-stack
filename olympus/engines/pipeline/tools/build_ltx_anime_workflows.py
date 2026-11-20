#!/usr/bin/env python3
"""Build flexible anime LTX 2B ComfyUI presets from the installed official templates."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.ltx2b import ANIME_STYLE, CKPT, COMFY, DEFAULT_NEGATIVE, T5  # noqa: E402

TEMPLATES = COMFY / ".venv/lib/python3.12/site-packages/comfyui_workflow_templates_json/templates"
OUTPUT = ENGINE_ROOT / "workflows" / "ui"
PANEL_NAME = "olympus_anime_start_panel.png"
DEFAULT_PROMPT = (
    "Aya, a 16-year-old girl with short black hair, a red scarf and brown wool coat, "
    "is fully visible and unobstructed on the left side of a floating lantern tower's "
    "spiral stairwell at deep indigo dusk. She climbs two steps as her scarf billows "
    "in the wind and warm amber lantern light flickers. The sea of clouds drifts below. "
    "A slow stable push-in preserves her appearance and the background throughout the shot."
)
GUIDE = """## Olympus anime LTX 2B — local 8 GB preset

Edit the **shot prompt**, then adjust the labelled control nodes. All models are local;
no cloud generation or Director nodes are required.

- **Prompt order:** subject and visible action first, environment second, camera last.
  Keep the subject unobstructed in the opening frame. Describe motion, not only mood.
  Retain exact hair, clothing, and colors in every rewrite; adding composition constraints
  must not replace character identity details.
- **Duration:** frames must follow `8n + 1` (49 = 2.04 s, 97 = 4.04 s at 24 fps).
- **Seed:** use `fixed` to compare prompt changes; use `randomize` for variations.
- **Sampler:** distilled model defaults are CFG 1.0 and Euler. Start with 8 steps;
  the fast preview uses 4 steps, 49 frames, and 512×320.
- **Models:** LTX 2B 0.9.8 distilled FP8 + T5 XXL FP8, already installed.

The 22B LTX Director workflow is separate and experimental on this machine.
"""


def _node(workflow: dict, node_id: int) -> dict:
    return next(node for node in workflow["nodes"] if node["id"] == node_id)


def _widgets(workflow: dict, node_id: int, values: list) -> None:
    _node(workflow, node_id)["widgets_values"] = values


def _title(workflow: dict, node_id: int, title: str) -> None:
    _node(workflow, node_id)["title"] = title


def _validate(workflow: dict) -> None:
    node_ids = {node["id"] for node in workflow["nodes"]}
    links = {link[0]: link for link in workflow["links"]}
    assert len(node_ids) == len(workflow["nodes"])
    assert len(links) == len(workflow["links"])
    for link_id, source, _source_slot, target, _target_slot, _kind in workflow["links"]:
        assert source in node_ids and target in node_ids, f"broken link {link_id}"
    for node in workflow["nodes"]:
        for port in node.get("inputs", []):
            if port.get("link") is not None:
                assert port["link"] in links, f"broken input on node {node['id']}"
        for port in node.get("outputs", []):
            for link_id in port.get("links") or []:
                assert link_id in links, f"broken output on node {node['id']}"


def build(template_name: str, slug: str, title: str, *, width: int, height: int,
          frames: int, steps: int, image_to_video: bool = False) -> dict:
    workflow = json.loads((TEMPLATES / template_name).read_text(encoding="utf-8"))
    workflow["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"olympus/ltx2b/{slug}"))
    workflow["revision"] = 0
    workflow["extra"] = {"ds": {"scale": 0.8, "offset": [240, 160]}, "frontendVersion": "1.27.10"}

    _widgets(workflow, 44, [CKPT])
    _widgets(workflow, 38, [T5, "ltxv", "default"])
    _node(workflow, 44)["properties"]["models"] = [{"name": CKPT, "directory": "checkpoints"}]
    _node(workflow, 38)["properties"]["models"] = [{"name": T5, "directory": "text_encoders"}]
    _widgets(workflow, 6, [f"{ANIME_STYLE}. {DEFAULT_PROMPT}"])
    _widgets(workflow, 7, [DEFAULT_NEGATIVE])
    _widgets(workflow, 69, [24])
    _widgets(workflow, 71, [steps, 2.05, 0.95, True, 0.1])
    _widgets(workflow, 72, [True, 42, "fixed", 1.0])
    _widgets(workflow, 73, ["euler"])
    save_id = 81 if image_to_video else 79
    create_id = 80 if image_to_video else 78
    _widgets(workflow, create_id, [24])
    _widgets(workflow, save_id, [f"video/olympus/{slug}", "mp4", "h264"])

    _title(workflow, 44, "MODEL · LTX 2B distilled FP8")
    _title(workflow, 38, "TEXT ENCODER · T5 XXL FP8")
    _title(workflow, 6, "PROMPT · subject + action + setting + camera")
    _title(workflow, 7, "NEGATIVE · anime / motion cleanup")
    _title(workflow, 69, "CONTROL · frames per second")
    _title(workflow, 71, "CONTROL · sampling steps")
    _title(workflow, 72, "CONTROL · fixed seed / CFG")
    _title(workflow, 73, "SAMPLER · Euler")
    _title(workflow, create_id, "OUTPUT · video fps")
    _title(workflow, save_id, "SAVE · H.264 MP4")

    note_id = 79 if image_to_video else 77
    note = _node(workflow, note_id)
    note["title"] = title
    note["widgets_values"] = [GUIDE + (
        "\n## Image-to-video\n\nThe bundled Lanternfall panel is installed as "
        f"`{PANEL_NAME}`. Choose another image in **INPUT · start panel**. "
        "Strength 1.0 anchors the first frame to that panel; the prompt directs its motion.\n"
        if image_to_video else
        "\n## Text-to-video\n\nNo input image is needed. Use this for establishing shots "
        "and new action; use the I2V preset when exact first-frame identity matters.\n"
    )]
    note["pos"] = [-500, 0]
    note["size"] = [410, 540 if image_to_video else 500]

    tip = _node(workflow, 76)
    tip["title"] = "PROMPTING · action before camera"
    tip["widgets_values"] = [
        "Show the main subject clearly from frame one. Lead with a concrete action "
        "(‘Aya climbs two steps’), then describe the setting and a restrained camera move. "
        "Long prompts help; avoid foreground objects that hide the subject."
    ]
    tip["size"] = [425, 120]

    if image_to_video:
        _widgets(workflow, 77, [width, height, frames, 1, 1.0])
        _widgets(workflow, 78, [PANEL_NAME, "image"])
        _title(workflow, 77, "CONTROL · size / 8n+1 frames / panel strength")
        _title(workflow, 78, "INPUT · start panel")
    else:
        _widgets(workflow, 70, [width, height, frames, 1])
        _title(workflow, 70, "CONTROL · width / height / 8n+1 frames")

    group_titles = (
        ["1 · LOCAL MODELS", "3 · ANIME DIRECTION", "2 · SHOT CONTROLS", "4 · SAMPLER + OUTPUT"]
        if not image_to_video else
        ["1 · LOCAL MODELS", "3 · ANIME DIRECTION", "4 · SHOT CONTROLS", "5 · SAMPLER + OUTPUT",
         "2 · START PANEL"]
    )
    for group, group_title in zip(workflow.get("groups", []), group_titles, strict=True):
        group["title"] = group_title
        group["color"] = "#7c5cbf" if image_to_video else "#3f789e"
    _validate(workflow)
    return workflow


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="copy presets into ComfyUI user workflows")
    parser.add_argument("--panel", type=Path, help="start panel to install for the I2V example")
    args = parser.parse_args()

    specs = [
        ("ltxv_text_to_video.json", "ltx2b_anime_t2v", "Olympus anime · text to video", 768, 512, 97, 8, False),
        ("ltxv_image_to_video.json", "ltx2b_anime_i2v", "Olympus anime · image to video", 768, 512, 97, 8, True),
        ("ltxv_text_to_video.json", "ltx2b_anime_preview", "Olympus anime · fast preview", 512, 320, 49, 4, False),
    ]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    install_dir = COMFY / "user/default/workflows/olympus"
    if args.install:
        install_dir.mkdir(parents=True, exist_ok=True)
    for template, slug, title, width, height, frames, steps, i2v in specs:
        workflow = build(template, slug, title, width=width, height=height, frames=frames,
                         steps=steps, image_to_video=i2v)
        destination = OUTPUT / f"{slug}.json"
        destination.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.install:
            shutil.copy2(destination, install_dir / destination.name)
        print(f"{destination}: {len(workflow['nodes'])} nodes, {len(workflow['links'])} links")
    if args.install and args.panel:
        shutil.copy2(args.panel, COMFY / "input" / PANEL_NAME)
        print(f"installed start panel: {COMFY / 'input' / PANEL_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
