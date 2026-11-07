"""LTX-Video 2B (0.9.8 distilled, fp8) renderer for the 8 GB Legion GPU — ComfyUI native nodes.

Two modes, both driven by the director pass (storyboard/director.json):
  i2v - the shot's panel + the director's motion beat  (LTXVImgToVideo)
  t2v - the director's text-to-video paragraph only     (EmptyLTXVLatentVideo)

97 frames @ 24 fps = 4 s (LTX wants 8n+1 frames), 768x512, 8 steps at cfg 1.0 for the distilled
model. Uses the same GPU lock + OOM retry as the SVD path.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from .comfy_client import MIN_CLIP_BYTES, _already_done, _request, _with_oom_retry
from .gpu_lock import gpu_batch

CKPT = "ltxv-2b-0.9.8-distilled-fp8.safetensors"
T5 = "t5xxl_fp8_e4m3fn.safetensors"
COMFY = Path("/home/amire/Downloads/ComfyUI")
DEFAULT_NEGATIVE = ("worst quality, inconsistent motion, blurry, jittery, distorted, deformed face, "
                    "extra limbs, text, watermark, static image")


def frames_for(seconds: float, fps: int = 24) -> int:
    """LTX latent rule: 8n+1 frames."""
    n = max(1, round(seconds * fps / 8))
    return 8 * n + 1


def graph(prompt: str, seed: int, *, image: str | None = None, negative: str = DEFAULT_NEGATIVE,
          width: int = 768, height: int = 512, frames: int = 97, fps: int = 24,
          strength: float = 1.0, steps: int = 8, prefix: str = "olympus_ltx") -> dict:
    g = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": T5, "type": "ltxv"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
    }
    if image:
        g["5"] = {"class_type": "LoadImage", "inputs": {"image": image}}
        g["6"] = {"class_type": "LTXVImgToVideo", "inputs": {
            "positive": ["3", 0], "negative": ["4", 0], "vae": ["1", 2], "image": ["5", 0],
            "width": width, "height": height, "length": frames, "batch_size": 1, "strength": strength}}
        pos, neg, latent = ["6", 0], ["6", 1], ["6", 2]
    else:
        g["6"] = {"class_type": "EmptyLTXVLatentVideo", "inputs": {
            "width": width, "height": height, "length": frames, "batch_size": 1}}
        pos, neg, latent = ["3", 0], ["4", 0], ["6", 0]
    g["7"] = {"class_type": "LTXVConditioning", "inputs": {"positive": pos, "negative": neg, "frame_rate": float(fps)}}
    g["8"] = {"class_type": "KSampler", "inputs": {
        "model": ["1", 0], "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler",
        "scheduler": "simple", "positive": ["7", 0], "negative": ["7", 1], "latent_image": latent, "denoise": 1.0}}
    g["9"] = {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["1", 2]}}
    g["10"] = {"class_type": "VHS_VideoCombine", "inputs": {
        "images": ["9", 0], "frame_rate": fps, "loop_count": 0, "filename_prefix": prefix,
        "format": "video/h264-mp4", "pingpong": False, "save_output": True}}
    return g


def _render(prompt: str, destination: Path, seed: int, base_url: str, timeout: int,
            panel: Path | None, **kw) -> Path:
    base_url = base_url.rstrip("/")
    image = None
    if panel is not None:
        image = f"olympus_ltx_{seed}.png"
        shutil.copy(Path(panel), COMFY / "input" / image)
    g = graph(prompt, seed, image=image, **kw)
    pid = _request(f"{base_url}/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})["prompt_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        h = _request(f"{base_url}/history/{pid}").get(pid)
        if h:
            if h.get("status", {}).get("status_str") == "error":
                raise RuntimeError(str(h.get("status"))[:800])
            out = h.get("outputs") or {}
            video = next((it for o in out.values() for it in o.get("gifs", [])), None)
            if video:
                src = COMFY / "output" / video.get("subfolder", "") / video["filename"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(src.read_bytes())
                return destination
            if out:
                raise RuntimeError(f"LTX prompt {pid} produced no clip")
        time.sleep(3)
    raise TimeoutError(f"LTX prompt {pid} timed out")


def render_clip(prompt: str, destination: Path, seed: int, *, panel: Path | None = None,
                base_url: str = "http://127.0.0.1:8188", timeout: int = 1800, **kw) -> Path:
    """i2v when a panel is given, else t2v. Resumable: an existing clip is kept."""
    if _already_done(destination, MIN_CLIP_BYTES):
        return destination
    with gpu_batch("comfyui:ltx2b"):
        return _with_oom_retry(lambda: _render(prompt, destination, seed, base_url, timeout, panel, **kw), base_url)
