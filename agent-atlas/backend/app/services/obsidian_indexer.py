"""
Scans an Obsidian vault, extracts metadata, and indexes notes into SQLite + vector store.
"""
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.storage.database import get_connection
from app.services.vector_store import add_documents
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.obsidian")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def get_vault_path() -> Optional[Path]:
    raw = os.getenv("OBSIDIAN_VAULT_PATH", "")
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.exists() else None


def ensure_vault_structure() -> bool:
    """Create the Atlas folder structure inside the vault. Returns True if vault found."""
    path = get_vault_path()
    if not path:
        return False
    for sub in ("Atlas/Sessions", "Atlas/Projects", "Atlas/Profile", "Atlas/Knowledge"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    logger.info("Obsidian Atlas structure ready at: %s/Atlas/", path)
    return True


def append_daily_note(goal: str, response: str, route: str = "") -> bool:
    """Append a run entry to today's session log in Atlas/Sessions/YYYY-MM-DD.md."""
    from datetime import datetime
    path = get_vault_path()
    if not path:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    note_path = path / "Atlas" / "Sessions" / f"{today}.md"
    ts = datetime.now().strftime("%H:%M")
    header = f"# Agent Atlas — {today}\n\n" if not note_path.exists() else ""
    entry = (
        f"\n## {ts} · {route or 'run'}\n"
        f"**Goal:** {goal[:300]}\n\n"
        f"**Response:**\n{str(response)[:1500]}\n\n"
        "---\n"
    )
    try:
        with open(note_path, "a", encoding="utf-8") as f:
            f.write(header + entry)
        return True
    except Exception as exc:
        logger.warning("Failed to write daily note: %s", exc)
        return False


def _safe_filename(name: str) -> str:
    """Strip path separators and dangerous characters so a string is safe as a filename."""
    safe = re.sub(r"[^\w\s\-\.]", "_", name.replace("/", "_").replace("\\", "_"))
    return safe.strip("._") or "unknown"


def save_memory_fact(category: str, key: str, value: str) -> bool:
    """Upsert a fact line in Atlas/Profile/{category}.md."""
    path = get_vault_path()
    if not path:
        return False
    note_path = path / "Atlas" / "Profile" / f"{_safe_filename(category)}.md"
    try:
        existing = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        pattern = re.compile(rf"^\*\*{re.escape(key)}\*\*:.*$", re.MULTILINE)
        new_line = f"**{key}**: {value}"
        if pattern.search(existing):
            updated = pattern.sub(new_line, existing)
            note_path.write_text(updated, encoding="utf-8")
        else:
            with open(note_path, "a", encoding="utf-8") as f:
                if not existing:
                    f.write(f"# {category}\n\n")
                f.write(new_line + "\n")
        return True
    except Exception as exc:
        logger.warning("Failed to save memory fact: %s", exc)
        return False


def create_project_note(project_id: str, summary: str) -> bool:
    """Create/append to Atlas/Projects/{project_id}.md with a summary."""
    from datetime import datetime
    path = get_vault_path()
    if not path:
        return False
    note_path = path / "Atlas" / "Projects" / f"{_safe_filename(project_id)}.md"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"# Project: {project_id}\n\n" if not note_path.exists() else ""
    entry = f"\n### {ts}\n{summary}\n\n---\n"
    try:
        with open(note_path, "a", encoding="utf-8") as f:
            f.write(header + entry)
        return True
    except Exception as exc:
        logger.warning("Failed to write project note: %s", exc)
        return False


def _json_default(obj: Any) -> Any:
    """Convert types that json.dumps can't handle (e.g. datetime.date from PyYAML)."""
    import datetime
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=_json_default)


def _parse_frontmatter(content: str) -> Dict[str, Any]:
    try:
        import yaml
        m = FRONTMATTER_RE.match(content)
        if m:
            return yaml.safe_load(m.group(1)) or {}
    except Exception:
        pass
    return {}


def _extract_links(content: str) -> List[str]:
    return WIKILINK_RE.findall(content)


def index_vault(vault_path: Optional[Path] = None) -> int:
    path = vault_path or get_vault_path()
    if not path:
        logger.warning("OBSIDIAN_VAULT_PATH not set or does not exist — skipping vault index.")
        return 0

    logger.info("Indexing Obsidian vault: %s", path)
    conn = get_connection()
    count = 0
    docs_to_embed = []

    try:
        for md_file in path.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                content_hash = hashlib.md5(content.encode()).hexdigest()

                row = conn.execute(
                    "SELECT content_hash FROM obsidian_notes WHERE path = ?",
                    (str(md_file),),
                ).fetchone()
                if row and row["content_hash"] == content_hash:
                    continue  # unchanged

                fm = _parse_frontmatter(content)
                links = _extract_links(content)
                title = md_file.stem
                tags = fm.get("tags", [])
                if isinstance(tags, str):
                    tags = [tags]

                note_id = new_id()
                conn.execute(
                    """INSERT INTO obsidian_notes (id, path, title, tags, links, frontmatter_json, content_hash, indexed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(path) DO UPDATE SET
                         title=excluded.title, tags=excluded.tags, links=excluded.links,
                         frontmatter_json=excluded.frontmatter_json, content_hash=excluded.content_hash,
                         indexed_at=excluded.indexed_at""",
                    (
                        note_id,
                        str(md_file),
                        title,
                        _dumps(tags),
                        _dumps(links),
                        _dumps(fm),
                        content_hash,
                        now_iso(),
                    ),
                )
                docs_to_embed.append(
                    {"id": str(md_file), "text": content[:2000], "metadata": {
                        "title": title,
                        "tags": ", ".join(tags) if tags else "untagged",
                    }}
                )
                count += 1
            except Exception as exc:
                logger.error("Error indexing %s: %s", md_file, exc)

        conn.commit()
    finally:
        conn.close()

    if docs_to_embed:
        add_documents("obsidian", docs_to_embed)

    logger.info("Indexed %d new/changed notes.", count)
    return count


def search_notes(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    from app.services.vector_store import query as vec_query
    raw = vec_query("obsidian", query, top_k=top_k)
    # Normalize to the shape the frontend expects: id, path, title, score, snippet.
    # The vector store stores the file path as the document id.
    results = []
    for r in raw:
        meta = r.get("metadata") or {}
        results.append({
            "id": r.get("id", ""),
            "path": r.get("id", ""),          # id IS the absolute file path
            "title": meta.get("title", ""),
            "score": r.get("score", 0.0),
            "snippet": (r.get("text") or "")[:300] or None,
        })
    return results


def append_to_note(path: str, content: str) -> bool:
    vault = get_vault_path()
    # Require a configured vault — never allow arbitrary filesystem writes.
    if vault is None:
        logger.warning("append_to_note: no vault configured — write rejected.")
        return False
    p = Path(path)
    try:
        p.resolve().relative_to(vault.resolve())
    except ValueError:
        logger.warning("append_to_note: path '%s' is outside the vault — rejected.", path)
        return False
    if not p.exists():
        logger.warning("Note does not exist: %s", path)
        return False
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n" + content)
    return True
