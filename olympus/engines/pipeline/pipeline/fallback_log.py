"""Structured provider fallback logging."""

from __future__ import annotations

import json
import time
from pathlib import Path


def record(project_dir: Path | None, capability: str, source: str, target: str, reason: str) -> None:
    root = Path(project_dir) if project_dir else Path.cwd()
    path = root / "logs" / "provider_fallbacks.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "ts": time.time(), "capability": capability,
            "source": source, "target": target, "reason": reason,
        }) + "\n")
