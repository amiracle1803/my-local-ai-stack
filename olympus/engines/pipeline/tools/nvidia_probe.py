"""NVIDIA NIM catalog probe — find models that beat the local stack.

Tests candidate hosted models on pipeline-realistic tasks with LONG timeouts
(the point is: does it give a meaningful, better result even if slower than
local qwen3:8b / qwen2.5vl:7b?). Respects the free-tier rate limit by sleeping
between calls.

Text tasks (mimic pipeline LLM stages):
  * JSON  : extract a character profile from a story excerpt -> strict JSON
            (like stage1 worldbible)
  * prose : write one atmospheric scene from a brief (like stage0/script)

Vision task (mimic stage3b panel QC):
  * QC    : judge a real generated panel for render validity + on-model facts

Usage:
  python tools/nvidia_probe.py                    # all
  python tools/nvidia_probe.py --text-only
  python tools/nvidia_probe.py --models deepseek-ai/deepseek-v4-pro-0813
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import requests

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))
from pipeline.config import PipelineConfig  # noqa: E402
from pipeline.nvidia_gen import resolve_api_key  # noqa: E402

BASE = "https://integrate.api.nvidia.com/v1"
LONG_TIMEOUT = 300  # "increase wait time" — give big hosted models room
GAP_S = 12  # sleep between calls to avoid free-tier 529 rate limit

TEXT_JSON_PROMPT = (
    "You are a world-bible analyst. From the story below, extract a JSON "
    "character profile with EXACT keys: {\"name\": str, \"role\": str, "
    "\"appearance\": {\"hair\": str, \"eyes\": str, \"build\": str, "
    "\"clothing\": str}, \"traits\": [str, ...]}. Return ONLY JSON, no prose.\n\n"
    "STORY: The lighthouse keeper, a wiry man named Kaito with unkempt silver "
    "hair and storm-grey eyes, wore a salt-stained navy oilskin. He was stubborn "
    "and quiet, but fiercely loyal to the mer-creature Nereida he had sworn to "
    "protect. Nereida was slender, with scales like shattered moonlight and "
    "emerald eyes."
)

TEXT_PROSE_PROMPT = (
    "Write one vivid, cinematic anime-style scene (120-150 words) from this "
    "brief: a lighthouse keeper and a mer-creature exchange a single line of "
    "dialogue on a cliff at dusk. Use strong sensory detail and a melancholic "
    "tone. No stage directions or meta commentary."
)

QC_PROMPT = (
    "You are an anime-production QC judge. Look at this image and answer as "
    "JSON only, no prose: {\"render_valid\": bool, \"artifacts\": bool, "
    "\"on_model\": bool, \"notes\": \"short\"}. "
    "render_valid=false if blank/corrupt/black. artifacts=true on smeared "
    "limbs/garbled text. on_model=true if it looks like a coherent anime scene."
)

TEXT_MODELS = [
    "deepseek-ai/deepseek-v4-flash-0731",   # baseline (tested working)
    "deepseek-ai/deepseek-v4-pro-0813",     # bigger deepseek
    "moonshotai/kimi-k3",                    # strong reasoning
    "nvidia/nemotron-ultra-253b-v1",         # 253B flagship
    "nvidia/nemotron-3-ultra-550b-a55b",     # 550B
    "writer/palmyra-creative-122b",          # creative-writing-tuned
    "openai/gpt-oss-20b",                    # Apache-2.0 open model
    "minimaxai/minimax-m3",
]

VISION_MODELS = [
    "meta/llama-3.2-90b-vision-instruct",    # configured default
    "meta/llama-3.2-11b-vision-instruct",
    "nvidia/neva-22b",
]


def headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def chat(key, model, messages, timeout=LONG_TIMEOUT, max_tokens=2000):
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/chat/completions", json=payload,
                          headers=headers(key), timeout=timeout)
        code = r.status_code
        if code != 200:
            return {"status": code, "latency": time.time() - t0,
                    "body": r.text[:120]}
        data = r.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning_content")
        return {"status": 200, "latency": time.time() - t0, "content": content}
    except requests.RequestException as e:
        return {"status": "err", "latency": time.time() - t0, "body": str(e)[:120]}


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def json_ok(text) -> tuple:
    if not text:
        return False, "empty"
    try:
        json.loads(text)  # also strip fences if present
        return True, "parsed"
    except Exception:
        # try stripping markdown fences
        import re
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                json.loads(m.group(0)); return True, "parsed(fence-stripped)"
            except Exception:
                pass
        return False, "not-json"


def run_text(key, model):
    print(f"\n{'='*70}\nTEXT MODEL: {model}")
    # JSON task
    res = chat(key, model, [{"role": "user", "content": TEXT_JSON_PROMPT}], max_tokens=1200)
    if res["status"] == 200:
        ok, why = json_ok(res["content"])
        print(f"  [JSON] {ok and 'PASS' or 'FAIL'} ({why}) | {res['latency']:.0f}s")
        print(f"         {str(res['content'])[:200]}")
    else:
        print(f"  [JSON] {res['status']} | {res['latency']:.0f}s | {res.get('body')}")
    time.sleep(GAP_S)
    # prose task
    res = chat(key, model, [{"role": "user", "content": TEXT_PROSE_PROMPT}], max_tokens=800)
    if res["status"] == 200:
        wc = len((res["content"] or "").split())
        print(f"  [PROSE] ok | {wc} words | {res['latency']:.0f}s")
        print(f"         {str(res['content'])[:180]}...")
    else:
        print(f"  [PROSE] {res['status']} | {res['latency']:.0f}s | {res.get('body')}")
    time.sleep(GAP_S)


def run_vision(key, model, image):
    print(f"\n{'='*70}\nVISION MODEL: {model}")
    content = [{"type": "text", "text": QC_PROMPT},
               {"type": "image_url", "image_url": {"url": data_uri(image)}}]
    res = chat(key, model, [{"role": "user", "content": content}], max_tokens=800)
    if res["status"] == 200:
        ok, why = json_ok(res["content"])
        print(f"  [QC] {ok and 'PASS' or 'FAIL'} ({why}) | {res['latency']:.0f}s")
        print(f"       {str(res['content'])[:200]}")
    else:
        print(f"  [QC] {res['status']} | {res['latency']:.0f}s | {res.get('body')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-only", action="store_true")
    ap.add_argument("--vision-only", action="store_true")
    ap.add_argument("--models", nargs="*", default=[])
    ap.add_argument("--image", default="olympus/engines/pipeline/projects/lantern-test/panels/blk-001/sh-001-01.png")
    args = ap.parse_args()

    cfg = PipelineConfig.load()
    key = resolve_api_key(cfg.nim)
    if not key:
        print("no NVIDIA API key"); sys.exit(1)

    img = Path(args.image)
    if not img.exists():
        print(f"image not found: {img}"); img = None

    text_models = args.models or TEXT_MODELS
    vision_models = args.models or VISION_MODELS

    if not args.vision_only:
        for m in text_models:
            run_text(key, m)
    if not args.text_only and img:
        for m in vision_models:
            run_vision(key, m, img)
            time.sleep(GAP_S)
    print("\nDONE.")


if __name__ == "__main__":
    main()