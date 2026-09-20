#!/usr/bin/env python3
"""Benchmark local Voice Studio providers through the stable HTTP contract."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
import wave
from pathlib import Path


def synthesize(base_url: str, text: str, voice: str, output: Path) -> dict:
    started = time.perf_counter()
    payload = json.dumps({"text": text, "voice": voice, "speed": 1.0}).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/tts",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    duration = None
    try:
        with wave.open(str(output), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            actual_bytes = max(0, output.stat().st_size - 44)
            expected_bytes = frames * wav.getnchannels() * wav.getsampwidth()
            if expected_bytes > actual_bytes * 4:
                frames = actual_bytes // max(1, wav.getnchannels() * wav.getsampwidth())
            duration = frames / float(rate)
    except (OSError, wave.Error):
        pass
    return {
        "output": str(output),
        "bytes": len(data),
        "content_type": content_type,
        "latency_seconds": round(time.perf_counter() - started, 3),
        "audio_seconds": round(duration, 3) if duration is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5050")
    parser.add_argument("--output-dir", type=Path, default=Path("tts-benchmarks"))
    parser.add_argument("--text", default=(
        "The bloodline was not a legend. It was a promise carried through every wound, "
        "every silence, and every impossible dawn."
    ))
    parser.add_argument("--voice", default="af_heart")
    args = parser.parse_args()
    result = synthesize(args.base_url, args.text, args.voice, args.output_dir / "voice_studio.wav")
    result.update({"provider": "voice-studio", "voice": args.voice, "text": args.text})
    manifest = args.output_dir / "benchmark.json"
    manifest.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
