#!/usr/bin/env python3
"""Non-generative health probe for optional cloud providers.

Reads only environment variables/gitignored secret files. It never submits
prompts, images, video, or audio and never prints credential values.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def present(env: str, secret_file: str | None = None) -> bool:
    if os.getenv(env, "").strip():
        return True
    if secret_file and (ROOT / secret_file).exists():
        return bool((ROOT / secret_file).read_text(encoding="utf-8").strip())
    return False


def probe(url: str, headers: dict[str, str] | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return {"reachable": True, "status": response.status}
    except urllib.error.HTTPError as exc:
        return {"reachable": True, "status": exc.code}
    except Exception as exc:
        return {"reachable": False, "error": type(exc).__name__}


def main() -> int:
    hf = present("HF_TOKEN", ".agent-secrets/hf_token")
    fal = present("FAL_KEY", ".agent-secrets/fal_key")
    replicate = present("REPLICATE_API_TOKEN", ".agent-secrets/replicate_token")
    pollinations = present("POLLINATIONS_API_KEY", ".agent-secrets/pollinations_key")
    nvidia = present("NVIDIA_API_KEY", ".agent-secrets/nvidia_key")
    result = {
        "credentials": {
            "huggingface": hf,
            "fal": fal,
            "replicate": replicate,
            "pollinations": pollinations,
            "nvidia": nvidia,
        },
        "providers": {
            "huggingface": {
                "capabilities": ["t2i", "i2i"],
                "billing": "free quota may be limited and provider/model dependent",
                "probe": probe("https://router.huggingface.co/v1/models", {"Authorization": f"Bearer {os.getenv('HF_TOKEN', '')}"} if hf else None),
            },
            "fal": {
                "capabilities": ["t2i", "i2i", "i2v", "tts"],
                "billing": "paid API; trial/free credits are account-dependent",
                "probe": probe("https://fal.ai/docs/model-apis/authentication"),
            },
            "replicate": {
                "capabilities": ["t2i", "i2i", "i2v", "tts"],
                "billing": "pay-as-you-go; selected free trials/models only",
                "probe": probe("https://api.replicate.com/v1/models", {"Authorization": f"Bearer {os.getenv('REPLICATE_API_TOKEN', '')}"} if replicate else None),
            },
            "pollinations": {
                "capabilities": ["t2i", "i2i", "i2v", "tts"],
                "billing": "verify current official quota/auth terms before use",
                "probe": probe("https://pollinations.ai"),
            },
            "nvidia": {
                "capabilities": ["llm", "vision"],
                "billing": "account/quota dependent",
                "probe": {"configured": nvidia},
            },
        },
        "safety": "No generation requests were submitted; credential values were not printed.",
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
