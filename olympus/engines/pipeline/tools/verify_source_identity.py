#!/usr/bin/env python3
"""Verify that a project's staged script still matches its declared source."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    staged = args.project / "input" / "script.txt"
    if not staged.exists() or not args.source.exists():
        raise SystemExit("source and project input/script.txt are required")
    if digest(staged) != digest(args.source):
        print("FAIL: project input/script.txt does not match the requested source")
        return 1
    print(f"OK: source identity verified ({digest(args.source)[:16]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
