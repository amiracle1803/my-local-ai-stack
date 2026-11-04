#!/usr/bin/env python3
"""
queue.py — submit ComfyUI workflows to the local server. Consolidates the two
root queue scripts: batch_queue (queue raw workflow JSON) and convert_and_queue
(convert a workflow to API prompt format via nodes_to_prompt, then queue it).
"""

import json
import time
import urllib.request
import urllib.error
from pathlib import Path

# nodes_to_prompt lives at the repo root as a shared ComfyUI helper; import it
# by adding the repo root (three levels up from this file) to sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
import sys
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from nodes_to_prompt import nodes_to_prompt  # noqa: E402


def _post(url: str, payload: dict) -> dict:
    """POST a JSON payload and return the parsed response body."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def queue_workflow(url: str, workflow: dict, delay: float = 0) -> dict:
    """Queue a raw workflow JSON directly and return the server response."""
    res = _post(url, {"prompt": workflow})
    time.sleep(delay)
    return res


def queue_workflow_dir(directory: str, url: str = "http://localhost:8188/prompt",
                       convert: bool = False, delay: float = 0) -> int:
    """Queue every *.json in `directory`, optionally converting each workflow to
    API prompt format first. Returns the number of successfully queued files."""
    ok = 0
    for wf_path in sorted(Path(directory).glob("*.json")):
        wf = json.loads(wf_path.read_text(encoding="utf-8"))
        payload = nodes_to_prompt(wf) if convert else {"prompt": wf}
        print(f"Queueing {wf_path.name}...")
        try:
            res = _post(url, payload)
            print("  queued:", res.get("prompt_id"))
            ok += 1
            time.sleep(delay)
        except urllib.error.HTTPError as e:
            print("  FAILED:", e.code, e.read().decode()[:300])
        except Exception as e:  # noqa: BLE001 - report any queue failure and move on
            print("  FAILED:", e)
    print(f"Queued {ok}/{len(list(Path(directory).glob('*.json')))} workflows")
    return ok


def main(directory: str, url: str = "http://localhost:8188/prompt",
         convert: bool = False, delay: float = 0) -> int:
    """CLI entry: queue a directory of workflows."""
    return queue_workflow_dir(directory, url, convert, delay)
