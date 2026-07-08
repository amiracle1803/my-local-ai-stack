"""
run_nightly.py  --  The Project 2 orchestrator. This is what the scheduler runs.

Each night it:
  1. Checks Ollama is up (clear message + exit if not).
  2. Takes a lock so two runs can't overlap.
  3. Finds notes changed since the last successful run.
  4. Extracts tasks/decisions/insights from each (extract.py) -> running logs.
  5. Writes a Daily Review, plus a Weekly Review on Sundays (summarize.py).
  6. Saves the run time so next time only new changes are processed.

Everything it writes goes to <vault>/_generated/. Your notes are never touched.
A full log of each run is kept in <vault>/_generated/logs/.
"""

from __future__ import annotations
import sys
import time
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.lib import llm, notes  # noqa: E402
from shared.lib.state import load_state, save_state, lock  # noqa: E402

import extract  # noqa: E402
import summarize  # noqa: E402

NAMESPACE = "second_brain"


def _log(msg: str, log_lines: list[str]) -> None:
    stamp = dt.datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line)
    log_lines.append(line)


def run() -> int:
    log_lines: list[str] = []
    started = time.time()
    _log("Nightly run starting.", log_lines)

    state = load_state(NAMESPACE)
    last_run = float(state.get("last_run_ts", 0))

    # 1. find changed notes (first ever run: process everything once)
    if last_run == 0:
        changed = notes.list_markdown()
        _log(f"First run: processing all {len(changed)} notes.", log_lines)
    else:
        changed = notes.list_markdown(since_ts=last_run)
        _log(f"{len(changed)} note(s) changed since last run.", log_lines)

    # 2. extract structured items
    total_new = 0
    for p in changed:
        try:
            text = notes.read_note(p)
            extraction = extract.extract_note(text)
            n = extract.file_items(extraction, p.name, state)
            if n:
                _log(f"  {p.name}: filed {n} new item(s).", log_lines)
            total_new += n
        except Exception as exc:  # noqa: BLE001 - one bad note shouldn't kill the run
            _log(f"  {p.name}: ERROR {exc}", log_lines)
    _log(f"Filed {total_new} new item(s) total.", log_lines)

    # 3. daily review (always) + weekly review (Sundays)
    try:
        out = summarize.write_daily_review(changed)
        _log(f"Wrote daily review -> {out.name}", log_lines)
    except Exception as exc:  # noqa: BLE001
        _log(f"Daily review failed: {exc}", log_lines)

    if notes.is_sunday():
        try:
            week_notes = notes.list_markdown(since_ts=time.time() - 7 * 86400)
            out = summarize.write_weekly_review(week_notes)
            _log(f"Wrote weekly review -> {out.name}", log_lines)
        except Exception as exc:  # noqa: BLE001
            _log(f"Weekly review failed: {exc}", log_lines)

    # 4. remember when we ran, so next time only new changes are processed
    state["last_run_ts"] = started
    save_state(NAMESPACE, state)

    took = int(time.time() - started)
    _log(f"Done in {took}s.", log_lines)

    # write the run log into the vault for later inspection
    notes.write_generated(
        f"logs/nightly-{notes.now_stamp()}.log", "\n".join(log_lines) + "\n"
    )
    return 0


def main() -> int:
    llm.require_ollama()
    try:
        with lock(NAMESPACE, stale_seconds=3 * 3600):
            return run()
    except RuntimeError as exc:
        print(exc)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
