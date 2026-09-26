"""Small native ComfyUI API client for bounded pipeline jobs."""

from __future__ import annotations

import json
import shutil
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .gpu_lock import gpu_batch


def _request(url: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read())


def upload_image(image_path: str | Path, base_url: str) -> str:
    """Upload an image to the server's input dir; returns the server-side
    filename usable as ``imageFile``/LoadImage values. Works for local and
    remote (e.g. Lightning AI) ComfyUI alike."""
    image_path = Path(image_path)
    base_url = base_url.rstrip("/")
    boundary = "olympus" + uuid.uuid4().hex[:12]
    body = b"\r\n".join([
        f"--{boundary}".encode(),
        f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"'.encode(),
        b"Content-Type: image/png",
        b"",
        image_path.read_bytes(),
        f"--{boundary}--".encode(),
        b"",
    ])
    req = urllib.request.Request(
        f"{base_url}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.loads(response.read())
    return result["name"]


def _graph(prompt: str, seed: int, prefix: str) -> dict:
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux-2-klein-4b-Q4_K_M.gguf", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "flux2"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 512, "batch_size": 1}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality, blurry, text, watermark, deformed, extra fingers", "clip": ["2", 0]}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": seed, "steps": 16, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["4", 0], "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }


def _render_panel(prompt: str, destination: Path, seed: int, base_url: str = "http://127.0.0.1:8188", timeout: int = 900) -> Path:
    base_url = base_url.rstrip("/")
    prompt_id = _request(f"{base_url}/prompt", {"prompt": _graph(prompt, seed, "olympus_panel"), "client_id": str(uuid.uuid4())})["prompt_id"]
    deadline = time.monotonic() + timeout
    result = None
    while time.monotonic() < deadline:
        history = _request(f"{base_url}/history/{prompt_id}").get(prompt_id)
        if history:
            if history.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(history))
            if history.get("outputs"):
                result = history["outputs"]
                break
        time.sleep(2)
    if not result:
        raise TimeoutError(f"ComfyUI prompt {prompt_id} timed out")
    image = next((item for output in result.values() for item in output.get("images", [])), None)
    if not image:
        raise RuntimeError(f"ComfyUI prompt {prompt_id} produced no image")
    query = urllib.parse.urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
    with urllib.request.urlopen(f"{base_url}/view?{query}", timeout=30) as response:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.read())
    return destination


def render_panel(prompt: str, destination: Path, seed: int,
                 base_url: str = "http://127.0.0.1:8188", timeout: int = 900) -> Path:
    with gpu_batch("comfyui:panel"):
        return _render_panel(prompt, destination, seed, base_url, timeout)


def _svd_graph(input_image: str, seed: int, frames: int = 14, fps: float = 6.0,
               width: int = 1024, height: int = 576) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "svd_xt.safetensors"}},
        "2": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "sd_vit_h.safetensors"}},
        "3": {"class_type": "LoadImage", "inputs": {"image": input_image}},
        "4": {"class_type": "ImageScale", "inputs": {"upscale_method": "lanczos", "width": width, "height": height, "crop": "center", "image": ["3", 0]}},
        "5": {"class_type": "CLIPVisionEncode", "inputs": {"crop": "center", "clip_vision": ["2", 0], "image": ["4", 0]}},
        "6": {"class_type": "SVD_img2vid_Conditioning", "inputs": {"width": width, "height": height, "video_frames": frames, "motion_bucket_id": 127, "fps": int(fps), "augmentation_level": 0.0, "clip_vision": ["2", 0], "init_image": ["4", 0], "vae": ["1", 2]}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": seed, "steps": 25, "cfg": 2.5, "sampler_name": "euler", "scheduler": "karras", "positive": ["6", 0], "negative": ["6", 1], "latent_image": ["6", 2], "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["1", 2]}},
        "9": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["8", 0], "frame_rate": fps, "loop_count": 0, "filename_prefix": "olympus_clip", "format": "video/h264-mp4", "pingpong": False, "save_output": True}},
    }


def _animate_panel(panel_path: str | Path, destination: Path, seed: int,
                  base_url: str = "http://127.0.0.1:8188", timeout: int = 1200,
                  frames: int = 14, fps: float = 6.0) -> Path:
    """Animate a panel via SVD (Stable Video Diffusion) and fetch the MP4 clip."""
    base_url = base_url.rstrip("/")
    input_name = f"olympus_panel_{seed}.png"
    shutil.copy(Path(panel_path), Path("/home/amire/Downloads/ComfyUI/input") / input_name)
    graph = _svd_graph(input_name, seed, frames=frames, fps=fps)
    prompt_id = _request(f"{base_url}/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})["prompt_id"]
    deadline = time.monotonic() + timeout
    result = None
    while time.monotonic() < deadline:
        history = _request(f"{base_url}/history/{prompt_id}").get(prompt_id)
        if history:
            if history.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(history))
            if history.get("outputs"):
                result = history["outputs"]
                break
        time.sleep(3)
    if not result:
        raise TimeoutError(f"ComfyUI SVD prompt {prompt_id} timed out")
    video = next((item for output in result.values() for item in output.get("gifs", [])), None)
    if not video:
        raise RuntimeError(f"ComfyUI SVD prompt {prompt_id} produced no clip")
    src = Path("/home/amire/Downloads/ComfyUI/output") / video["filename"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(src.read_bytes())
    return destination


def animate_panel(panel_path: str | Path, destination: Path, seed: int,
                  base_url: str = "http://127.0.0.1:8188", timeout: int = 1200,
                  frames: int = 14, fps: float = 6.0) -> Path:
    with gpu_batch("comfyui:animation"):
        return _animate_panel(panel_path, destination, seed, base_url, timeout, frames, fps)
