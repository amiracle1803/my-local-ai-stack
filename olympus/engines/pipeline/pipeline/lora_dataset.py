"""Persistent LoRA training-dataset builder (style + background/scene).

The pipeline's character LoRAs are trained per-project (kohya). The STYLE and
SCENE LoRAs are different: they capture the *house art style* and the *scene
aesthetics* and should be trained ONCE and reused by every project, so a panel
never depends on re-running a training pass.

This module generates the training images through ComfyUI (the same ComfyClient
+ flux/krea2 workflow the refs use), writes kohya-style captions (.txt next to
each .png), and indexes the dataset for ``lora_docker.prepare_character_dataset``.

Datasets live under ``olympus/engines/pipeline/loras/_datasets/``:
  style/   -> 100+ varied manga-style images, caption ends with the style token
  scene/   -> 50+ location/background images (no characters), scene captions
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .config import PipelineConfig
from .comfy_client import ComfyClient, ComfyError, ContingencyStop
from . import image_router

logger = logging.getLogger(__name__)

# Shared style token used as the trigger word in every caption. Both the
# dataset captions and the pipeline's panel prompts use this so the trained
# LoRA activates from the same word.
STYLE_TOKEN = "krea2 manga"

# Persistent dataset roots (never per-project).
_DATASETS = "loras/_datasets"
_STYLE_DIR = "style"
_SCENE_DIR = "scene"

# A varied set of subjects so the style LoRA generalizes (not one character).
_STYLE_SUBJECTS = [
    "a young swordsman with silver hair",
    "a red-haired mage casting a spell",
    "an armored knight on a rooftop",
    "a girl with a fox mask by a lantern",
    "an old fisherman by the harbor",
    "a scarred wanderer in a long coat",
    "a schoolgirl with a katana",
    "a demon lord in dark robes",
    "a shrine maiden in autumn leaves",
    "a street musician at night",
    "a ninja in a rainstorm",
    "a blacksmith at the forge",
    "a prince on a white horse",
    "a witch brewing in a candle-lit hut",
    "a boy with a spirit companion",
    "a warrior queen on a throne",
    "a traveler at a mountain pass",
    "a thief in a moonlit alley",
    "a priest with a staff",
    "a dragon rider above clouds",
    "a girl feeding crows in snow",
    "a samurai under falling petals",
    "a detective in a neon city",
    "a farm boy with a scythe",
    "a fortune teller with cards",
]

# Variety axes so the 100+ images differ (not 25 identical).
_STYLE_ANGLES = ["full body", "upper body", "portrait", "three-quarter shot"]
_STYLE_MOODS = ["golden hour", "moonlit night", "rain", "snow", "misty dawn", "storm clouds"]
_STYLE_COMPOSITIONS = ["dynamic action", "quiet moment", "close-up", "wide establishing"]

# Scene/background subjects (no characters) for the scene LoRA.
_SCENE_SUBJECTS = [
    "an empty mountain village street at dusk",
    "a lantern-lit shrine gate",
    "a misty forest clearing",
    "a stormy seaside cliff",
    "an old castle courtyard",
    "a moonlit bamboo grove",
    "a snowy mountain pass",
    "a neon-lit city alley",
    "a harbor at dawn",
    "an abandoned train station",
    "a cherry blossom road",
    "a candle-lit study",
    "a windswept desert dune",
    "a frozen lake at twilight",
    "a rooftop above a burning city",
    "a quiet tea-house interior",
    "a battlefield at dusk",
    "an overgrown garden ruin",
    "a starry field of grass",
    "a mountain village square",
]

# Shared negative to keep the images clean manga panels.
_NEG = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
    "cropped, worst quality, low quality, jpeg artifacts, signature, watermark, "
    "blurry, out of frame, extra limbs"
)


def _seed_for(unit: str, i: int) -> int:
    import hashlib
    return int(hashlib.sha256(f"{unit}:{i}".encode()).hexdigest()[:12], 16)


def _caption(prompt: str, *, scene: bool) -> str:
    """Build the kohya caption: the prompt + the shared style token."""
    base = prompt.strip().rstrip(",")
    return f"{base}, {STYLE_TOKEN}" if not scene else f"{base}, {STYLE_TOKEN} background"


def _generate(comfy: ComfyClient, template: str, prompt: str, seed: int,
              dest: Path, prefix: str, *, scene: bool) -> Path | None:
    """Render one dataset image via ComfyUI; returns the saved path or None."""
    try:
        paths = comfy.generate(
            template,
            {
                "PROMPT_POS": prompt,
                "PROMPT_NEG": _NEG,
                "WIDTH": 768, "HEIGHT": 1024,
                "SEED": seed,
                "SAVE_PREFIX": f"lora_datasets/{prefix}",
            },
            dest=dest,
        )
    except (ComfyError, ContingencyStop) as exc:
        logger.warning("dataset image %s failed: %s", prefix, exc)
        return None
    return Path(paths[0])


def build_style_dataset(config: PipelineConfig, *, count: int = 120) -> dict[str, Any]:
    """Generate ``count`` varied manga-style images + captions for the style LoRA.

    Varies subject × angle × mood × composition with deterministic seeds so a
    re-run with the same ``count`` reproduces the same set. Returns an index
    dict ``{images: [paths], root: <style_dir>}``.
    """
    comfy = ComfyClient(config)
    if not comfy.healthy():
        raise RuntimeError("ComfyUI is not reachable - start it first.")
    template, _ = image_router.pick_template(config, comfy)

    root = config.loras_dir() / _STYLE_DIR
    root.mkdir(parents=True, exist_ok=True)
    images: list[str] = []

    i = 0
    while len(images) < count:
        s = _STYLE_SUBJECTS[i % len(_STYLE_SUBJECTS)]
        a = _STYLE_ANGLES[(i // len(_STYLE_SUBJECTS)) % len(_STYLE_ANGLES)]
        m = _STYLE_MOODS[(i // (len(_STYLE_SUBJECTS) * len(_STYLE_ANGLES))) % len(_STYLE_MOODS)]
        c = _STYLE_COMPOSITIONS[(i // (len(_STYLE_SUBJECTS) * len(_STYLE_ANGLES) * len(_STYLE_MOODS))) % len(_STYLE_COMPOSITIONS)]
        prompt = f"{s}, {a}, {m}, {c}, manga panel, detailed anime art"
        seed = _seed_for("style", i)
        out = _generate(comfy, template, prompt, seed, root, f"style_{i:04d}", scene=False)
        if out is not None:
            out.rename(root / f"style_{i:04d}.png")
            (root / f"style_{i:04d}.txt").write_text(_caption(prompt, scene=False), encoding="utf-8")
            images.append(str((root / f"style_{i:04d}.png").relative_to(config.loras_dir())))
        i += 1

    index = {"root": str(root.relative_to(config.loras_dir())), "images": images}
    (root / "_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    logger.info("style dataset: %d images in %s", len(images), root)
    return index


def build_scene_dataset(config: PipelineConfig, *, count: int = 60) -> dict[str, Any]:
    """Generate ``count`` background/scene images (no characters) + captions."""
    comfy = ComfyClient(config)
    if not comfy.healthy():
        raise RuntimeError("ComfyUI is not reachable - start it first.")
    template, _ = image_router.pick_template(config, comfy)

    root = config.loras_dir() / _SCENE_DIR
    root.mkdir(parents=True, exist_ok=True)
    images: list[str] = []

    i = 0
    while len(images) < count:
        s = _SCENE_SUBJECTS[i % len(_SCENE_SUBJECTS)]
        mood = _STYLE_MOODS[(i // len(_SCENE_SUBJECTS)) % len(_STYLE_MOODS)]
        prompt = f"{s}, {mood}, no people, empty scene, detailed background art"
        seed = _seed_for("scene", i)
        out = _generate(comfy, template, prompt, seed, root, f"scene_{i:04d}", scene=True)
        if out is not None:
            out.rename(root / f"scene_{i:04d}.png")
            (root / f"scene_{i:04d}.txt").write_text(_caption(prompt, scene=True), encoding="utf-8")
            images.append(str((root / f"scene_{i:04d}.png").relative_to(config.loras_dir())))
        i += 1

    index = {"root": str(root.relative_to(config.loras_dir())), "images": images}
    (root / "_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    logger.info("scene dataset: %d images in %s", len(images), root)
    return index


def build_datasets(config: PipelineConfig, *, style_count: int = 120, scene_count: int = 60) -> dict[str, Any]:
    """Build both persistent datasets. Returns their index dicts keyed by name."""
    return {
        "style": build_style_dataset(config, count=style_count),
        "scene": build_scene_dataset(config, count=scene_count),
    }