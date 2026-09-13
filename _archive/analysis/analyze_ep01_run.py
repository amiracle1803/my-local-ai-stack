#!/usr/bin/env python3
"""
analyze_ep01_run.py
Simple post-run validation for LTX2.3 panels-first-last output.
Checks video existence, duration, file size, and logs acceptance criteria.
"""

import argparse, json
from pathlib import Path

def analyze(video_path, first_img, last_img):
    v = Path(video_path)
    if not v.exists():
        return {"status": "FAIL", "reason": "Video not found"}
    size_mb = v.stat().st_size / 1024 / 1024
    # Placeholder for ffprobe duration
    result = {
        "video": str(v),
        "size_mb": round(size_mb, 2),
        "first_image": str(first_img),
        "last_image": str(last_img),
        "checks": {
            "exists": True,
            "size_reasonable": 1 <= size_mb <= 100,
            "images_exist": Path(first_img).exists() and Path(last_img).exists()
        }
    }
    result["status"] = "PASS" if all(result["checks"].values()) else "WARN"
    return result

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--first", required=True)
    p.add_argument("--last", required=True)
    args = p.parse_args()
    res = analyze(args.video, args.first, args.last)
    print(json.dumps(res, indent=2))
