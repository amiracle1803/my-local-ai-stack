"""
Exports key SQLite tables to JSONL files under data/exports/YYYY-MM-DD/.
Runs automatically once per day; can also be triggered via API.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("agent_atlas.backup")

EXPORTS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "exports"

TABLES = [
    "jobs",
    "messages",
    "agent_traces",
    "memory_profile",
    "memory_episodes",
    "memory_projects",
    "obsidian_notes",
    "metrics",
]

_task: asyncio.Task | None = None
_last_backup: str | None = None


def get_last_backup() -> str | None:
    return _last_backup


def run_backup() -> dict:
    """Export all tables to JSONL. Returns summary."""
    global _last_backup
    from app.storage.database import get_connection

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = EXPORTS_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    summary = {}
    try:
        for table in TABLES:
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
                out_file = out_dir / f"{table}.jsonl"
                with open(out_file, "w", encoding="utf-8") as f:
                    for row in rows:
                        f.write(json.dumps(dict(row)) + "\n")
                summary[table] = len(rows)
            except Exception as exc:
                logger.warning("Could not export table %s: %s", table, exc)
                summary[table] = -1
    finally:
        conn.close()

    _last_backup = datetime.now(timezone.utc).isoformat()
    logger.info("Backup complete → %s (%s)", out_dir, summary)
    return {"dir": str(out_dir), "tables": summary, "timestamp": _last_backup}


async def _backup_loop(interval_hours: float = 24.0):
    logger.info("DB backup scheduler started (every %sh)", interval_hours)
    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            await asyncio.to_thread(run_backup)
        except Exception as exc:
            logger.error("Scheduled backup failed: %s", exc)


def start_backup_scheduler():
    global _task
    _task = asyncio.create_task(_backup_loop())
    logger.info("DB backup scheduler running (daily).")


def stop_backup_scheduler():
    global _task
    if _task:
        _task.cancel()
        _task = None
