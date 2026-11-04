#!/usr/bin/env python3
"""Run a bounded Anima T2I smoke test against local ComfyUI."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
import uuid
from pathlib import Path


def request_json(url: str, payload: dict | None = None) -> dict:
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read())


def graph(prompt: str, seed: int, prefix: str) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "anima-base-v1.0.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion",
            "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {
            "width": 512, "height": 288, "batch_size": 1}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {
            "text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {
            "text": "low quality, blurry, text, watermark, deformed, extra fingers",
            "clip": ["2", 0]}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": 8, "cfg": 4.0,
            "sampler_name": "er_sde", "scheduler": "simple",
            "positive": ["5", 0], "negative": ["6", 0],
            "latent_image": ["4", 0], "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {
            "samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "images": ["8", 0], "filename_prefix": prefix}},
    }


def run(base_url: str, prompt: str, seed: int, timeout: int, prefix: str) -> dict:
    client_id = str(uuid.uuid4())
    queued = request_json(f"{base_url}/prompt", {
        "prompt": graph(prompt, seed, prefix), "client_id": client_id,
    })
    prompt_id = queued["prompt_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = request_json(f"{base_url}/history/{prompt_id}")
        item = history.get(prompt_id)
        if item:
            status = item.get("status", {})
            if status.get("status_str") == "error" or status.get("completed") is False:
                raise RuntimeError(json.dumps(item, indent=2))
            if item.get("outputs"):
                return {"prompt_id": prompt_id, "outputs": item["outputs"]}
        time.sleep(2)
    raise TimeoutError(f"ComfyUI prompt {prompt_id} did not finish in {timeout}s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8188")
    parser.add_argument("--prompt", default="anime key visual, a lone swordsman beneath a red moon, cinematic cel shading")
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--marker", type=Path)
    args = parser.parse_args()
    result = run(args.base_url.rstrip("/"), args.prompt, args.seed, args.timeout, "olympus_anima_smoke")
    if args.marker:
        args.marker.parent.mkdir(parents=True, exist_ok=True)
        args.marker.write_text(json.dumps({"profile": "stage3b_default-panel",
                                           "engine": "anima",
                                           "seed": args.seed,
                                           "result": result}, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
