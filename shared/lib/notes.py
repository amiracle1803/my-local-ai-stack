"""
notes.py  --  Safe helpers for reading and writing your Obsidian vault.

The single most important rule in this whole project:
    >>> Agents ONLY ever write inside <vault>/_generated/ <<<
Your own notes are never touched, moved, or overwritten. If the AI ever makes
a mess, you delete the _generated folder and nothing of yours is lost.
"""

from __future__ import annotations
import datetime as _dt
import os
import re
from pathlib import Path

from .config import load_config

CFG = load_config()

# folders we never scan as "notes"
_SKIP_DIRS = {".obsidian", ".trash", ".git", CFG["generated_subdir"]}


def vault_root() -> Path:
    p = Path(CFG["vault_path"])
    p.mkdir(parents=True, exist_ok=True)
    return p


def generated_dir() -> Path:
    """The one folder agents are allowed to write to."""
    p = vault_root() / CFG["generated_subdir"]
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_markdown(since_ts: float | None = None) -> list[Path]:
    """
    Return .md files in the vault (excluding _generated and dotfolders).
    If since_ts is given, only files modified after that Unix timestamp.
    """
    out: list[Path] = []
    root = vault_root()
    for dirpath, dirnames, filenames in os.walk(root):
        # prune skip dirs in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if not name.lower().endswith(".md"):
                continue
            fp = Path(dirpath) / name
            try:
                mtime = fp.stat().st_mtime
            except OSError:
                continue
            if since_ts is None or mtime > since_ts:
                out.append(fp)
    return sorted(out)


def read_note(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"[could not read {path}: {exc}]"


def write_generated(relpath: str, content: str) -> Path:
    """Overwrite a file under _generated (create parent dirs as needed)."""
    target = generated_dir() / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def append_generated(relpath: str, content: str, header_if_new: str = "") -> Path:
    """Append to a file under _generated, writing a header the first time."""
    target = generated_dir() / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    new_file = not target.exists()
    with target.open("a", encoding="utf-8") as fh:
        if new_file and header_if_new:
            fh.write(header_if_new.rstrip() + "\n\n")
        fh.write(content.rstrip() + "\n")
    return target


# --- small utilities -------------------------------------------------------
def today_str() -> str:
    return _dt.date.today().isoformat()


def now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def is_sunday() -> bool:
    return _dt.date.today().weekday() == 6


def slugify(text: str, max_len: int = 50) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return (text[:max_len].strip("-")) or "untitled"


def find_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s<>\")]+", text)
