#!/usr/bin/env python3
"""
watcher.py - Zero-dependency file watcher for the LLM Wiki workflow.

Watches raw/ for new files and automatically runs agent.py ingest on each
one. Uses polling (no third-party watchdog library needed).

Usage:
    python3 tools/watcher.py              # poll every 10 seconds
    python3 tools/watcher.py --interval 30
    python3 tools/watcher.py --dry-run    # print detections, don't ingest

Configuration:
    ANTHROPIC_API_KEY   Required (passed through to agent.py).
    WIKI_MODEL          Optional model override (passed through to agent.py).
    WIKI_ROOT           Optional project root override.

The watcher records which files it has already processed in a small state
file at .watcher-state (gitignored). Delete that file to re-process everything.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

STATE_FILE = ".watcher-state"
IGNORE_PATTERNS = {".gitkeep", ".DS_Store", "Thumbs.db"}


def find_root(explicit=None) -> Path:
    if explicit:
        root = Path(explicit).resolve()
        if not (root / "wiki").is_dir():
            sys.exit(f"error: --root {root} has no wiki/ directory")
        return root
    here = Path.cwd().resolve()
    for cand in [here, *here.parents]:
        if (cand / "wiki").is_dir():
            return cand
    sys.exit("error: not inside a wiki project (no wiki/ directory found).")


def load_state(root: Path) -> set:
    state_path = root / STATE_FILE
    if not state_path.exists():
        return set()
    try:
        return set(json.loads(state_path.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_state(root: Path, seen: set):
    state_path = root / STATE_FILE
    state_path.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")


def scan_raw(root: Path) -> list:
    raw_dir = root / "raw"
    files = []
    for path in sorted(raw_dir.rglob("*")):
        if path.is_file() and path.name not in IGNORE_PATTERNS:
            files.append(path.relative_to(root).as_posix())
    return files


def run_ingest(root: Path, rel_path: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [DRY-RUN] would ingest: {rel_path}")
        return True

    agent_script = root / "tools" / "agent.py"
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, str(agent_script), "--root", str(root), "ingest", rel_path],
        env=env,
    )
    return result.returncode == 0


def watch(root: Path, interval: int, dry_run: bool, once: bool):
    seen = load_state(root)
    print(f"Watching {root / 'raw'} (interval={interval}s, dry_run={dry_run})")
    print(f"Already-seen files loaded: {len(seen)}")
    print("Press Ctrl+C to stop.\n")

    while True:
        current = set(scan_raw(root))
        new_files = current - seen

        for rel in sorted(new_files):
            print(f"[{_now()}] New file detected: {rel}")
            ok = run_ingest(root, rel, dry_run)
            if ok or dry_run:
                seen.add(rel)
                save_state(root, seen)
            else:
                print(f"  [WARN] ingest failed for {rel} — will retry next cycle")

        if once:
            break

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nWatcher stopped.")
            break


def _now() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="watcher",
        description="Watch raw/ and auto-ingest new files via agent.py",
    )
    p.add_argument("--root", help="wiki project root (default: auto-detect)")
    p.add_argument("--interval", type=int, default=10,
                   help="polling interval in seconds (default: 10)")
    p.add_argument("--dry-run", action="store_true",
                   help="detect files but do not call agent.py ingest")
    p.add_argument("--once", action="store_true",
                   help="scan once and exit (useful for cron/Task Scheduler)")
    args = p.parse_args(argv)

    root = find_root(args.root)
    watch(root, args.interval, args.dry_run, args.once)


if __name__ == "__main__":
    main()
