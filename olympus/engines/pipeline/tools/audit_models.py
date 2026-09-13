#!/usr/bin/env python3
"""Audit local model files, workflow references, and optional checksums.

Read-only by default. It never downloads, upgrades, or deletes model files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while data := handle.read(chunk):
            digest.update(data)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("ComfyUI/models"))
    parser.add_argument("--workflow-root", type=Path, default=Path("olympus/engines/pipeline/workflows"))
    parser.add_argument("--hash", action="store_true")
    args = parser.parse_args()
    refs = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in args.workflow_root.glob("*.json"))
    rows = []
    for path in sorted(p for p in args.root.rglob("*") if p.is_file() and p.stat().st_size > 1_000_000):
        rows.append({
            "path": str(path), "bytes": path.stat().st_size,
            "referenced_by_workflow_name": path.name in refs,
            "sha256": sha256(path) if args.hash else None,
        })
    report = {"root": str(args.root), "files": rows, "count": len(rows)}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
