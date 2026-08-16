#!/usr/bin/env python3
"""
convert_and_queue.py
Convert all workflows in a dir to API prompts and queue them sequentially.
"""

import json, sys, time
from pathlib import Path
import urllib.request, urllib.error

sys.path.insert(0, str(Path(__file__).parent))
from nodes_to_prompt import nodes_to_prompt

def queue(url, prompt):
    data = json.dumps(prompt).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dir", required=True)
    p.add_argument("--url", default="http://localhost:8188/prompt")
    args = p.parse_args()
    for wf_path in sorted(Path(args.dir).glob("*.json")):
        wf = json.loads(wf_path.read_text())
        prompt = nodes_to_prompt(wf)
        print(f"Queueing {wf_path.name}...")
        try:
            res = queue(args.url, prompt)
            print("  queued:", res.get("prompt_id"))
        except urllib.error.HTTPError as e:
            print("  FAILED:", e.code, e.read().decode()[:300])
        except Exception as e:
            print("  FAILED:", e)

if __name__ == "__main__":
    main()