#!/usr/bin/env python3
"""
batch_queue.py
Queue multiple ComfyUI workflows sequentially via API.
"""

import json, time, argparse
from pathlib import Path
import urllib.request

def queue_workflow(url, workflow):
    data = json.dumps({"prompt": workflow}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", required=True)
    p.add_argument("--url", default="http://localhost:8188/prompt")
    args = p.parse_args()
    dirpath = Path(args.dir)
    for wf_path in sorted(dirpath.glob("*.json")):
        wf = json.loads(wf_path.read_text())
        print(f"Queueing {wf_path.name}...")
        try:
            res = queue_workflow(args.url, wf)
            print("Queued, prompt_id:", res.get("prompt_id"))
            time.sleep(2)
        except Exception as e:
            print(f"Failed {wf_path.name}: {e}")

if __name__ == "__main__":
    main()