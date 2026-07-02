"""
obsidian_indexer.py  --  Walk the vault, embed notes (and PDFs), store
them in SQLite, and answer semantic search queries.

Indexing is incremental: each file's content hash is compared against
what's stored, so re-running only re-embeds what actually changed. Notes
whose files were deleted get pruned. If Ollama or the embedding model
isn't available, embed() returns None and search_notes() falls back to a
plain substring match instead of returning nothing.
"""

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.services.embeddings import cosine_similarity, embed
from app.services.pdf_ingest import extract_pdf_markdown
from app.storage.database import get_connection
from app.utils.ids import new_id, now_iso

logger = logging.getLogger("agent_atlas.obsidian_indexer")

DEFAULT_VAULT_PATH = "C:/Users/amire/Documents/Obsidian Vault"
_SKIP_PREFIXES = (".obsidian", ".trash", ".git", "_generated")

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def get_vault_path() -> Optional[Path]:
    raw = os.getenv("OBSIDIAN_VAULT_PATH", DEFAULT_VAULT_PATH)
    p = Path(raw)
    return p if p.exists() else None


def _parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:  # noqa: BLE001
        fm = {}
    return (fm if isinstance(fm, dict) else {}), content[m.end():]


def _extract_links(content: str) -> List[str]:
    return sorted(set(_WIKILINK_RE.findall(content)))


def _is_skipped(rel_parts: tuple[str, ...]) -> bool:
    return any(part in _SKIP_PREFIXES for part in rel_parts)


async def index_vault() -> int:
    vault = get_vault_path()
    if vault is None:
        logger.warning("OBSIDIAN_VAULT_PATH not set or doesn't exist -- skipping index")
        return 0

    indexed = 0
    pruned: List[str] = []
    seen_paths: set[str] = set()
    conn = get_connection()
    try:
        files = list(vault.rglob("*.md")) + list(vault.rglob("*.pdf"))
        for f in files:
            if _is_skipped(f.relative_to(vault).parts[:-1]):
                continue
            seen_paths.add(str(f))

            if f.suffix.lower() == ".pdf":
                body = extract_pdf_markdown(f) or ""
                frontmatter: Dict[str, Any] = {}
            else:
                raw = f.read_text(encoding="utf-8", errors="replace")
                frontmatter, body = _parse_frontmatter(raw)
            if not body.strip():
                continue

            content_hash = hashlib.md5(body.encode("utf-8")).hexdigest()
            row = conn.execute(
                "SELECT id, content_hash FROM obsidian_notes WHERE path = ?", (str(f),)
            ).fetchone()
            if row and row["content_hash"] == content_hash:
                continue  # unchanged since last index

            vector = await embed(body[:4000])
            tags = frontmatter.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            note_id = row["id"] if row else new_id()
            title = frontmatter.get("title") or f.stem

            conn.execute(
                """INSERT INTO obsidian_notes
                   (id, path, title, tags, links, frontmatter_json, content_hash,
                    snippet, embedding_json, indexed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET
                     title=excluded.title, tags=excluded.tags, links=excluded.links,
                     frontmatter_json=excluded.frontmatter_json,
                     content_hash=excluded.content_hash, snippet=excluded.snippet,
                     embedding_json=excluded.embedding_json, indexed_at=excluded.indexed_at""",
                (note_id, str(f), title, json.dumps(tags), json.dumps(_extract_links(body)),
                 json.dumps(frontmatter, default=str), content_hash, body[:300],
                 json.dumps(vector) if vector else None, now_iso()),
            )
            conn.commit()
            indexed += 1

        existing = [r["path"] for r in conn.execute("SELECT path FROM obsidian_notes").fetchall()]
        pruned = [p for p in existing if p not in seen_paths]
        for p in pruned:
            conn.execute("DELETE FROM obsidian_notes WHERE path = ?", (p,))
        if pruned:
            conn.commit()
    finally:
        conn.close()

    logger.info("Indexed %d changed note(s), pruned %d deleted", indexed, len(pruned))
    return indexed


async def search_notes(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    query_vec = await embed(query)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, path, title, snippet, embedding_json FROM obsidian_notes"
        ).fetchall()
    finally:
        conn.close()

    if query_vec is not None:
        scored = []
        for r in rows:
            if not r["embedding_json"]:
                continue
            score = cosine_similarity(query_vec, json.loads(r["embedding_json"]))
            scored.append((score, r))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {"id": r["id"], "path": r["path"], "title": r["title"],
                 "score": round(score, 4), "snippet": r["snippet"]}
                for score, r in scored[:top_k]
            ]

    # Fallback: no embeddings indexed yet, or Ollama unavailable right now.
    logger.warning("search_notes falling back to substring match (no embeddings available)")
    conn = get_connection()
    try:
        like = f"%{query}%"
        rows = conn.execute(
            "SELECT id, path, title, snippet FROM obsidian_notes "
            "WHERE title LIKE ? OR snippet LIKE ? LIMIT ?",
            (like, like, top_k),
        ).fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "path": r["path"], "title": r["title"], "score": 0.0,
             "snippet": r["snippet"]} for r in rows]


def append_to_note(rel_or_abs_path: str, content: str) -> bool:
    """Append text to a note. Refuses to write outside the vault."""
    vault = get_vault_path()
    if vault is None:
        return False
    target = Path(rel_or_abs_path)
    if not target.is_absolute():
        target = vault / target
    try:
        target.resolve().relative_to(vault.resolve())
    except ValueError:
        logger.warning("append_to_note refused: %s escapes the vault", target)
        return False
    if not target.exists():
        return False
    with open(target, "a", encoding="utf-8") as f:
        f.write(("\n" if not content.startswith("\n") else "") + content)
    return True
