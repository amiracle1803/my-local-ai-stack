import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger("agent_atlas.db")

# database.py → storage/ → app/ → backend/ → agent-atlas/
DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "db" / "agent_atlas.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_profile (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS memory_projects (
    project_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_id, key)
);

CREATE TABLE IF NOT EXISTS memory_episodes (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_traces (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    agent_id TEXT NOT NULL,
    input_json TEXT,
    output_json TEXT,
    model_used TEXT,
    duration_ms REAL,
    success INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT,
    progress REAL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    room_id TEXT,
    conversation_id TEXT,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    role TEXT NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obsidian_notes (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT,
    tags TEXT,
    links TEXT,
    frontmatter_json TEXT,
    content_hash TEXT,
    indexed_at TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    logger.info("Initializing database at %s", DB_PATH)
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        # Additive migrations — safe to run on existing DBs
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
    logger.info("Database ready.")


def _migrate(conn: sqlite3.Connection):
    """Apply additive schema changes that are safe to run repeatedly."""
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    except Exception as exc:
        logger.error("DB migration: could not read jobs schema — skipping: %s", exc)
        return

    for col, ddl in [("notes", "TEXT"), ("title", "TEXT")]:
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
                logger.info("DB migration: added jobs.%s column", col)
            except Exception as exc:
                logger.error("DB migration: failed to add jobs.%s — %s", col, exc)
