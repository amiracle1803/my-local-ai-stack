"""Task store (sqlite in data/) + background executor calling Ollama.

Task lifecycle: queued -> running -> done | failed. The API field for the
model's answer is `result` (NOT `output` — see olympus-instance-notes.md).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.request
from datetime import datetime, timezone

from .agents import Agent, AgentRegistry
from .config import DATA_DIR, load_config, resolve_model

DB_PATH = DATA_DIR / "olympus.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    text    TEXT NOT NULL,
    agent   TEXT NOT NULL,
    model   TEXT NOT NULL,
    status  TEXT NOT NULL DEFAULT 'queued',
    result  TEXT,
    error   TEXT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class TaskManager:
    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry
        DATA_DIR.mkdir(exist_ok=True)
        with _connect() as conn:
            conn.executescript(_SCHEMA)

    # -- persistence ---------------------------------------------------------

    def _insert(self, text: str, agent: Agent) -> int:
        model = resolve_model(agent.model)
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (text, agent, model, status, created, updated)"
                " VALUES (?, ?, ?, 'queued', ?, ?)",
                (text, agent.id, model, _now(), _now()),
            )
            return int(cur.lastrowid)

    def _update(self, tid: int, **fields) -> None:
        fields["updated"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with _connect() as conn:
            conn.execute(f"UPDATE tasks SET {cols} WHERE id = ?", (*fields.values(), tid))

    def get(self, tid: int) -> dict | None:
        with _connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 100) -> list[dict]:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- execution -----------------------------------------------------------

    def submit(self, text: str, agent_id: str | None = None) -> dict:
        agent = self.registry.get(agent_id) if agent_id else self.registry.route(text)
        if agent is None:
            raise LookupError(f"unknown agent: {agent_id!r}")
        tid = self._insert(text, agent)
        threading.Thread(target=self._run, args=(tid,), daemon=True).start()
        task = self.get(tid)
        assert task is not None
        return task

    def rerun(self, tid: int) -> dict:
        task = self.get(tid)
        if task is None:
            raise LookupError(f"no task {tid}")
        return self.submit(task["text"], task["agent"])

    def retry(self, tid: int) -> dict:
        task = self.get(tid)
        if task is None:
            raise LookupError(f"no task {tid}")
        if task["status"] != "failed":
            raise ValueError(f"task {tid} is '{task['status']}', only failed tasks can be retried")
        self._update(tid, status="queued", error=None)
        threading.Thread(target=self._run, args=(tid,), daemon=True).start()
        refreshed = self.get(tid)
        assert refreshed is not None
        return refreshed

    def _run(self, tid: int) -> None:
        task = self.get(tid)
        if task is None:
            return
        agent = self.registry.get(task["agent"])
        system_prompt = agent.system_prompt if agent else "You are a helpful assistant."
        self._update(tid, status="running")
        try:
            result = _ollama_chat(task["model"], system_prompt, task["text"])
            self._update(tid, status="done", result=result)
        except Exception as exc:  # surface the real error in the task record
            self._update(tid, status="failed", error=f"{type(exc).__name__}: {exc}")


def _ollama_chat(model: str, system: str, user: str) -> str:
    cfg = load_config()["ollama"]
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=cfg["timeout_seconds"]) as resp:
        body = json.load(resp)
    return body["message"]["content"]
