"""Persistent per-stage scorecards (sqlite).

Table ``scores(stage, unit, metric, value, ts, run_id)``. ``require_stage``
refuses to run a stage unless the previous stage wrote its done marker.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from .blueprint import STAGE_ORDER, now_iso

_STAGE_UNIT = "_stage"
_DONE_METRIC = "done"

MANDATORY_METRICS: dict[str, list[str]] = {
    "stage0": ["structure_completeness"],
    "stage0_dossier": ["characters_found"],
    "stage1": ["bible_coverage"],
    "stage1_world": ["world_coverage"],
    "stage1r": ["refs_per_character"],
    "stage3": ["block_count"],
    "stage2": ["story_beats"],
    "stage3b": ["panels_generated"],
    "stage4": ["alignment_coverage"],
    "stage3c": ["ltx_rendered"],
    "stage_vlm_review": ["review_coverage"],
    "stage5": ["av_sync_error_ms"],
}


class SkippedStageError(RuntimeError):
    """Raised when a stage runs before its predecessor is proven complete."""


class Scores:
    def __init__(self, db_path: str | Path, run_id: str | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or str(uuid.uuid4())
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS scores (
                stage TEXT NOT NULL, unit TEXT NOT NULL, metric TEXT NOT NULL,
                value REAL, ts TEXT NOT NULL, run_id TEXT NOT NULL)"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scores_stage_metric ON scores(stage, metric)"
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> "Scores":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def record(self, stage: str, unit: str, metric: str, value: float) -> None:
        self._conn.execute(
            "INSERT INTO scores (stage, unit, metric, value, ts, run_id) VALUES (?,?,?,?,?,?)",
            (stage, unit, metric, float(value), now_iso(), self.run_id),
        )
        self._conn.commit()

    def record_globals(self, stage: str, metrics: dict[str, float]) -> None:
        ts = now_iso()
        rows = [(stage, "global", m, float(v), ts, self.run_id) for m, v in metrics.items()]
        self._conn.executemany(
            "INSERT INTO scores (stage, unit, metric, value, ts, run_id) VALUES (?,?,?,?,?,?)", rows
        )
        self._conn.commit()

    def stage_done(self, stage: str) -> None:
        if stage not in STAGE_ORDER:
            raise ValueError(f"unknown stage: {stage!r}")
        self.record(stage, _STAGE_UNIT, _DONE_METRIC, 1.0)

    def is_done(self, stage: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM scores WHERE stage=? AND unit=? AND metric=? LIMIT 1",
            (stage, _STAGE_UNIT, _DONE_METRIC),
        )
        return cur.fetchone() is not None

    def has_metric(self, stage: str, metric: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM scores WHERE stage=? AND metric=? LIMIT 1", (stage, metric)
        )
        return cur.fetchone() is not None

    def metrics_for(self, stage: str) -> dict[str, float]:
        cur = self._conn.execute(
            "SELECT metric, value FROM scores WHERE stage=? AND unit='global' "
            "ORDER BY rowid DESC",
            (stage,),
        )
        out: dict[str, float] = {}
        for metric, value in cur.fetchall():
            out.setdefault(metric, float(value))
        return out

    def clear_stage(self, stage: str) -> None:
        self._conn.execute("DELETE FROM scores WHERE stage=?", (stage,))
        self._conn.commit()

    def require_stage(self, stage: str) -> None:
        """Block unless the previous stage in STAGE_ORDER is done."""
        if stage not in STAGE_ORDER:
            raise ValueError(f"unknown stage: {stage!r}")
        idx = STAGE_ORDER.index(stage)
        if idx == 0:
            return
        prev = STAGE_ORDER[idx - 1]
        if not self.is_done(prev):
            raise SkippedStageError(
                f"cannot run {stage}: previous stage {prev} is not done yet"
            )

    def report(self) -> dict:
        out: dict[str, dict] = {}
        for stage in STAGE_ORDER:
            metrics = self.metrics_for(stage)
            missing = [m for m in MANDATORY_METRICS.get(stage, []) if m not in metrics]
            out[stage] = {
                "done": self.is_done(stage),
                "complete": self.is_done(stage) and not missing,
                "metrics": metrics,
                "missing_metrics": missing,
            }
        return {"stages": out}
