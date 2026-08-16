#!/usr/bin/env python3
"""
parse_mystic_eyes_story.py

Extract structured character prompts and arc metadata from the Mystic Eyes
story folder for automatic pipeline ingestion.

Inputs:
  Character apperence and description.txt
  Character list- guide.txt

Outputs:
  mystic_eyes_characters.json
    { "characters": [...], "arcs": [...] }

The JSON can be ingested by ComfyUI via a custom node or pre-processed
into CLIPTextEncode prompts for stages 0-3 conditioning.
"""

import re
import json
from pathlib import Path
from typing import List, Dict

STORY_ROOT = Path("/run/media/amire/c8b5a6cf-d6ff-4925-be6b-4a6e09dbcdea1/YouTube/Content Creation/Ai youtube story/Full ai video production/Mystic Eyes My Eyes Steal the Laws of Cultivation")
APPEARANCE_FILE = STORY_ROOT / "Character apperence and description.txt"
GUIDE_FILE = STORY_ROOT / "Character list- guide.txt"

def parse_appearance(path: Path) -> List[Dict]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    # Entries start with a name line, usually title-cased, followed by description lines until blank line or next name
    # Heuristic: lines that end with no comma and are short are headings
    entries = []
    current = None
    buffer = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if current:
                entries.append({"name": current, "description": " ".join(buffer).strip()})
                current = None
                buffer = []
            continue
        # New entry detection: starts with name and '(' or name alone, and next line is description
        # Detect pattern: Name with optional arc in parentheses
        # Many entries have no parenthesis for first line
        # We'll detect if line is short (<80 chars) and next line exists and doesn't start with lowercase
        # Simpler: if line matches pattern ^[A-Z][A-Za-z\s]+(?:\(.*\))?:?$
        if re.match(r'^[A-Z][A-Za-z\s\-]+(?:\(.*\))?:?$', line):
            if current:
                entries.append({"name": current, "description": " ".join(buffer).strip()})
            current = line.rstrip(':')
            buffer = []
        else:
            if current:
                buffer.append(line)
    if current:
        entries.append({"name": current, "description": " ".join(buffer).strip()})
    return entries

def parse_guide(path: Path) -> Dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    # Extract main character block and arcs
    chars = {}
    current_section = None
    for line in text.splitlines():
        if line.startswith("🌟") or line.startswith("👨‍👩‍👦") or line.startswith("⚔️") or line.startswith("🗺️") or line.startswith("🏙️") or line.startswith("🌍"):
            current_section = line.strip()
            continue
        m = re.match(r'^([A-Z][A-Za-z\s]+)$', line.strip())
        if m and len(line.strip()) < 50:
            name = m.group(1).strip()
            chars[name] = {"section": current_section}
    return chars

def build_prompts(entries: List[Dict]) -> List[Dict]:
    out = []
    for e in entries:
        name = e["name"]
        desc = e["description"]
        # Build Dashtoon-like prompt
        prompt = f"{desc}, Manhwa webtoon style, Korean comic art, consistent character appearance"
        out.append({
            "name": name,
            "description_raw": desc,
            "prompt": prompt
        })
    return out

def main():
    appearance = parse_appearance(APPEARANCE_FILE)
    guide = parse_guide(GUIDE_FILE)
    prompts = build_prompts(appearance)

    output = {
        "story_title": "Mystic Eyes My Eyes Steal the Laws of Cultivation",
        "author": "RogueArvy",
        "characters": prompts,
        "guide_sections": guide
    }
    out_path = STORY_ROOT / "mystic_eyes_characters.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Parsed {len(prompts)} character entries")
    print(f"Saved to {out_path}")
    # Preview first 3
    for p in prompts[:3]:
        print(f"- {p['name']}: {p['prompt'][:120]}...")

if __name__ == "__main__":
    main()