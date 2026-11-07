"""Cloud text-to-image backends, tried before the local ComfyUI render.

Order (OLYMPUS_CLOUD_IMAGES, comma list; "0"/"" disables cloud entirely):
  nvidia       - NVIDIA Build FLUX.1 (schnell by default), key .agent-secrets/nvidia_invoke_key|nvidia_key
                 or NVIDIA_API_KEY. Sizes are snapped to the sizes FLUX accepts (768-1344, step 64).
  gemini       - Gemini image model, key GEMINI_API_KEY (env or ~/.hermes/.env). 429 = quota, skipped.
  pollinations - image.pollinations.ai, no key needed (POLLINATIONS_TOKEN used if present).

Every provider gets a short timeout and a circuit breaker: after BREAK_AFTER consecutive
failures (or one timeout / quota / auth error) it is skipped for the rest of the process, so a
dead API costs seconds, not the run.

Probed 2026-11-06 from the Legion: pollinations OK (~4 s, but anonymous tier = photoreal-leaning,
own size, watermark strip -> cropped); NVIDIA FLUX schnell/dev time out; no Gemini key here.
So run_images uses cloud as the FALLBACK when local ComfyUI fails (OLYMPUS_IMAGE_SOURCE=cloud
puts cloud first).
Returns the provider name that made the image, or "" (caller falls back to local ComfyUI).
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STACK = Path(__file__).resolve().parents[4]
BREAK_AFTER = 2
TIMEOUT = int(os.environ.get("OLYMPUS_CLOUD_TIMEOUT", "45"))
NVIDIA_MODEL = os.environ.get("OLYMPUS_NVIDIA_FLUX", "flux.1-schnell")
GEMINI_MODEL = os.environ.get("OLYMPUS_GEMINI_IMAGE", "gemini-2.5-flash-image")
_failures: dict[str, int] = {}
UA = "olympus-pipeline/1.0"


def _key(*names: str, files: tuple[str, ...] = ()) -> str:
    for n in names:
        if os.environ.get(n):
            return os.environ[n].strip()
    for f in files:
        p = STACK / ".agent-secrets" / f
        if p.exists() and p.read_text().strip():
            return p.read_text().strip()
    env = Path.home() / ".hermes" / ".env"
    if env.exists():
        for line in env.read_text(errors="replace").splitlines():
            for n in names:
                if line.startswith(f"{n}=") and line.split("=", 1)[1].strip():
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def snap(v: int, lo: int = 768, hi: int = 1344, step: int = 64) -> int:
    return max(lo, min(hi, int(round(v / step)) * step))


def flux_size(width: int, height: int) -> tuple[int, int]:
    """Keep the aspect ratio inside FLUX's allowed 768..1344 box (16:9 -> 1344x768)."""
    ar = width / max(1, height)
    if ar >= 1:
        w = 1344
        return w, snap(w / ar)
    h = 1344
    return snap(h * ar), h


def _post(url: str, body: dict, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": UA, **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def nvidia(prompt: str, negative: str, width: int, height: int, seed: int) -> bytes:
    key = _key("NVIDIA_API_KEY", files=("nvidia_invoke_key", "nvidia_key"))
    if not key:
        raise RuntimeError("no NVIDIA key")
    w, h = flux_size(width, height)
    body = {"prompt": prompt[:1500], "width": w, "height": h, "seed": seed % 4294967295,
            "steps": 4 if "schnell" in NVIDIA_MODEL else 30}
    d = _post(f"https://ai.api.nvidia.com/v1/genai/black-forest-labs/{NVIDIA_MODEL}", body,
              {"Authorization": f"Bearer {key}", "Accept": "application/json"}, TIMEOUT)
    art = (d.get("artifacts") or [{}])[0]
    if art.get("finishReason") not in (None, "SUCCESS"):
        raise RuntimeError(f"nvidia finishReason {art.get('finishReason')}")
    return base64.b64decode(art["base64"])


def gemini(prompt: str, negative: str, width: int, height: int, seed: int) -> bytes:
    key = _key("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("no Gemini key")
    text = f"{prompt}\nAvoid: {negative}\nWide 16:9 single frame." if negative else prompt
    d = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
              {"contents": [{"parts": [{"text": text}]}],
               "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9"}}},
              {"x-goog-api-key": key}, TIMEOUT)
    for part in ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts", []):
        data = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
        if data:
            return base64.b64decode(data)
    raise RuntimeError("gemini returned no image")


def pollinations(prompt: str, negative: str, width: int, height: int, seed: int) -> bytes:
    q = {"width": width, "height": height, "seed": seed % 2147483647, "model": "flux",
         "nologo": "true", "private": "true", "safe": "true"}
    if negative:
        q["negative_prompt"] = negative[:300]
    headers = {"User-Agent": UA}
    tok = _key("POLLINATIONS_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1500], safe="")
           + "?" + urllib.parse.urlencode(q))
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as r:
        if not (r.headers.get("Content-Type") or "").startswith("image/"):
            raise RuntimeError(f"pollinations returned {r.headers.get('Content-Type')}")
        return r.read()


PROVIDERS = {"nvidia": nvidia, "gemini": gemini, "pollinations": pollinations}


def order() -> list[str]:
    raw = os.environ.get("OLYMPUS_CLOUD_IMAGES", "nvidia,gemini,pollinations")
    if raw.strip() in ("", "0", "off", "none"):
        return []
    return [p.strip() for p in raw.split(",") if p.strip() in PROVIDERS]


def _is_image(b: bytes) -> bool:
    return len(b) > 10_000 and (b[:8] == b"\x89PNG\r\n\x1a\n" or b[:3] == b"\xff\xd8\xff" or b[8:12] == b"WEBP")


def generate(prompt: str, destination: Path, seed: int, *, negative: str = "",
             width: int = 1280, height: int = 720, providers: list[str] | None = None) -> str:
    """Write a PNG to destination from the first cloud provider that works; '' if none did."""
    for name in providers if providers is not None else order():
        if _failures.get(name, 0) >= BREAK_AFTER:
            continue
        try:
            data = PROVIDERS[name](prompt, negative, width, height, seed)
            if not _is_image(data):
                raise RuntimeError("not an image")
        except urllib.error.HTTPError as e:
            # quota / payment / auth problems won't fix themselves during a run
            _failures[name] = BREAK_AFTER if e.code in (401, 402, 403, 429) else _failures.get(name, 0) + 1
            print(f"  cloud image: {name} HTTP {e.code}; next", flush=True)
            continue
        except Exception as e:  # noqa: BLE001 - any provider failure means "try the next one"
            timed_out = isinstance(e, TimeoutError) or "timed out" in str(e)
            _failures[name] = BREAK_AFTER if timed_out else _failures.get(name, 0) + 1
            print(f"  cloud image: {name} failed ({type(e).__name__}: {str(e)[:120]}); next", flush=True)
            continue
        _failures[name] = 0
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _save_png(data, destination, width, height, crop_bottom=0.06 if name == "pollinations" else 0.0)
        return name
    return ""


def _save_png(data: bytes, destination: Path, width: int, height: int, crop_bottom: float = 0.0) -> None:
    """Normalise to the panel size: drop a provider's watermark strip, center-crop to the
    target aspect, resize."""
    from io import BytesIO
    from PIL import Image
    im = Image.open(BytesIO(data)).convert("RGB")
    if crop_bottom:
        im = im.crop((0, 0, im.width, int(im.height * (1 - crop_bottom))))
    target = width / height
    if im.width / im.height > target:
        w = int(im.height * target)
        x = (im.width - w) // 2
        im = im.crop((x, 0, x + w, im.height))
    else:
        h = int(im.width / target)
        y = (im.height - h) // 2
        im = im.crop((0, y, im.width, y + h))
    im.resize((width, height), Image.LANCZOS).save(destination, "PNG")
