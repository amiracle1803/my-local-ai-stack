"""LTX-Video 0.9.8 distilled renderer (2B checkpoint or 13B GGUF) — ComfyUI native nodes.

Two modes, both driven by the director pass (storyboard/director.json):
  i2v - the shot's panel + the director's motion beat  (LTXVImgToVideo)
  t2v - the director's text-to-video paragraph only     (EmptyLTXVLatentVideo)

LTX wants 8n+1 frames (97 @ 24 fps = 4 s). Model, base size and the optional 2x latent upscale
come from the [render] profile in stack.toml (DynamicVRAM streams what doesn't fit in 8 GB from
system RAM). Uses the same GPU lock + OOM retry as the SVD path.
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
# Distilled LTX runs at cfg 1.0, which ignores the negative prompt: steer with the positive.
ANIME_STYLE = ("hand-painted 2D Japanese anime, cinematic cel shading, clean line art, "
               "consistent character design, faces stay clearly visible with consistent features, "
               "detailed atmospheric background")
DEFAULT_NEGATIVE = ("photorealistic, live action, 3d render, worst quality, inconsistent motion, "
                    "blurry, jittery, distorted, deformed face, extra limbs, occluded subject, hidden face, "
                    "cropped subject, foreground obstruction, text, watermark, static image")


def frames_for(seconds: float, fps: int = 24) -> int:
    """LTX latent rule: 8n+1 frames."""
    n = max(1, round(seconds * fps / 8))
    return 8 * n + 1


# Official LTX-Video 0.9.8 distilled schedules (ltxv-13b-0.9.8-distilled.yaml; same for 2B):
# 8 first-pass steps, then 3 refine steps on the 2x-upscaled latent.
FIRST_PASS_SIGMAS = "1.0, 0.9937, 0.9875, 0.9812, 0.975, 0.9094, 0.725, 0.4219, 0.0"
SECOND_PASS_SIGMAS = "0.9094, 0.725, 0.4219, 0.0"


def _profile():
    from .comfy_client import render_profile
    return render_profile()


def graph(prompt: str, seed: int, *, image: str | None = None, negative: str = DEFAULT_NEGATIVE,
          width: int | None = None, height: int | None = None, frames: int = 97, fps: int = 24,
          strength: float = 1.0, steps: int = 8, prefix: str = "olympus_ltx",
          style: str = ANIME_STYLE, prof=None) -> dict:
    """i2v (image given) or t2v. Model, base size and the optional 2x latent upscale come from
    the [render] profile; `steps` is kept for callers but the distilled schedule is fixed."""
    prof = prof or _profile()
    width, height = width or prof.video_width, height or prof.video_height
    positive = f"{style}. {prompt}" if style else prompt
    if prof.video_unet:          # GGUF transformer (e.g. LTXV 13B) + separate video VAE
        g = {"1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": prof.video_unet}},
             "1v": {"class_type": "VAELoader", "inputs": {"vae_name": prof.video_vae}}}
        model, vae = ["1", 0], ["1v", 0]
    else:
        g = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": prof.video_ckpt or CKPT}}}
        model, vae = ["1", 0], ["1", 2]
    g.update({
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": T5, "type": "ltxv"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
    })
    if image:
        g["5"] = {"class_type": "LoadImage", "inputs": {"image": image}}
        img = ["5", 0]
        if prof.video_img_compression:   # make the still look like a video frame (less frozen start)
            g["5p"] = {"class_type": "LTXVPreprocess", "inputs": {"image": img, "img_compression": prof.video_img_compression}}
            img = ["5p", 0]
        g["6"] = {"class_type": "LTXVImgToVideo", "inputs": {
            "positive": ["3", 0], "negative": ["4", 0], "vae": vae, "image": img,
            "width": width, "height": height, "length": frames, "batch_size": 1, "strength": strength}}
        pos, neg, latent = ["6", 0], ["6", 1], ["6", 2]
    else:
        g["6"] = {"class_type": "EmptyLTXVLatentVideo", "inputs": {
            "width": width, "height": height, "length": frames, "batch_size": 1}}
        pos, neg, latent = ["3", 0], ["4", 0], ["6", 0]
    g["7"] = {"class_type": "LTXVConditioning", "inputs": {"positive": pos, "negative": neg, "frame_rate": float(fps)}}
    g["11"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}}
    g["12"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": FIRST_PASS_SIGMAS}}
    g["13"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}}
    g["14"] = {"class_type": "CFGGuider", "inputs": {"model": model, "positive": ["7", 0],
                                                     "negative": ["7", 1], "cfg": 1.0}}
    g["8"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["13", 0], "guider": ["14", 0], "sampler": ["11", 0], "sigmas": ["12", 0], "latent_image": latent}}
    out = ["8", 0]
    if prof.video_upscale:       # 2x spatial latent upscale + short refine = sharp 2x-res clip
        g["20"] = {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": prof.video_upscale}}
        g["21"] = {"class_type": "LTXVLatentUpsampler", "inputs": {"samples": out, "upscale_model": ["20", 0], "vae": vae}}
        up = ["21", 0]
        if image:                # keep the panel as the exact first frame in the refine pass too
            g["22"] = {"class_type": "LTXVImgToVideoInplace", "inputs": {
                "vae": vae, "image": img, "latent": up, "strength": strength, "bypass": False}}
            up = ["22", 0]
        g["23"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": SECOND_PASS_SIGMAS}}
        g["24"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["13", 0], "guider": ["14", 0], "sampler": ["11", 0], "sigmas": ["23", 0], "latent_image": up}}
        out = ["24", 0]
        g["9"] = {"class_type": "VAEDecodeTiled", "inputs": {"samples": out, "vae": vae, "tile_size": 512,
                                                             "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}}
    else:
        g["9"] = {"class_type": "VAEDecode", "inputs": {"samples": out, "vae": vae}}
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
