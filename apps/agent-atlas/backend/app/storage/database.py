import sqlite3
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
DB_PATH = DATA_DIR / "db" / "agent_atlas.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    room_id TEXT,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    role TEXT NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    job_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obsidian_notes (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    links TEXT NOT NULL DEFAULT '[]',
    frontmatter_json TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT,
    snippet TEXT NOT NULL DEFAULT '',
    embedding_json TEXT,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_profile (
    user_id TEXT NOT NULL DEFAULT 'default',
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

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_messages_job_id ON messages(job_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a new connection. SQLite connections aren't safe to share across
    threads/async tasks, so call sites open, use, and close per-operation
    rather than holding one global connection."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return _connect(path)


def init_db(db_path: Optional[Path] = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
