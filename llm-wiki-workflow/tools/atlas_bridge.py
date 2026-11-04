#!/usr/bin/env python3
"""
atlas_bridge.py — Connect the LLM Wiki to a running Agent Atlas instance.

The LLM Wiki is the knowledge layer for Agent Atlas. This bridge lets you:
  - Submit tasks to Agent Atlas from the wiki CLI
  - Check Agent Atlas health and job status
  - Trigger Obsidian vault re-indexing in Atlas
  - Search the Atlas knowledge base

Usage:
    python tools/atlas_bridge.py status
    python tools/atlas_bridge.py run "Research the best vector database for local use"
    python tools/atlas_bridge.py run "Summarize recent sessions" --background
    python tools/atlas_bridge.py jobs
    python tools/atlas_bridge.py agents
    python tools/atlas_bridge.py search "collaboration bus"
    python tools/atlas_bridge.py reindex

Configuration:
    ATLAS_URL   Base URL for Agent Atlas API (default: http://localhost:8000)

No third-party dependencies. Python 3.8+. Uses urllib only.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ATLAS_URL = os.environ.get("ATLAS_URL", "http://localhost:8000").rstrip("/")


def _get(path: str) -> dict:
    url = f"{ATLAS_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"error": f"Cannot reach Agent Atlas at {ATLAS_URL}: {e.reason}",
                "tip": "Is Agent Atlas running? Start it with: cd agent-atlas && python -m uvicorn backend.app.main:app"}
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, payload: dict) -> dict:
    url = f"{ATLAS_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {body}"}
    except urllib.error.URLError as e:
        return {"error": f"Cannot reach Agent Atlas at {ATLAS_URL}: {e.reason}",
                "tip": "Is Agent Atlas running?"}
    except Exception as e:
        return {"error": str(e)}


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_status(args):
    """Show Agent Atlas system health."""
    data = _get("/api/health")
    if "error" in data:
        print(f"[OFFLINE] {data['error']}")
        if "tip" in data:
            print(f"  Tip: {data['tip']}")
        return
    print(f"[ONLINE] Agent Atlas at {ATLAS_URL}")
    print(f"  Status:  {data.get('status', 'unknown')}")
    print(f"  Agents:  {data.get('agents_loaded', '?')} registered")
    print(f"  Models:  {data.get('models_loaded', '?')} loaded")


def cmd_run(args):
    """Submit a task to Agent Atlas."""
    payload = {
        "goal": args.goal,
        "run_mode": "background" if args.background else "sync",
        "risk_level": args.risk,
        "context": {},
    }
    print(f"Submitting to Agent Atlas: {args.goal[:80]}")
    print(f"  Mode: {'background' if args.background else 'sync'}, Risk: {args.risk}")
    if not args.background:
        print("  Waiting for response (sync mode — may take up to 90s)...")

    data = _post("/api/run", payload)

    if "error" in data:
        print(f"[ERROR] {data['error']}")
        return

    job_id = data.get("job_id", "?")
    print(f"\n  Job ID: {job_id}")
    if args.background:
        print(f"  Status: queued — check with: python tools/atlas_bridge.py jobs")
    else:
        response = data.get("response", "")
        print(f"\n--- Response ---\n{response}")


def cmd_jobs(args):
    """List recent jobs."""
    data = _get("/api/jobs/")
    if "error" in data:
        print(f"[ERROR] {data['error']}")
        return

    jobs = data if isinstance(data, list) else data.get("jobs", [])
    if not jobs:
        print("No jobs found.")
        return

    limit = args.limit
    print(f"Recent jobs (showing up to {limit}):")
    for job in jobs[:limit]:
        status = job.get("status", "?")
        title = job.get("title") or job.get("type") or job.get("id", "?")[:20]
        created = job.get("created_at", "")[:16]
        jid = job.get("id", "?")[:12]
        print(f"  [{status:8}] {jid}  {created}  {title}")


def cmd_agents(args):
    """List all registered agents."""
    data = _get("/api/agents/")
    if "error" in data:
        print(f"[ERROR] {data['error']}")
        return

    agents = data if isinstance(data, list) else data.get("agents", [])
    if not agents:
        print("No agents returned.")
        return

    by_layer: dict[str, list] = {}
    for a in agents:
        layer = a.get("layer", "unknown")
        by_layer.setdefault(layer, []).append(a)

    layer_order = ["control", "knowledge", "action", "platform", "unknown"]
    for layer in layer_order:
        if layer not in by_layer:
            continue
        print(f"\n{layer.upper()} LAYER")
        for a in by_layer[layer]:
            aid = a.get("id", "?")
            name = a.get("display_name", aid)
            desc = a.get("description", "")[:60]
            print(f"  {aid:30} {name}")
            if desc:
                print(f"  {'':30} {desc}")


def cmd_search(args):
    """Search Agent Atlas's Obsidian vault."""
    data = _post("/api/obsidian/search", {"query": args.query, "top_k": args.top_k})
    if "error" in data:
        print(f"[ERROR] {data['error']}")
        return

    results = data if isinstance(data, list) else data.get("results", [])
    if not results:
        print(f"No results for: {args.query}")
        return

    print(f"Search results for '{args.query}':")
    for i, r in enumerate(results, 1):
        path = r.get("path") or r.get("metadata", {}).get("path", "?")
        score = r.get("score", r.get("distance", "?"))
        text = r.get("text", r.get("content", ""))[:120].replace("\n", " ")
        print(f"\n  [{i}] {path}  (score: {score})")
        print(f"      {text}...")


def cmd_reindex(args):
    """Trigger Agent Atlas to re-index the Obsidian vault."""
    print("Triggering Obsidian vault re-index in Agent Atlas...")
    data = _post("/api/obsidian/index", {})
    if "error" in data:
        print(f"[ERROR] {data['error']}")
        return
    print(f"[OK] {data.get('message', 'Re-index triggered.')}")
    print("     Agent Atlas will index the LLM-Wiki pages you just synced.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="atlas_bridge",
        description="Connect the LLM Wiki to a running Agent Atlas instance.",
        epilog=f"Agent Atlas URL: {ATLAS_URL}  (set ATLAS_URL env var to change)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Check Agent Atlas health").set_defaults(func=cmd_status)

    p = sub.add_parser("run", help="Submit a task to Agent Atlas")
    p.add_argument("goal", help="The task or question to submit")
    p.add_argument("--background", "-b", action="store_true",
                   help="Queue as background job (returns immediately)")
    p.add_argument("--risk", choices=["low", "medium", "high", "critical"],
                   default="low", help="Risk level (default: low)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("jobs", help="List recent jobs")
    p.add_argument("--limit", type=int, default=20, help="Max jobs to show (default: 20)")
    p.set_defaults(func=cmd_jobs)

    sub.add_parser("agents", help="List all registered agents").set_defaults(func=cmd_agents)

    p = sub.add_parser("search", help="Search the Obsidian vault via Agent Atlas")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=5, dest="top_k")
    p.set_defaults(func=cmd_search)

    sub.add_parser("reindex", help="Trigger Atlas to re-index Obsidian vault").set_defaults(func=cmd_reindex)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
