"""LTX-2.3 Director I2V renderer — stage3c "ltx_director" engine.

Drives the proven `workflows/ltx_director_23.json` template over the local
ComfyUI HTTP API.

Per-shot construction follows docs/planning/ltx-director-v2v-2026-08-20.md:
the panel is an image keyframe segment, followed by a text motion beat,
with the 97-frame / 24 fps / 8n+1 latent rule and `last_frame_fix`.

This is optional on the 8GB local target; the default local pipeline uses
panels mode unless a compatible local i2v model set is installed.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import comfy_client

_TEMPLATE = Path(__file__).resolve().parent.parent / "workflows" / "ltx_director_23_extender.json"
_FRAMES = 97          # 97 px-frames @24fps = 4.04s; 8n+1 latent rule
LTX_MODEL = "ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf"
_WIDTH = 576
_HEIGHT = 320
_DEFAULT_GUIDE = "anime scene, cinematic lighting, consistent character and background, subtle natural motion"


def _graph(panel_file: str, motion_prompt: str, seed: int,
           guide_prompt: str, frames: int, width: int, height: int) -> dict:
    """Fill the ltx_director_23 template per docs/planning/ltx-director-v2v."""
    g = json.loads(_TEMPLATE.read_text(encoding="utf-8"))
    g["1"]["inputs"]["unet_name"] = LTX_MODEL
    g["100"]["inputs"]["global_prompt"] = guide_prompt
    g["7"]["inputs"]["noise_seed"] = seed
    segments = [
        {"start": 0, "length": frames, "type": "image", "imageFile": panel_file},
        {"start": 0, "length": frames, "type": "text", "prompt": motion_prompt},
    ]
    d = g["100"]["inputs"]
    d["timeline_data"] = json.dumps({"segments": segments})
    # Extender variant: every entry of the "|"-split locals list must be
    # non-empty (empty slots raise); one text beat per shot here.
    d["local_prompts"] = motion_prompt
    d["segment_lengths"] = str(frames)
    d["guide_strength"] = "1.0"
    d["duration_frames"] = frames
    d["duration_seconds"] = round(frames / 24.0, 3)
    d["custom_width"] = width
    d["custom_height"] = height
    return g


def render_director_clip(panel_path: str | Path, destination: Path, *, seed: int,
                         base_url: str, motion_prompt: str,
                         guide_prompt: str = _DEFAULT_GUIDE,
                         frames: int = _FRAMES, width: int = _WIDTH,
                         height: int = _HEIGHT, timeout: int = 1800) -> Path:
    """Render one directed clip: panel keyframe + motion beat -> h264 mp4."""
    base_url = base_url.rstrip("/")
    panel_file = comfy_client.upload_image(panel_path, base_url)
    prompt_id = comfy_client._request(f"{base_url}/prompt", {
        "prompt": _graph(panel_file, motion_prompt, seed, guide_prompt, frames, width, height),
        "client_id": str(uuid.uuid4()),
    })["prompt_id"]

    deadline = time.monotonic() + timeout
    result = None
    while time.monotonic() < deadline:
        history = comfy_client._request(f"{base_url}/history/{prompt_id}").get(prompt_id)
        if history:
            status = history.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, indent=2)[:4000])
            if history.get("outputs"):
                result = history["outputs"]
                break
        time.sleep(5)
    if not result:
        raise TimeoutError(f"LTX Director prompt {prompt_id} timed out after {timeout}s")

    video = next((item for output in result.values() for item in output.get("gifs", [])), None)
    if not video:
        raise RuntimeError(f"LTX Director prompt {prompt_id} produced no clip")
    query = urllib.parse.urlencode({"filename": video["filename"],
                                    "subfolder": video.get("subfolder", ""),
                                    "type": video.get("type", "output")})
    with urllib.request.urlopen(f"{base_url}/view?{query}", timeout=120) as response:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.read())
    return destination
