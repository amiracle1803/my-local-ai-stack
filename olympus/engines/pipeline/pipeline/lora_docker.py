"""Docker-based LoRA training wrapper for kohya-ss.

Replaces the stub train_lora() in model_lab.py with a real implementation
that runs kohya-ss inside a GPU-enabled Docker container.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .config import ENGINE_ROOT, PipelineConfig

logger = logging.getLogger(__name__)

_DOCKER_IMAGE = "kohya-ss:local"
_DOCKERFILE = ENGINE_ROOT / "Dockerfile.kohya"


@dataclass
class LoRATrainingResult:
    """Result of a LoRA training run."""
    dataset_path: str
    character_id: str
    rank: int
    steps: int
    passed: bool = False
    lora_path: Optional[str] = None
    error: Optional[str] = None


def _ensure_podman_image() -> bool:
    """Build the kohya-ss Docker image if not present."""
    try:
        result = subprocess.run(
            ["podman", "images", "-q", _DOCKER_IMAGE],
            capture_output=True, text=True, timeout=30,
        )
        if result.stdout.strip():
            return True
        logger.info("Building kohya-ss Docker image...")
        build = subprocess.run(
            ["podman", "build", "-f", str(_DOCKERFILE), "-t", _DOCKER_IMAGE, str(ENGINE_ROOT)],
            capture_output=True, text=True, timeout=1800,
        )
        if build.returncode != 0:
            logger.error("Docker build failed: %s", build.stderr)
            return False
        logger.info("Docker image built successfully")
        return True
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.error("Docker not available or build failed: %s", exc)
        return False


def train_lora_podman(
    dataset_path: str | Path,
    *,
    character_id: str | None = None,
    rank: int = 8,
    steps: int = 800,
    output_path: str | Path | None = None,
    config: PipelineConfig | None = None,
) -> LoRATrainingResult:
    """Train a LoRA using kohya-ss inside Docker.

    Args:
        dataset_path: Path to training images (with caption .txt files)
        character_id: Character identifier for naming
        rank: LoRA rank (dimension)
        steps: Training steps
        output_path: Where to save the LoRA (default: config.loras_dir()/character_id/)
        config: PipelineConfig for paths

    Returns:
        LoRATrainingResult with success status and output path
    """
    result = LoRATrainingResult(
        dataset_path=str(dataset_path),
        character_id=character_id or "unknown",
        rank=rank,
        steps=steps,
    )

    if not _ensure_podman_image():
        logger.error("Failed to ensure kohya-ss Docker image")
        result.passed = False
        result.error = "Docker image unavailable"
        return result

    dataset = Path(dataset_path)
    if not dataset.exists():
        logger.error("Dataset path does not exist: %s", dataset)
        result.passed = False
        result.error = "Dataset not found"
        return result

    if config is None:
        from .config import load_config
        config = load_config()

    if output_path is None:
        output_path = config.loras_dir() / (character_id or "lora")
    output = Path(output_path)
    output.mkdir(parents=True, exist_ok=True)

    char_id = character_id or dataset.name

    # Build podman run command with GPU device passthrough
    # Mount krea2 model file for flux training (safetensors format)
    krea2_model = config.comfyui_dir() / "models" / "diffusion_models" / "krea2_turbo_fp8_scaled.safetensors"
    # Mount tokenizer cache
    tokenizer_cache = Path("/home/amire/Downloads/my-local-ai-stack/hf_cache")
    cmd = [
        "podman", "run", "--rm",
        "--device", "/dev/nvidia0",
        "--device", "/dev/nvidiactl",
        "--device", "/dev/nvidia-modeset",
        "--device", "/dev/nvidia-uvm",
        "--device", "/dev/nvidia-uvm-tools",
        "--device", "/dev/dri/renderD128",
        "-v", f"{dataset.resolve()}:/data:ro",
        "-v", f"{output.resolve()}:/output",
        "-v", f"{config.comfyui_dir().resolve()}:/models",
        "-v", f"{krea2_model}:/models/krea2_turbo_fp8_scaled.safetensors",
        "-v", f"{tokenizer_cache}:/root/.cache/huggingface",
        _DOCKER_IMAGE,
        "--dataset", "/data",
        "--output", "/output",
        "--character", char_id,
        "--rank", str(rank),
        "--steps", str(steps),
    ]

    logger.info("Starting kohya-ss LoRA training for %s (rank=%d, steps=%d)", char_id, rank, steps)
    logger.debug("Docker command: %s", " ".join(cmd))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        if proc.returncode != 0:
            logger.error("Training failed: %s", proc.stderr)
            result.passed = False
            result.error = proc.stderr[-2000:]
            return result

        # Find output LoRA
        lora_files = list(output.glob(f"{char_id}_lora*.safetensors"))
        if not lora_files:
            logger.error("No LoRA output found in %s", output)
            result.passed = False
            result.error = "No LoRA file produced"
            return result

        lora_path = lora_files[0]
        result.lora_path = str(lora_path)
        result.passed = True
        logger.info("LoRA training succeeded: %s", lora_path)
        return result

    except subprocess.TimeoutExpired:
        logger.error("Training timed out after 2 hours")
        result.passed = False
        result.error = "Timeout"
        return result
    except Exception as exc:
        logger.exception("Training error: %s", exc)
        result.passed = False
        result.error = str(exc)
        return result


def prepare_character_dataset(
    character_refs_dir: Path,
    output_dir: Path,
    character_name: str,
) -> Path:
    """Prepare a kohya-compatible dataset from character reference images.

    Creates the directory structure with images and caption .txt files
    that kohya-ss expects.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect reference images
    ref_images = sorted(character_refs_dir.glob("*.png"))
    if not ref_images:
        logger.warning("No reference images found in %s", character_refs_dir)
        return output_dir

    # Create caption template
    caption = f"anime character {character_name}, detailed face, consistent features"

    for i, img in enumerate(ref_images):
        # Copy image
        dest_img = output_dir / f"{character_name}_{i:04d}.png"
        dest_img.write_bytes(img.read_bytes())

        # Create caption file
        dest_caption = output_dir / f"{character_name}_{i:04d}.txt"
        dest_caption.write_text(caption, encoding="utf-8")

    logger.info("Prepared dataset for %s: %d images in %s", character_name, len(ref_images), output_dir)
    return output_dir
