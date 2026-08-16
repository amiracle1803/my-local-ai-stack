#!/usr/bin/env python3
"""
reparse_mystic_eyes_corrected.py
Re-parse Character appearance file using blank-line blocks and filter noise.
"""

from pathlib import Path
import json

STORY_ROOT = Path("/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/Ai youtube story/Full ai video production/Mystic Eyes My Eyes Steal the Laws of Cultivation")
APPEARANCE_FILE = STORY_ROOT / "Character apperence and description.txt"

def parse_blocks(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    entries = []
    for b in blocks:
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        if not lines:
            continue
        name = lines[0]
        # filter noise
        if name.lower().startswith("perfect") or name.lower().startswith("your generation schedule"):
            continue
        # Skip if name is too long > 80 chars (likely description)
        if len(name) > 80:
            continue
        desc = " ".join(lines[1:])
        if not desc:
            continue
        entries.append({"name": name, "description": desc})
    return entries

entries = parse_blocks(APPEARANCE_FILE)
out_path = STORY_ROOT / "mystic_eyes_characters_v2.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"characters": entries}, f, indent=2, ensure_ascii=False)
print(f"Parsed {len(entries)} entries")
for e in entries:
    print("-", e["name"])