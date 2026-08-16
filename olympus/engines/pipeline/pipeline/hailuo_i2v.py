"""Hailuo 2.3 Image-to-Video adapter for anime pipeline.

Supports both hosted API (MiniMax) and self-hosted ComfyUI nodes.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

from .config import PipelineConfig
from .comfy_client import ComfyClient, ComfyError

logger = logging.getLogger(__name__)


@dataclass
class HailuoI2VResult:
    clip_path: Optional[Path] = None
    duration_s: float = 0.0
    success: bool = False
    error: Optional[str] = None
    job_id: Optional[str] = None


class HailuoI2VClient:
    """Client for Hailuo 2.3 I2V generation via API or ComfyUI."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.anim_cfg = config.animation
        self.endpoint = self.anim_cfg.hailuo_api_endpoint
        self.model = self.anim_cfg.hailuo_model  # i2v-pro | i2v-fast | i2v-standard
        self.api_key = self.anim_cfg.hailuo_api_key
        self.comfy = ComfyClient(config)

    def available(self) -> bool:
        """Check if Hailuo backend is available."""
        if self.endpoint:
            return self._check_api()
        # Fallback: check if Hailuo ComfyUI workflow exists
        wf = self.config.comfyui_dir() / "workflows" / "video_i2v_hailuo_minimax.json"
        return wf.exists()

    def _check_api(self) -> bool:
        """Check API health."""
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            r = requests.get(f"{self.endpoint.rstrip('/')}/health", headers=headers, timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    def generate(
        self,
        start_image: Path,
        prompt: str,
        *,
        duration_s: float = 5.0,
        seed: int | None = None,
        negative_prompt: str = "low quality, blurry, distorted, bad anatomy, extra limbs",
        motion_bucket_id: int = 127,  # Hailuo motion intensity
        fps: int = 16,
    ) -> HailuoI2VResult:
        """Generate video from start image and prompt."""
        if self.endpoint and self.api_key:
            return self._generate_api(start_image, prompt, duration_s, seed, negative_prompt, motion_bucket_id, fps)
        else:
            return self._generate_comfyui(start_image, prompt, duration_s, seed, negative_prompt, fps)

    def _generate_api(
        self,
        start_image: Path,
        prompt: str,
        duration_s: float,
        seed: int | None,
        negative_prompt: str,
        motion_bucket_id: int,
        fps: int,
    ) -> HailuoI2VResult:
        """Generate via MiniMax Hailuo API."""
        job_id = str(uuid.uuid4())[:8]
        logger.info("Hailuo API I2V job %s: %s...", job_id, prompt[:60])

        try:
            # Upload start image
            with open(start_image, "rb") as f:
                files = {"image": (start_image.name, f, "image/png")}
                upload = requests.post(
                    f"{self.endpoint.rstrip('/')}/v1/files",
                    files=files,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=60,
                )
                upload.raise_for_status()
                image_id = upload.json()["file_id"]

            # Submit generation job
            payload = {
                "model": self.model,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "image_id": image_id,
                "duration": int(duration_s),
                "fps": fps,
                "motion_bucket_id": motion_bucket_id,
                "seed": seed or int(time.time() * 1000) % 2**32,
            }
            submit = requests.post(
                f"{self.endpoint.rstrip('/')}/v1/generations",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                timeout=60,
            )
            submit.raise_for_status()
            job_data = submit.json()
            generation_id = job_data["generation_id"]

            # Poll for completion
            while True:
                time.sleep(5)
                status = requests.get(
                    f"{self.endpoint.rstrip('/')}/v1/generations/{generation_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=30,
                )
                status.raise_for_status()
                data = status.json()
                if data["status"] == "completed":
                    video_url = data["video_url"]
                    break
                elif data["status"] == "failed":
                    raise RuntimeError(f"Generation failed: {data.get('error')}")

            # Download video
            video_resp = requests.get(video_url, timeout=300)
            video_resp.raise_for_status()

            out_dir = Path(self.config.animation.hailuo_output_dir) if hasattr(self.config.animation, 'hailuo_output_dir') else Path("output/hailuo")
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"hailuo_{job_id}.mp4"
            out_path.write_bytes(video_resp.content)

            return HailuoI2VResult(
                clip_path=out_path,
                duration_s=duration_s,
                success=True,
                job_id=job_id,
            )

        except Exception as exc:
            logger.error("Hailuo API generation failed: %s", exc)
            return HailuoI2VResult(success=False, error=str(exc), job_id=job_id)

    def _generate_comfyui(
        self,
        start_image: Path,
        prompt: str,
        duration_s: float,
        seed: int | None,
        negative_prompt: str,
        fps: int,
    ) -> HailuoI2VResult:
        """Generate via local ComfyUI Hailuo workflow."""
        job_id = str(uuid.uuid4())[:8]
        logger.info("Hailuo ComfyUI I2V job %s", job_id)

        wf_path = self.config.comfyui_dir() / "workflows" / "video_i2v_hailuo_minimax.json"
        if not wf_path.exists():
            return HailuoI2VResult(success=False, error="video_i2v_hailuo_minimax.json workflow not found", job_id=job_id)

        try:
            uploaded = self.comfy.upload_image(start_image, name=f"hailuo_start_{job_id}.png")
            frames = int(duration_s * fps)
            paths = self.comfy.generate(
                "video_i2v_hailuo_minimax.json",
                {
                    "PROMPT_POS": prompt,
                    "PROMPT_NEG": negative_prompt,
                    "START_IMAGE": uploaded,
                    "SEED": seed or int(time.time() * 1000) % 2**32,
                    "FRAMES": frames,
                    "FPS": fps,
                    "SAVE_PREFIX": f"pipeline/hailuo/{job_id}",
                },
                dest=Path(self.config.animation.hailuo_output_dir) if hasattr(self.config.animation, 'hailuo_output_dir') else Path("output/hailuo"),
            )
            if not paths:
                raise ComfyError("No output from ComfyUI")

            return HailuoI2VResult(
                clip_path=Path(paths[0]),
                duration_s=duration_s,
                success=True,
                job_id=job_id,
            )

        except ComfyError as exc:
            logger.error("Hailuo ComfyUI generation failed: %s", exc)
            return HailuoI2VResult(success=False, error=str(exc), job_id=job_id)


def create_hailuo_workflow() -> dict[str, Any]:
    """Create a minimal Hailuo I2V ComfyUI workflow template.

    This is a placeholder - actual workflow depends on the specific
    Hailuo ComfyUI node implementation (e.g., ComfyUI-MiniMax-Hailuo).
    """
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": "START_IMAGE"}
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "PROMPT_POS", "clip": ["3", 1]}
        },
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "t5xxl_fp8_e4m3fn.safetensors"}
        },
        "4": {
            "class_type": "HailuoI2V",  # Custom node from ComfyUI-MiniMax-Hailuo
            "inputs": {
                "model": "hailuo-2.3-i2v-pro",
                "start_image": ["1", 0],
                "positive": ["2", 0],
                "negative": ["5", 0],
                "frames": 81,
                "fps": 16,
                "motion_bucket_id": 127,
                "seed": "SEED"
            }
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "PROMPT_NEG", "clip": ["3", 1]}
        },
        "6": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["4", 0],
                "fps": 16,
                "filename_prefix": "SAVE_PREFIX"
            }
        }
    }
