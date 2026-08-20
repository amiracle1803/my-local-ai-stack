"""Filesystem memory v1 (memory.md §4/§7).

Files are the memory; vectors (Qdrant) come later. Phase 0 scope:
- ensure the memory tree
- write_error: err-<date>-<slug>.md with uniform frontmatter (§4) + failure ledger body (§7)
- find_errors: keyword/filename scan (no vector DB yet)
- MEMORY.md index maintenance (one line per entry)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .runstate import atomic_write, _slugify

HARNESS_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = HARNESS_ROOT / "memory"

STRATA = ("episodic", "semantic", "procedural", "errors", "inbox", "loops", "snapshots")
INDEX_NAME = "MEMORY.md"


@dataclass(frozen=True)
class ErrorHit:
    id: str
    path: Path
    title: str
    tags: list[str]
    score: int   # keyword overlap count


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def ensure_memory(memory_dir: Path = MEMORY_DIR) -> Path:
    for sub in STRATA:
        (memory_dir / sub).mkdir(parents=True, exist_ok=True)
    index = memory_dir / INDEX_NAME
    if not index.exists():
        atomic_write(index, "# MEMORY.md — recall index\n\n"
                            "One line per entry: `- [type] id — hook`\n\n")
    return memory_dir


# --- error memory --------------------------------------------------------

def write_error(
    task_id: str,
    symptom: str,
    context: str,
    root_cause: str,
    remedies: list[str],
    recommendation: str,
    *,
    tags: Optional[list[str]] = None,
    confidence: float = 0.8,
    supersedes: Optional[str] = None,
    memory_dir: Path = MEMORY_DIR,
    now: Optional[datetime] = None,
) -> Path:
    """Write an err-*.md entry (the anti-repetition organ, memory.md §7)."""
    ensure_memory(memory_dir)
    now = now or _utcnow()
    slug = _slugify(symptom)
    entry_id = f"err-{now:%Y%m%d}-{slug}"
    path = _unique_path(memory_dir / "errors" / f"{entry_id}.md")
    entry_id = path.stem
    tags = tags or _keywords(symptom)

    fm = _frontmatter(
        entry_id=entry_id, type_="error", title=symptom,
        tags=tags, task_refs=[task_id], confidence=confidence, supersedes=supersedes,
    )
    remedy_lines = "\n".join(f"- {r}" for r in remedies) or "- (none tried)"
    body = (
        f"{fm}\n"
        f"# {symptom}\n\n"
        f"## Symptom\n{symptom}\n\n"
        f"## Context\n{context}\n\n"
        f"## Root cause (hypothesis)\n{root_cause}\n\n"
        f"## Remedies tried\n{remedy_lines}\n\n"
        f"## Recommended next approach\n{recommendation}\n"
    )
    atomic_write(path, body)
    _append_index(memory_dir, "error", entry_id, symptom)
    return path


def write_episode(
    task_id: str,
    title: str,
    outcome: str,
    summary_lines: list[str],
    *,
    tags: Optional[list[str]] = None,
    confidence: float = 0.8,
    memory_dir: Path = MEMORY_DIR,
    now: Optional[datetime] = None,
) -> Path:
    """Write an episodic entry (<=30 body lines) after a task closes (memory.md §7).

    Same frontmatter conventions as write_error; single-writer discipline still applies
    (Phase 1 writes directly; the curator takes over dedup/expiry later).
    """
    ensure_memory(memory_dir)
    now = now or _utcnow()
    slug = _slugify(title)
    entry_id = f"epi-{now:%Y%m%d}-{slug}"
    path = _unique_path(memory_dir / "episodic" / f"{entry_id}.md")
    entry_id = path.stem
    tags = tags or _keywords(title)

    fm = _frontmatter(
        entry_id=entry_id, type_="episodic", title=title,
        tags=tags, task_refs=[task_id], confidence=confidence, supersedes=None,
    )
    lines = summary_lines[:30] or ["(no detail recorded)"]
    body_lines = "\n".join(f"- {ln}" for ln in lines)
    body = (
        f"{fm}\n"
        f"# {title}\n\n"
        f"## Outcome\n{outcome}\n\n"
        f"## What happened\n{body_lines}\n"
    )
    atomic_write(path, body)
    _append_index(memory_dir, "episodic", entry_id, title)
    return path


def find_errors(query_terms, memory_dir: Path = MEMORY_DIR, limit: int = 3) -> list[ErrorHit]:
    """Keyword/filename scan over memory/errors/, ranked by term overlap (memory.md §5)."""
    errors_dir = memory_dir / "errors"
    if not errors_dir.exists():
        return []
    if isinstance(query_terms, str):
        query_terms = _keywords(query_terms)
    terms = {t.lower() for t in query_terms if t}

    hits: list[ErrorHit] = []
    for path in sorted(errors_dir.glob("err-*.md")):
        text = path.read_text(encoding="utf-8").lower()
        stem = path.stem.lower()
        score = sum(1 for t in terms if t in text or t in stem)
        if score:
            title, tags = _parse_header(path)
            hits.append(ErrorHit(id=path.stem, path=path, title=title, tags=tags, score=score))
    hits.sort(key=lambda h: (-h.score, h.id))
    return hits[:limit]


# --- index ---------------------------------------------------------------

def _append_index(memory_dir: Path, type_: str, entry_id: str, hook: str) -> None:
    index = memory_dir / INDEX_NAME
    line = f"- [{type_}] {entry_id} — {hook.strip()}\n"
    existing = index.read_text(encoding="utf-8") if index.exists() else ""
    if f"] {entry_id} " in existing:  # idempotent
        return
    atomic_write(index, existing + line)


# --- snapshots (refine/rollback, ported from prime-agent /refine) --------

def snapshot_index(memory_dir: Path = MEMORY_DIR, now: Optional[datetime] = None) -> str:
    """Copy MEMORY.md into snapshots/ and record it in the snapshot manifest.

    A snapshot is the pre-task recall state: the immutable baseline that a later
    rollback restores. Returns the snapshot id ("snap-<ts>").
    """
    ensure_memory(memory_dir)
    now = now or _utcnow()
    snap_id = f"snap-{now:%Y%m%d-%H%M%S}"
    index_path = memory_dir / INDEX_NAME
    content = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    snap_dir = memory_dir / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(snap_dir / f"{snap_id}.md", content)
    manifest = _load_snapshot_manifest(memory_dir)
    manifest.append({
        "id": snap_id,
        "created": now.isoformat(),
        "index_lines": content.count("\n") + (1 if content else 0),
    })
    atomic_write(snap_dir / "manifest.json", json.dumps(manifest, indent=2))
    return snap_id


def rollback_index(snapshot_id: str, memory_dir: Path = MEMORY_DIR) -> int:
    """Restore MEMORY.md from a snapshot (the recall state a task started from).

    Files written since the snapshot are left on disk; only the index returns to
    the baseline, so a failed task's entries stop being recalled without data loss.
    Returns the number of index lines that were reverted.
    """
    snap_dir = memory_dir / "snapshots"
    snap_path = snap_dir / f"{snapshot_id}.md"
    if not snap_path.exists():
        raise FileNotFoundError(f"no snapshot {snapshot_id} in {snap_dir}")
    current = (memory_dir / INDEX_NAME).read_text(encoding="utf-8") if (memory_dir / INDEX_NAME).exists() else ""
    restored = snap_path.read_text(encoding="utf-8")
    atomic_write(memory_dir / INDEX_NAME, restored)
    return len([l for l in current.splitlines() if l not in restored.splitlines()])


def list_snapshots(memory_dir: Path = MEMORY_DIR) -> list[dict]:
    """Snapshot manifest entries, newest first (created DESC)."""
    return list(reversed(_load_snapshot_manifest(memory_dir)))


def _load_snapshot_manifest(memory_dir: Path) -> list[dict]:
    path = memory_dir / "snapshots" / "manifest.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# --- internals -----------------------------------------------------------

def _frontmatter(*, entry_id, type_, title, tags, task_refs, confidence, supersedes) -> str:
    tags_str = "[" + ", ".join(tags) + "]"
    refs_str = "[" + ", ".join(task_refs) + "]"
    sup = supersedes if supersedes else "null"
    return (
        "---\n"
        f"id: {entry_id}\n"
        f"type: {type_}\n"
        f"title: {title}\n"
        f"tags: {tags_str}\n"
        f"task_refs: {refs_str}\n"
        f"confidence: {confidence}\n"
        f"supersedes: {sup}\n"
        f"expires: null\n"
        "---\n"
    )


def _parse_header(path: Path) -> tuple[str, list[str]]:
    title, tags = path.stem, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("title:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("tags:"):
            raw = line.split(":", 1)[1].strip().strip("[]")
            tags = [t.strip() for t in raw.split(",") if t.strip()]
        elif line.strip() == "---" and title != path.stem:
            break
    return title, tags


_STOP = {"the", "a", "an", "on", "in", "of", "to", "and", "or", "for", "with", "at", "is", "by"}


def _keywords(text: str, limit: int = 6) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out: list[str] = []
    for w in words:
        if len(w) > 2 and w not in _STOP and w not in out:
            out.append(w)
        if len(out) >= limit:
            break
    return out


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        cand = path.with_name(f"{stem}-{n}{suffix}")
        if not cand.exists():
            return cand
        n += 1
