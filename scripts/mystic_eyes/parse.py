#!/usr/bin/env python3
"""
parse.py — extract character name/description entries from the Mystic Eyes
source text. Consolidates the three ad-hoc parsers that used to live as
separate root scripts into one module with selectable strategies.

Strategies:
  heuristic  — split on short title-cased "name" lines (parse_mystic_eyes_story)
  names      — slice the file at each known character name (final_parse)
  blocks     — split on blank-line blocks and filter noise (reparse_corrected)
"""

import re
import json
from typing import List, Dict

from . import config


def _read(path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_heuristic(text: str) -> List[Dict]:
    """Split on short title-cased heading lines; following lines are the body."""
    entries, current, buffer = [], None, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if current:
                entries.append({"name": current, "description": " ".join(buffer).strip()})
                current, buffer = None, []
            continue
        if re.match(r"^[A-Z][A-Za-z\s\-]+(?:\(.*\))?:?$", line):
            if current:
                entries.append({"name": current, "description": " ".join(buffer).strip()})
            current, buffer = line.rstrip(":"), []
        elif current:
            buffer.append(line)
    if current:
        entries.append({"name": current, "description": " ".join(buffer).strip()})
    return entries


def parse_by_names(text: str) -> List[Dict]:
    """Slice the file at each known name; the following block is its description."""
    entries = []
    names = config.KNOWN_NAMES
    for i, name in enumerate(names):
        start = text.find(name)
        if start == -1:
            continue
        end = text.find(names[i + 1], start + 1) if i + 1 < len(names) else -1
        block = text[start:end] if end != -1 else text[start:]
        lines = block.splitlines()
        desc = " ".join(l.strip() for l in lines[1:] if l.strip())
        entries.append({"name": name, "description": desc})
    return entries


def parse_blocks(text: str) -> List[Dict]:
    """Split on blank lines and drop noise headings / over-long names."""
    entries = []
    for b in text.split("\n\n"):
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        if not lines:
            continue
        name = lines[0]
        if name.lower().startswith(("perfect", "your generation schedule")) or len(name) > 80:
            continue
        desc = " ".join(lines[1:])
        if desc:
            entries.append({"name": name, "description": desc})
    return entries


# strategy → (parser, default output path)
STRATEGIES = {
    "heuristic": (parse_heuristic, config.CHARACTERS_JSON),
    "names": (parse_by_names, config.CHARACTERS_FINAL_JSON),
    "blocks": (parse_blocks, config.CHARACTERS_V2_JSON),
}


def parse(text: str, strategy: str = "blocks") -> List[Dict]:
    """Run the chosen strategy over `text` and return character entries."""
    try:
        parser, _ = STRATEGIES[strategy]
    except KeyError:
        raise ValueError(f"unknown strategy {strategy!r}; pick from {sorted(STRATEGIES)}")
    return parser(text)


def main(strategy: str = "blocks", output: str | None = None) -> int:
    """CLI entry: parse the appearance file and write the characters JSON."""
    parser, default_out = STRATEGIES[strategy]
    entries = parser(_read(config.APPEARANCE_FILE))
    out = (output or default_out) and (config.STORY_ROOT / output if output else default_out)
    out.write_text(json.dumps({"characters": entries}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Parsed {len(entries)} entries ({strategy}) -> {out}")
    for e in entries:
        print("-", e["name"])
    return 0
