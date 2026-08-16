#!/usr/bin/env python3
"""
final_parse_mystic_eyes.py
Manually define known character names and extract descriptions by slicing file.
"""

from pathlib import Path
import json

STORY_ROOT = Path("/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/Ai youtube story/Full ai video production/Mystic Eyes My Eyes Steal the Laws of Cultivation")
APPEARANCE_FILE = STORY_ROOT / "Character apperence and description.txt"

KNOWN_NAMES = [
    "Kyrian (Early Arc — Royal Order)",
    "Kyrian (Wilderness Arc)",
    "Kyrian (Sect/Bloody Court Arc)",
    "Liora",
    "Rurik",
    "General Harken",
    "Kael",
    "Elyria",
    "Lina",
    "Wei Feng",
    "Mu Yanyu",
    "Old Wang",
    "Dong Zhen",
    "Bai Zhu",
    "Li Fen",
    "Yan Ling",
    "Kai",
    "Mei Li",
]

text = APPEARANCE_FILE.read_text(encoding="utf-8", errors="ignore")
entries = []
for i, name in enumerate(KNOWN_NAMES):
    start = text.find(name)
    if start == -1:
        continue
    # end is start of next name or end of file
    end = text.find(KNOWN_NAMES[i+1], start+1) if i+1 < len(KNOWN_NAMES) else -1
    block = text[start:end] if end != -1 else text[start:]
    # first line is name, rest is description
    lines = block.splitlines()
    desc = " ".join(l.strip() for l in lines[1:] if l.strip())
    entries.append({"name": name, "description": desc})

out = STORY_ROOT / "mystic_eyes_characters_final.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump({"characters": entries}, f, indent=2, ensure_ascii=False)
print(f"Saved {len(entries)} characters to {out}")
for e in entries:
    print("-", e["name"])