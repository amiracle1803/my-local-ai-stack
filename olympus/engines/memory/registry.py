"""SQLite registry mapping memories to provenance (user/project/agent/source/evidence).

Each memory stored in Qdrant gets a row here recording who/what/when/where it
came from, plus a confidence score and a link back to the original evidence.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_registry (
    memory_id   TEXT PRIMARY KEY,          -- Qdrant point id
    user_id     TEXT NOT NULL DEFAULT '',
    project_id  TEXT NOT NULL DEFAULT '',
    agent_id    TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',  -- file path / doc name / chat log
    memory      TEXT NOT NULL,             -- the extracted memory text
    confidence  REAL NOT NULL DEFAULT 1.0,
    evidence    TEXT NOT NULL DEFAULT '',  -- link / offset into source
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_user ON memory_registry(user_id);
CREATE INDEX IF NOT EXISTS idx_registry_project ON memory_registry(project_id);
CREATE INDEX IF NOT EXISTS idx_registry_agent ON memory_registry(agent_id);
CREATE INDEX IF NOT EXISTS idx_registry_source ON memory_registry(source);
"""


class MemoryRegistry:
    def __init__(self, db_path: str | Path = "memory_registry.db"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record(
        self,
        memory_id: str,
        memory: str,
        *,
        user_id: str = "",
        project_id: str = "",
        agent_id: str = "",
        source: str = "",
        confidence: float = 1.0,
        evidence: str = "",
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO memory_registry "
            "(memory_id, user_id, project_id, agent_id, source, memory, confidence, evidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (memory_id, user_id, project_id, agent_id, source, memory, confidence, evidence, _now()),
        )
        self._conn.commit()

    def query(self, **filters: str) -> list[dict[str, Any]]:
        where, params = [], []
        for col, val in filters.items():
            if val:
                where.append(f"{col} = ?")
                params.append(val)
        sql = "SELECT * FROM memory_registry"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def all(self) -> list[dict[str, Any]]:
        return self.query()

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM memory_registry").fetchone()
        return int(row["n"])