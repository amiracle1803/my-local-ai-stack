"""
run_inbox.py  --  Batch mode for the Task Dropbox.

Instead of the web form, you can drop plain .txt or .md files into
project1-ops-hub/task-inbox/. Run this script (or schedule it) and it will:
  - process every file in the inbox,
  - write the result to task-outbox/,
  - move the original into done/ so it isn't processed twice.

This is the robust, no-web-server way to feed the hub -- e.g. via a scheduled
task every few minutes, or synced from your phone into the inbox folder.
"""

from __future__ import annotations
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process import process_task, save_result  # noqa: E402
from shared.lib import llm  # noqa: E402
from shared.lib.config import load_config  # noqa: E402
from shared.lib.state import lock  # noqa: E402

CFG = load_config()


def main() -> int:
    inbox = Path(CFG["task_inbox"])
    done = Path(CFG["task_done"])
    inbox.mkdir(parents=True, exist_ok=True)
    done.mkdir(parents=True, exist_ok=True)

    files = [p for p in inbox.iterdir()
             if p.is_file() and p.suffix.lower() in (".txt", ".md")]
    if not files:
        print("Inbox is empty. Drop .txt or .md files into:", inbox)
        return 0

    llm.require_ollama()

    processed = 0
    for f in sorted(files):
        task = f.read_text(encoding="utf-8", errors="replace").strip()
        if not task:
            # empty file -> just clear it out
            shutil.move(str(f), str(done / f.name))
            continue

        print(f"-> processing {f.name} ...")
        result = process_task(task)
        out = save_result(task, result)
        print(f"   [{result['category']}] -> {out.name}")

        # move original to done/ (add a number if a name clash happens)
        target = done / f.name
        n = 1
        while target.exists():
            target = done / f"{f.stem}({n}){f.suffix}"
            n += 1
        shutil.move(str(f), str(target))
        processed += 1

    print(f"Done. Processed {processed} file(s).")
    return 0


if __name__ == "__main__":
    # a lock stops two scheduled runs overlapping if one is slow
    try:
        with lock("task_inbox", stale_seconds=1800):
            raise SystemExit(main())
    except RuntimeError as exc:
        print(exc)
        raise SystemExit(0)
