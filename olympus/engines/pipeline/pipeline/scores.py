"""Persistent per-stage scorecards (design 5.2).

sqlite table ``scores(stage, unit, metric, value, ts, run_id)``. The stage
gate is structural, not honor-system: ``require_stage(N)`` refuses to let stage
N run unless the *previous* stage wrote its ``stage.done`` marker AND all of its
mandatory proof metrics exist. ``report()`` returns the full ledger.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .blueprint import STAGE_ORDER

# Sentinel row identifying a stage's "done" marker.
_STAGE_UNIT = "_stage"
_DONE_METRIC = "done"

# Mandatory proof metrics per stage (design 3.9 "proof metric" column). A stage
# that has not recorded these has not proven its improvement, so the next stage
# is blocked. Metric *names* are frozen here; the M1+ stage code records them.
MANDATORY_METRICS: dict[str, list[str]] = {
    "stage0": ["structure_completeness"],
    "stage1": ["bible_coverage"],
    "stage1r": ["refs_per_character"],
    "stage2": ["narration_avg_score"],
    "stage3": ["block_count"],
    "stage3b": ["prompt_adherence_avg"],
    "stage4": ["alignment_coverage"],
    "stage3c": ["lipsync_overlap_avg"],
    "stage5": ["av_sync_error_ms"],
}


class SkippedStageError(RuntimeError):
    """Raised when a stage is run before its predecessor is proven complete."""


class Scores:
    """Scorecard store backed by one sqlite file per project."""

    def __init__(self, db_path: str | Path, run_id: str | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or str(uuid.uuid4())
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scores (
                stage   TEXT NOT NULL,
                unit    TEXT NOT NULL,
                metric  TEXT NOT NULL,
                value   REAL,
                ts      TEXT NOT NULL,
                run_id  TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Scores":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- writing -------------------------------------------------------
    def record(self, stage: str, unit: str, metric: str, value: float) -> None:
        """Record one metric value for a unit (character/shot/block/...)."""
        self._conn.execute(
            "INSERT INTO scores (stage, unit, metric, value, ts, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (stage, unit, metric, float(value), _now_iso(), self.run_id),
        )
        self._conn.commit()

    def stage_done(self, stage: str) -> None:
        """Write the ``stage.done`` marker for ``stage``."""
        if stage not in STAGE_ORDER:
            raise ValueError(f"unknown stage: {stage!r}")
        self.record(stage, _STAGE_UNIT, _DONE_METRIC, 1.0)

    # ---- reading -------------------------------------------------------
    def is_done(self, stage: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM scores WHERE stage=? AND unit=? AND metric=? LIMIT 1",
            (stage, _STAGE_UNIT, _DONE_METRIC),
        )
        return cur.fetchone() is not None

    def has_metric(self, stage: str, metric: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM scores WHERE stage=? AND metric=? LIMIT 1",
            (stage, metric),
        )
        return cur.fetchone() is not None

    def missing_metrics(self, stage: str) -> list[str]:
        return [m for m in MANDATORY_METRICS.get(stage, []) if not self.has_metric(stage, m)]

    def metrics_for(self, stage: str) -> dict[str, float]:
        """Latest value per metric for a stage (excludes the done sentinel)."""
        cur = self._conn.execute(
            "SELECT metric, value FROM scores WHERE stage=? AND unit!=? ORDER BY ts",
            (stage, _STAGE_UNIT),
        )
        out: dict[str, float] = {}
        for metric, value in cur.fetchall():
            out[metric] = value
        return out

    # ---- gating (design 5.2) ------------------------------------------
    def require_stage(self, stage: str) -> None:
        """Raise :class:`SkippedStageError` unless the previous stage is proven
        complete (has ``stage.done`` AND all its mandatory metrics)."""
        if stage not in STAGE_ORDER:
            raise ValueError(f"unknown stage: {stage!r}")
        idx = STAGE_ORDER.index(stage)
        if idx == 0:
            return  # first stage has no predecessor
        prev = STAGE_ORDER[idx - 1]
        if not self.is_done(prev):
            raise SkippedStageError(
                f"cannot run {stage}: predecessor {prev} has no stage.done marker "
                f"(run {prev} first)."
            )
        missing = self.missing_metrics(prev)
        if missing:
            raise SkippedStageError(
                f"cannot run {stage}: predecessor {prev} is missing mandatory "
                f"metrics {missing}."
            )

    def report(self) -> dict:
        """Return the full ledger: per-stage done flag, metrics, gate status."""
        ledger: dict[str, dict] = {}
        for stage in STAGE_ORDER:
            missing = self.missing_metrics(stage)
            ledger[stage] = {
                "done": self.is_done(stage),
                "metrics": self.metrics_for(stage),
                "missing_metrics": missing,
                "complete": self.is_done(stage) and not missing,
            }
        return {"db": str(self.db_path), "run_id": self.run_id, "stages": ledger}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
