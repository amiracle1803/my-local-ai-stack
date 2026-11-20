"""LTX-2.3 Director I2V/T2V renderer — stage3c "ltx_director" engine.

Drives the `workflows/ltx_director_23_extender.json` template over the local
ComfyUI HTTP API. I2V uses a panel keyframe plus a text motion beat; T2V omits
the image segment and uses the director's chronological text paragraph.

This requires the separate LTX Director nodes and 22B model set. The installed
8 GB local default is `ltx2b`; Director is an experimental higher-VRAM path.
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


def _graph(panel_file: str | None, motion_prompt: str, seed: int,
           guide_prompt: str, frames: int, width: int, height: int) -> dict:
    """Fill the Director template with an optional image keyframe."""
    g = json.loads(_TEMPLATE.read_text(encoding="utf-8"))
    g["1"]["inputs"]["unet_name"] = LTX_MODEL
    g["100"]["inputs"]["global_prompt"] = guide_prompt
    g["7"]["inputs"]["noise_seed"] = seed
    segments = []
    if panel_file:
        segments.append({"start": 0, "length": frames, "type": "image", "imageFile": panel_file})
    segments.append({"start": 0, "length": frames, "type": "text", "prompt": motion_prompt})
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


def render_director_clip(panel_path: str | Path | None, destination: Path, *, seed: int,
                         base_url: str, motion_prompt: str,
                         guide_prompt: str = _DEFAULT_GUIDE,
                         frames: int = _FRAMES, width: int = _WIDTH,
                         height: int = _HEIGHT, timeout: int = 1800) -> Path:
    """Render one directed clip from text, optionally anchored by a panel."""
    base_url = base_url.rstrip("/")
    panel_file = comfy_client.upload_image(panel_path, base_url) if panel_path else None
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
