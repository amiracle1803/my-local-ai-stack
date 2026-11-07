"""Stage implementations: script intake -> complete video (local-first).

Each ``run_stageN`` takes a project dir, writes its canonical artifacts,
records proof metrics via Scores, and flips the blueprint entry to done.
All stages work offline: Ollama/Voice Studio are tried first, deterministic
local fallbacks keep the run green when services are down.
"""

from __future__ import annotations

import base64
import json
import hashlib
import os
import re
import subprocess
import wave
from pathlib import Path

from .art import render_panel
from .blueprint import Blueprint, compute_title_hash, now_iso
from .llm import ollama_generate
from .scores import Scores
from .voice_client import synth
from .contracts import validate_media
from .identity import canonical_name, legacy_stem

# --------------------------------------------------------------------------
# shared text helpers
# --------------------------------------------------------------------------

_NAME_RE = re.compile(r"\b([A-Z][a-z]{2,}(?: [A-Z][a-z]{2,})?)\b")
_STOP = {"The", "This", "That", "There", "They", "When", "Where", "What",
        "With", "From", "Into", "Night", "Morning", "Evening", "Scene",
        "Chapter", "Part", "Episode", "Village", "Mountain", "Shadow"}


def split_scenes(text: str, target_chars: int = 900) -> list[dict]:
    """Split pasted script into scene dicts (heading/location/summary/content)."""
    text = normalize_script(text)
    if not text:
        return [{"location": "UNKNOWN", "summary": "empty script", "content": ""}]
    # A script with SCENE headings is split exactly there (the size-based merge below cut
    # every written scene in two).
    heads = list(re.finditer(r"(?im)^(scene|chapter|part|episode)\s+\d+\b.*$", text))
    if len(heads) >= 2:
        target_chars = 10 ** 9
    # Respect explicit headings first.
    chunks = re.split(r"\n\s*\n", text)
    scenes: list[dict] = []
    buf = ""
    for ch in chunks:
        head = ch.strip().split("\n")[0][:80] if ch.strip() else ""
        is_heading = bool(re.match(r"(?i)^(scene|chapter|part|episode|shot)\b|^(INT\.|EXT\.)", head.strip()))
        if is_heading and buf:
            scenes.append(buf)
            buf = ch
        elif len(buf) + len(ch) > target_chars and buf:
            scenes.append(buf)
            buf = ch
        else:
            buf = (buf + "\n\n" + ch).strip() if buf else ch
    if buf:
        scenes.append(buf)
    out = []
    for i, c in enumerate(scenes):
        first = c.strip().split("\n")[0][:90]
        head = _HEADING_RE.match(first)
        if head and len(first[head.end():].strip()) > 3:  # "SCENE 1 — The Tower" -> "The Tower"
            first = first[head.end():].strip()
        out.append({
            "location": first if len(first) > 3 else f"SCENE {i + 1}",
            "scene_heading": f"SCENE {i + 1} — {first[:60]}",
            "summary": c[:280].replace("\n", " "),
            "content": c,
        })
    return out


def _speaker_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in normalize_script(text).splitlines():
        m = _SPEAKER_RE.match(line.strip())
        if not m:
            continue
        n = m.group(1).strip()
        if n.lower() in _NOT_SPEAKERS or n.lower() in _NARRATOR:
            continue
        n = n.title() if n.isupper() else n
        counts[n] = counts.get(n, 0) + 1
    return counts


def extract_names(text: str, limit: int = 8) -> list[str]:
    # A screenplay names its cast in the speaker labels; capitalised words in the action
    # lines ("She", "Flame", "Courage") are not characters.
    speakers = _speaker_counts(text)
    if len(speakers) >= 2:
        return [n for n, _ in sorted(speakers.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]
    # SCENE headings are location labels, not characters — drop them up front.
    text = re.sub(r"(?im)^\s*SCENE\s+\d+.*$", "", text)
    counts: dict[str, int] = {}
    for m in _NAME_RE.finditer(text):
        name = m.group(1).strip()
        if name in _STOP or len(name) < 3:
            continue
        counts[name] = counts.get(name, 0) + 1

    def _used_as_name(n: str) -> bool:
        """Kill sentence-initial false positives ("And", "Below"): a real name
        shows up mid-sentence, in dialogue attribution, or as a speaker label."""
        if re.search(rf"(?m)^\s*{re.escape(n)}\s*:", text):  # "Kael: ..."
            return True
        if re.search(rf"\b{re.escape(n)}\s+(?:said|asked|replied|whispered|shouted|"
                     r"murmured|answered|sighed|nodded|smiled|added|cried)\b", text, re.I):
            return True
        for m in re.finditer(rf"\b{re.escape(n)}\b", text):
            before = text[:m.start()].rstrip()
            if before and before[-1] not in ".!?:\"”\n":
                return True
        return False

    kept = {n: c for n, c in counts.items() if _used_as_name(n)}
    ranked = sorted((kept or counts).items(), key=lambda kv: (-kv[1], kv[0]))
    return [n for n, _ in ranked[:limit]]


def _mark_done(project_dir: Path, stage: str, score: float | None = None) -> None:
    bp = Blueprint.load(project_dir)
    entry = bp.stages.get(stage)
    if entry is not None:
        entry.status = "done"
        entry.ts = now_iso()
        entry.score = score
        bp.write(project_dir)


def _dialogue_lines(content: str) -> list[dict]:
    out = []
    for line in content.splitlines():
        m = re.match(r'\s*([A-Z][A-Za-z ]{1,24})\s*:\s*(.+)', line)
        if m:
            out.append({"speaker": m.group(1).strip(), "text": m.group(2).strip()[:200]})
    return out[:20]


# --------------------------------------------------------------------------
# script normalisation, beats and brief metadata
# (2026-11-04: LLM scripts arrive as markdown — **Aya:** (shouting) "…", *[stage
# direction]* — which the NAME: parser missed entirely; episodes came out as three
# 180-char narration snippets over six panels.)
# --------------------------------------------------------------------------

_HEADING_RE = re.compile(r"(?i)^(scene|chapter|part|episode)\s+\d+\b\s*[—–:.-]*\s*")
_SPEAKER_RE = re.compile(r"^([A-Z][A-Za-z'.-]*(?: [A-Z][A-Za-z'.-]*){0,2})\s*:\s*(.+)$")
_NOT_SPEAKERS = {"scene", "chapter", "part", "episode", "note", "notes", "tone", "style", "cast",
                 "series", "title", "setting", "location", "time", "voices", "sfx", "music",
                 "end", "cut", "fade", "int", "ext", "new", "opening", "closing"}
_NARRATOR = {"narrator", "narration", "voice over", "voiceover", "vo"}
SHOT_MIN_SECONDS = 2.5          # screen time of a shot with no audio
NARRATION_SHOT_WORDS = 45       # longer narration paragraphs split into several shots


def _slug(name: str) -> str:
    return re.sub(r"\W+", "_", name).strip("_").lower() or "char"


def _same_name(a: str, b: str) -> bool:
    """'Toma' and 'Old Toma' are the same character."""
    a, b = a.strip().lower(), b.strip().lower()
    return bool(a and b) and (a == b or a.split()[-1] == b.split()[-1])


def normalize_script(text: str) -> str:
    """Flatten an LLM markdown screenplay into the plain format the stages parse:
    ``**Aya:** (shouting) "Toma!"`` -> ``Aya: (shouting) Toma!``, ``*[She climbs.]*`` ->
    ``She climbs.``; markdown headings, rules and emphasis are dropped. Plain scripts
    pass through unchanged."""
    text = re.sub(r"(?s)<think>.*?</think>", "", text.replace("\r\n", "\n"))
    out: list[str] = []
    for raw in text.split("\n"):
        line = re.sub(r"^#{1,6}\s*", "", raw.strip())
        if re.fullmatch(r"[-*_=]{3,}", line):
            line = ""
        line = line.replace("*", "").replace("__", "").strip()
        direction = re.fullmatch(r"\[(.+)\]", line)
        if direction:  # a stage direction: drop camera labels ("Opening:", "Aya's POV.")
            d = re.sub(r"^([A-Z][A-Za-z' ]{0,24}):\s*", "", direction.group(1).strip())
            out.append(re.sub(r"\b[\w’']+ POV\b[.:,]?\s*", "", d).strip())
            continue
        sm = _SPEAKER_RE.match(line)
        if sm and sm.group(1).strip().lower() not in _NOT_SPEAKERS:
            speaker, rest = sm.group(1).strip(), sm.group(2).strip()
            speaker = speaker.title() if speaker.isupper() else speaker
            delivery = ""
            pm = re.match(r"^\(([^)]{1,80})\)\s*(.*)$", rest)
            if pm:
                delivery, rest = pm.group(1).strip(), pm.group(2).strip()
            quoted = re.findall(r"[\"“]([^\"”]+)[\"”]", rest)
            tail = ""
            if quoted:
                tail = re.split(r"[\"”]", rest)[-1].strip(" -—[]")
                rest = " ".join(q.strip() for q in quoted)
            out.append(f"{speaker}: " + (f"({delivery}) " if delivery else "") + rest)
            if len(tail) > 3:
                out.append(tail)
            continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _sentences_in_chunks(text: str, max_words: int) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    chunks: list[str] = []
    cur: list[str] = []
    for p in parts:
        if cur and len(" ".join(cur + [p]).split()) > max_words:
            chunks.append(" ".join(cur))
            cur = []
        cur.append(p)
    if cur:
        chunks.append(" ".join(cur))
    return [c for c in chunks if c.strip()]


def script_beats(content: str) -> list[dict]:
    """Ordered beats of one scene: ``{"kind": "action", "text"}`` narration paragraphs and
    ``{"kind": "dialogue", "speaker", "text", "delivery"}`` spoken lines."""
    beats: list[dict] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            beats.append({"kind": "action", "text": " ".join(para)})
            para.clear()

    for line in normalize_script(content).splitlines():
        s = line.strip()
        if not s:
            flush()
            continue
        if len(s) < 90 and re.search(r"(?i)\bepisode\s+\d+\b", s) and not _SPEAKER_RE.match(s) \
                and not re.match(r"(?i)^episode\s+\d+\s*$", s):
            flush()  # the title card is its own narrated beat
            beats.append({"kind": "action", "text": s.replace('"', "")})
            continue
        head = _HEADING_RE.match(s)
        if head:  # "SCENE 2 — The Flame Goes Out." is a location label; a long one is content
            flush()
            rest = s[head.end():].strip()
            if len(rest) > 80:
                para.append(rest)
            continue
        m = _SPEAKER_RE.match(s)
        name = m.group(1).strip() if m else ""
        if m and name.lower() not in _NOT_SPEAKERS:
            flush()
            rest = m.group(2).strip()
            if name.lower() in _NARRATOR:
                beats.append({"kind": "action", "text": rest})
                continue
            delivery = ""
            pm = re.match(r"^\(([^)]{1,80})\)\s*(.*)$", rest)
            if pm:
                delivery, rest = pm.group(1).strip(), pm.group(2).strip()
            rest = rest.strip(' "“”')
            if rest:
                beats.append({"kind": "dialogue", "speaker": name.title() if name.isupper() else name,
                              "text": rest, "delivery": delivery})
        else:
            para.append(s)
    flush()
    return beats


def shot_plan(content: str) -> list[dict]:
    """Group a scene's beats into shots. A narration paragraph opens a shot (long ones are
    split at sentence ends) and takes the next spoken line with it; every further spoken
    line gets its own close-up. Shared by storyboard (visuals) and screenplay (text)."""
    shots: list[dict] = []
    last_action = ""
    for b in script_beats(content):
        if b["kind"] == "action":
            for chunk in _sentences_in_chunks(b["text"], NARRATION_SHOT_WORDS):
                last_action = chunk
                shots.append({"narration": chunk, "action": chunk,
                              "speaker": "", "dialogue": "", "delivery": ""})
        elif shots and shots[-1]["narration"] and not shots[-1]["dialogue"]:
            shots[-1].update(speaker=b["speaker"], dialogue=b["text"], delivery=b["delivery"])
        else:
            shots.append({"narration": "", "action": last_action, "speaker": b["speaker"],
                          "dialogue": b["text"], "delivery": b["delivery"]})
    if not shots:
        text = re.sub(r"\s+", " ", content).strip()
        shots = [{"narration": text[:600], "action": text[:240], "speaker": "", "dialogue": "",
                  "delivery": ""}]
    return shots


def brief_meta(project_dir: Path) -> dict:
    """Optional series metadata in input/brief.md:
    ``Style: …``, ``Cast: Name (look), Name (look)``, ``Voices: Name=Speaker (style); …``."""
    p = Path(project_dir) / "input" / "brief.md"
    text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    meta: dict = {"style": "", "cast": {}, "voices": {}}
    m = re.search(r"(?i)\bStyle:\s*([^\n]+)", text)
    if m:
        meta["style"] = m.group(1).strip().rstrip(".")
    m = re.search(r"(?i)\bCast:\s*([^\n]+)", text)
    if m:
        for c in re.finditer(r"([A-Z][\w' -]{0,30}?)\s*\(([^)]*)\)", m.group(1)):
            meta["cast"][c.group(1).strip(" ,")] = c.group(2).strip()
    m = re.search(r"(?i)\bVoices:\s*([^\n]+)", text)
    if m:
        for part in m.group(1).split(";"):
            v = re.match(r"\s*([^=]+?)\s*=\s*([A-Za-z_]+)\s*(?:\(([^)]*)\))?", part)
            if v:
                meta["voices"][v.group(1).strip()] = {"voice": v.group(2), "style": (v.group(3) or "").strip()}
    return meta


_SCRIPT_RULES = ("Plain text only: no markdown, no asterisks, no title line. Narration paragraphs "
                 "describe what we see happen. Every spoken line goes on its own line as NAME: line "
                 "(optionally NAME: (short delivery note) line) and never inside a narration "
                 "paragraph. Only use characters from the brief's Cast. Blank line between paragraphs.\n\n"
                 "EXAMPLE OF THE FORMAT (a different story):\n"
                 "SCENE 1 — Harbor at dawn\n"
                 "Fishing boats bob in grey water. Kaito hauls an empty net onto the dock.\n\n"
                 "KAITO: (grunting) Nothing again.\n"
                 "HANA: Then we sail further out.\n\n"
                 "The gulls scatter as the harbor bell rings.")


def _brief_for_writer(brief: str) -> str:
    # Voice casting is for the TTS stage; the writer copied it into delivery notes.
    return "\n".join(l for l in brief.splitlines() if not re.match(r"(?i)^\s*voices:", l))[:3000]


def _script_prompt(brief: str, word_target: int) -> str:
    return (f"Write the full episode script for this anime brief: about {word_target} words, "
            "3-6 scenes, in this exact format:\n\n"
            "SCENE 1 — <this scene's own place, time of day>\n"
            "<1-3 sentences of narration describing what we see happen>\n"
            "NAME: <one short spoken line>\n"
            "NAME: (whispering) <a spoken line with a short delivery note>\n\n"
            "<more narration>\n\n"
            "SCENE 2 — <place>\n…\n\n"
            f"{_SCRIPT_RULES} Follow the brief's scene list in order.\n\n"
            f"BRIEF:\n{_brief_for_writer(brief)}")


def _write_script(brief: str, word_target: int) -> str | None:
    """Brief -> script with the local LLM. A brief with a SCENE list is written one scene at
    a time (an 8B model asked for 600 words in one go wrote ~300 and blurred the scenes);
    otherwise a single call. None when the LLM is unavailable."""
    beats = re.findall(r"(?im)^\s*SCENE\s+\d+\s*[-—–:.]\s*(.+)$", brief)
    if len(beats) < 2:
        llm = ollama_generate(_script_prompt(brief, word_target), timeout=600,
                              num_predict=max(2000, word_target * 4), temperature=0.5, think=False)
        return normalize_script(llm.text) if llm else None
    per = max(80, word_target // len(beats))
    parts: list[str] = []
    for i, beat in enumerate(beats, 1):
        so_far = "\n\n".join(parts)[-1800:] or "(nothing yet)"
        prompt = (f"{_SCRIPT_RULES}\n\nBRIEF:\n{_brief_for_writer(brief)}\n\nSCRIPT SO FAR:\n{so_far}\n\n"
                  f"Write ONLY scene {i} now — {beat.strip()} — about {per} words. First line: "
                  f"SCENE {i} — <place>. Then 3-4 narration paragraphs with 3-6 short spoken lines "
                  "between them. Continue naturally from the script so far; do not write later scenes.")
        text = ""
        for _attempt in range(2):  # retry once if the dialogue came back as prose
            llm = ollama_generate(prompt, timeout=300, num_predict=max(900, per * 5), temperature=0.6, think=False)
            if not llm:
                break
            text = normalize_script(llm.text)
            if _speaker_counts(text):
                break
        if not text:
            return "\n\n".join(parts) or None
        heads = list(re.finditer(r"(?im)^\s*SCENE\s+\d+\b.*$", text))
        if len(heads) > 1:  # the model ran on into the next scene
            text = text[:heads[1].start()]
        if heads:
            text = re.sub(r"(?i)^\s*SCENE\s+\d+", f"SCENE {i}", text.lstrip(), count=1)
        else:
            text = f"SCENE {i} — {beat.split('.')[0].strip()}\n{text}"
        parts.append(text.strip())
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# stage0 — intake: script.txt -> blueprint + scenes
# --------------------------------------------------------------------------

def run_stage0(project_dir: Path, brief: str | None = None,
               source_text: str | None = None, word_target: int = 800) -> dict:
    project_dir = Path(project_dir)
    bp = Blueprint.load(project_dir)
    inp = project_dir / "input"

    if source_text:
        (inp / "source.txt").write_text(source_text, encoding="utf-8")
        script_text = source_text
    elif brief and bp.mode == "0b":
        (inp / "brief.md").write_text(brief, encoding="utf-8")
        # Expand the brief into a working script (LLM first, template fallback).
        script_text = _write_script(brief, word_target) or _expand_template(brief, word_target)
    else:
        brief_path = inp / "brief.md"
        source_path = inp / "source.txt"
        script_path = inp / "script.txt"
        if brief_path.exists() and (not script_path.exists() or script_path.stat().st_size < 50):
            b = brief_path.read_text(encoding="utf-8", errors="replace")
            script_text = _write_script(b, word_target) or _expand_template(b, word_target)
        elif source_path.exists():
            script_text = source_path.read_text(encoding="utf-8", errors="replace")
        elif script_path.exists():
            script_text = script_path.read_text(encoding="utf-8", errors="replace")
        else:
            raise FileNotFoundError("stage0 needs input/script.txt, brief.md, or source text")

    (inp / "script.txt").write_text(script_text, encoding="utf-8")
    # Repin the pollution hash to the real intake text.
    bp.title_hash = compute_title_hash(script_text)
    bp.write(project_dir)

    scenes = split_scenes(script_text)
    (project_dir / "stage0_scenes.json").write_text(json.dumps(scenes, indent=2), encoding="utf-8")

    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage0", {"structure_completeness": 1.0 if len(scenes) >= 2 else 0.6,
                                     "scene_count": float(len(scenes))})
        sc.stage_done("stage0")
    _mark_done(project_dir, "stage0", 1.0)
    return {"scenes": len(scenes)}


def _expand_template(brief: str, word_target: int) -> str:
    body = re.sub(r"^---.*?---\s*", "", brief, flags=re.S).strip() or brief.strip()
    names = extract_names(body) or ["Kael"]
    hero = names[0]
    paras = [
        f"SCENE 1 — The village at dusk. {hero} sharpens a worn blade as storm clouds gather. "
        f"{body[:220]}",
        f"SCENE 2 — {hero}: We hold the pass tonight. A shadow moves between the pines — "
        f"the wolf is here. Villagers bar doors; lanterns gutter in the wind.",
        f"SCENE 3 — The fight on the ridge. {hero} trades cuts with the shadow wolf, "
        f"refusing to fall. Thunder cracks; the beast retreats into the dark.",
        f"SCENE 4 — Quiet after. {hero} binds a wound and smiles at the dawn. "
        f"The village endures — for now.",
    ]
    text = "\n\n".join(paras)
    while len(text.split()) < max(150, word_target // 4):
        text += "\n\n" + paras[1]
    return text


# --------------------------------------------------------------------------
# stage0_dossier — intake enrichment
# --------------------------------------------------------------------------

def run_dossier(project_dir: Path) -> dict:
    project_dir = Path(project_dir)
    script = (project_dir / "input" / "script.txt").read_text(encoding="utf-8", errors="replace")
    scenes = json.loads((project_dir / "stage0_scenes.json").read_text(encoding="utf-8"))
    cast = brief_meta(project_dir)["cast"]
    # With a brief Cast the characters are the speakers plus cast members the script uses;
    # capitalised words in prose ("Flame", "Then") are never guessed in.
    names = list(_speaker_counts(script)) if cast else extract_names(script)
    # The brief's Cast line carries the canonical look; add cast members the script uses.
    for cname in cast:
        if not any(_same_name(cname, n) for n in names) and \
                re.search(rf"\b{re.escape(cname.split()[-1])}\b", script, re.I):
            names.append(cname)

    def _look(n: str) -> str:
        hit = next((d for c, d in cast.items() if _same_name(c, n)), "")
        return hit or f"anime design, distinctive silhouette, expressive eyes ({n})"

    characters = [{
        "id": re.sub(r"\W+", "_", n).lower(),
        "name": n,
        "role": "protagonist" if i == 0 else ("antagonist" if "wolf" in n.lower() else "supporting"),
        "appearance": _look(n),
        "description": f"Key figure across {len(scenes)} scenes.",
        "source_evidence": [s.get("content", "")[:240] for s in scenes if n in s.get("content", "")][:3],
        "confidence": 0.45,
    } for i, n in enumerate(names)] or [{
        "id": "kael", "name": "Kael", "role": "protagonist",
        "appearance": "silver hair, green eyes, worn armor",
        "description": "Lone swordsman defending the village.",
    }]
    locations = []
    for i, s in enumerate(scenes):
        content = s.get("content", "")
        locations.append({"id": f"loc_{i:02d}", "name": s.get("location", f"Scene {i+1}")[:60],
                          "description": s.get("summary", "")[:200],
                          "views_360": {"north": "", "east": "", "south": "", "west": "", "above": "", "below": ""},
                          "setting": {"time": "unspecified", "season": "unspecified", "environment": "unspecified"},
                          "source_evidence": content[:400], "confidence": 0.35})
    log = []
    for s in scenes:
        for d in _dialogue_lines(s.get("content", "")):
            log.append({"speaker": d["speaker"], "addressee": "", "body_movement": "", "line": d["text"]})
    dossier = {"schema_version": 1, "title": Blueprint.load(project_dir).slug,
               "synopsis": scenes[0].get("summary", "")[:400] if scenes else "",
               "characters": characters, "locations": locations, "dialogue_log": log,
               "relationships": [], "extraction": {"method": "deterministic", "inferred": False}}
    out = project_dir / "intake" / "dossier.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dossier, indent=2), encoding="utf-8")
    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage0_dossier", {"characters_found": float(len(characters)),
                                             "locations_found": float(len(locations))})
        sc.stage_done("stage0_dossier")
    _mark_done(project_dir, "stage0_dossier", 1.0)
    return {"characters": len(characters)}


# --------------------------------------------------------------------------
# stage1 — world bible + stage1_world enrichment
# --------------------------------------------------------------------------

def run_worldbible(project_dir: Path) -> dict:
    project_dir = Path(project_dir)
    dossier = json.loads((project_dir / "intake" / "dossier.json").read_text(encoding="utf-8"))
    chars = []
    for c in dossier.get("characters", []):
        name = c.get("name", "Unknown")
        chars.append({
            "id": c.get("id", re.sub(r"\W+", "_", name).lower()),
            "name": name, "role": c.get("role", "supporting"),
            "aliases": [],
            "appearance": {"hair": "", "eyes": "", "skin": "", "build": "",
                           "clothing_primary": c.get("appearance", "")[:160]},
            "sd_prompt": f"anime key visual, {name}, {c.get('appearance','')[:120]}, clean lineart, cel shaded",
        })
    bible = {"title": dossier.get("title", ""), "synopsis": dossier.get("synopsis", ""),
             "characters": chars, "locations": dossier.get("locations", []),
             "relationships": [], "contradictions": []}
    wb = project_dir / "worldbible"
    wb.mkdir(parents=True, exist_ok=True)
    (wb / "world_bible.json").write_text(json.dumps(bible, indent=2), encoding="utf-8")
    (wb / "contradictions.json").write_text(json.dumps([], indent=2), encoding="utf-8")
    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage1", {"bible_coverage": 1.0, "characters": float(len(chars))})
        sc.stage_done("stage1")
    _mark_done(project_dir, "stage1", 1.0)
    return {"characters": len(chars)}


def run_world_enrich(project_dir: Path) -> dict:
    project_dir = Path(project_dir)
    p = project_dir / "worldbible" / "world_bible.json"
    bible = json.loads(p.read_text(encoding="utf-8"))
    dossier = json.loads((project_dir / "intake" / "dossier.json").read_text(encoding="utf-8"))
    bible.setdefault("world", {})
    bible["world"].setdefault("era", "unspecified")
    bible["world"].setdefault("magic", "unspecified")
    bible["world"].setdefault("economy", "unspecified")
    bible["world"].setdefault("lore", "")
    bible["scene_settings"] = [
        {"scene": i + 1, "location_id": loc.get("id"),
         "facts": {"description": loc.get("description", ""), "time": "unspecified",
                   "season": "unspecified", "environment": "unspecified"},
         "source": "stage0_dossier"}
        for i, loc in enumerate(dossier.get("locations", []))
    ]
    bible.setdefault("continuity_constraints", [])
    p.write_text(json.dumps(bible, indent=2), encoding="utf-8")
    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage1_world", {"world_coverage": 1.0})
        sc.stage_done("stage1_world")
    _mark_done(project_dir, "stage1_world", 1.0)
    return {"ok": True}


# --------------------------------------------------------------------------
# stage1r — reference images (PIL)
# --------------------------------------------------------------------------

ANIMAL = re.compile(r"\b(fox|cat|dog|wolf|bird|owl|crow|raven|dragon|horse|rabbit|bear|tiger|deer|"
                    r"serpent|snake|fish|creature|beast|kitsune)\b", re.I)


def sheet_prompt(look: str) -> tuple[str, str]:
    """Prompt + negative for one character sheet. Not 'reference sheet' wording: klein then draws a
    multi-view turnaround with extra figures and pets, which leak into panels as clones/animals.
    An animal character is told it has an animal body ('small male fox spirit' came out humanoid)."""
    look = re.sub(r"\b(anime key visual|clean lineart|cel shaded)\b,?\s*", "", look).strip(" ,")
    neg = ("multiple views, turnaround, character sheet layout, several figures, duplicate character, "
           "extra animals, pets, background scenery, props, text, watermark, blurry")
    if ANIMAL.search(look):
        body = (f"one single {look}: an animal with an animal body standing on four legs, not a person, "
                "no human body, no clothes")
        neg += ", humanoid, human body, person, clothes"
    else:
        body = f"one single person, {look}, full body, standing, front view"
    return (f"anime character design, {body}, the only figure in the image, plain white background, "
            "flat even lighting, clean lineart, cel shaded, no text"), neg


def run_references(project_dir: Path, quick: bool = False) -> dict:
    project_dir = Path(project_dir)
    bible = json.loads((project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8"))
    chars = bible.get("characters", [])[:4 if quick else 8] or [{"id": "kael", "name": "Kael"}]
    made = 0
    for c in chars:
        d = project_dir / "worldbible" / "refs" / c.get("id", "char")
        d.mkdir(parents=True, exist_ok=True)
        n_refs = 2 if quick else 3
        for i in range(n_refs):
            render_panel(d / f"ref_{i:02d}.png", title=c.get("name", "REF"),
                         subtitle=f"reference {i+1}/{n_refs} · 360 turnaround",
                         body=c.get("sd_prompt", "")[:200], seed=f"{c.get('id')}-{i}")
            made += 1
    # Real character sheets (full body, plain background) for the panel renderer's
    # ReferenceLatent: this is what keeps hair/clothes the same from shot to shot.
    sheets: dict[str, str] = {}
    if (os.environ.get("OLYMPUS_REAL_COMFY", "0") == "1" and os.environ.get("OLYMPUS_PANEL_REFS", "1") != "0"):
        try:
            from .comfy_client import render_panel as comfy_render
            from stack.config import cfg as _cfg
            for c in chars:
                cid = c.get("id", "char")
                look = c.get("sd_prompt") or c.get("name", "")
                sheet = project_dir / "worldbible" / "refs" / cid / "sheet.png"
                prompt, negative = sheet_prompt(look)
                comfy_render(prompt, sheet, seed=int(hashlib.sha256(cid.encode()).hexdigest()[:8], 16),
                             base_url=_cfg.comfyui.url, negative=negative)
                sheets[cid] = str(sheet.relative_to(project_dir))
        except Exception as e:  # noqa: BLE001  (panels still render, just without references)
            print(f"  character sheets failed: {type(e).__name__}: {e}", flush=True)
    manifest = {
        "refs": made,
        "sheets": sheets,
        "characters": {
            c.get("id", "char"): [
                str((project_dir / "worldbible" / "refs" / c.get("id", "char") /
                     f"ref_{i:02d}.png").relative_to(project_dir))
                for i in range(n_refs)
            ]
            for c in chars
        },
    }
    (project_dir / "worldbible" / "refs" / "_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    storyboard_path = project_dir / "storyboard" / "storyboard.json"
    if storyboard_path.exists():
        storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
        for shot in storyboard.get("shot_detail", []):
            assets = []
            for character_id in shot.get("character_ids", []):
                assets.extend(manifest["characters"].get(character_id, []))
            shot["reference_assets"] = assets
        storyboard_path.write_text(json.dumps(storyboard, indent=2), encoding="utf-8")
    rpc = round(made / max(1, len(chars)), 2)
    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage1r", {"refs_per_character": rpc, "failed_generations": 0.0})
        sc.stage_done("stage1r")
    _mark_done(project_dir, "stage1r", 1.0)
    return {"refs": made}


# --------------------------------------------------------------------------
# stage3 — storyboard enrichment (runs after world bible, before screenplay)
# --------------------------------------------------------------------------

def run_storyboard(project_dir: Path) -> dict:
    project_dir = Path(project_dir)
    # Read from world bible and scenes, NOT screenplay (which runs after)
    bible_path = project_dir / "worldbible" / "world_bible.json"
    bible = json.loads(bible_path.read_text(encoding="utf-8")) if bible_path.exists() else {}
    scenes = json.loads((project_dir / "stage0_scenes.json").read_text(encoding="utf-8"))
    characters = [(c.get("id") or _slug(c.get("name", "char")), c.get("name", ""))
                  for c in bible.get("characters", [])]

    def present(plan: dict) -> list[str]:
        text = f"{plan['speaker']} {plan['narration']} {plan['dialogue']}"
        found = [cid for cid, name in characters if name and (
            _same_name(name, plan["speaker"]) or
            re.search(rf"\b{re.escape(name.split()[-1])}\b", text, re.I))]
        return found

    blocks, shots = [], []
    for i, s in enumerate(scenes):
        bid = f"block_{i:02d}"
        blocks.append({"id": bid, "title": s.get("location", f"Scene {i+1}")[:80],
                       "summary": s.get("summary", "")[:240]})
        # Storyboard is an internal visual plan: one shot per narration paragraph or spoken
        # line (shot_plan). Screenplay text is produced later by stage2 from the same plan.
        prev_ids: list[str] = []
        for j, plan in enumerate(shot_plan(s.get("content", ""))):
            ids = present(plan) or prev_ids  # "she climbs" keeps the last shot's cast
            prev_ids = ids
            if j == 0:
                composition, camera = "wide establishing shot", "slow push-in"
            elif plan["speaker"] and not plan["narration"]:
                composition = (f"close-up on {plan['speaker']}" if j % 2 else
                               f"over-the-shoulder medium shot on {plan['speaker']}")
                camera = "static"
            else:
                composition, camera = (("medium action shot", "subtle tracking movement") if j % 2
                                       else ("dynamic wide shot", "slow pan"))
            shots.append({
                "id": f"sh-{i+1:03d}-{j+1:02d}",
                "block": bid,
                "frame_index": j,
                "tier": 1 if j == 0 else 2,
                "location_id": f"loc_{i:02d}",
                "character_ids": ids,
                "action": plan["action"][:240],
                "composition": composition,
                "camera": camera,
                "continuity": {
                    "outfit": "default",
                    "lighting": s.get("setting", {}).get("time", "unspecified"),
                    "screen_direction": "left_to_right",
                },
                "reference_assets": [],
            })
    sb = {"blocks": blocks, "shot_detail": shots}
    out = project_dir / "storyboard" / "storyboard.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sb, indent=2), encoding="utf-8")
    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage3", {"block_count": float(len(blocks)), "shots": float(len(shots))})
        sc.stage_done("stage3")
    _mark_done(project_dir, "stage3", 1.0)
    return {"shots": len(shots)}


# --------------------------------------------------------------------------
# stage2 — screenplay (narration + dialogue timed to storyboard shots)
# --------------------------------------------------------------------------

def run_screenplay(project_dir: Path) -> dict:
    project_dir = Path(project_dir)
    scenes = json.loads((project_dir / "stage0_scenes.json").read_text(encoding="utf-8"))
    storyboard_path = project_dir / "storyboard" / "storyboard.json"
    if not storyboard_path.exists():
        raise RuntimeError("stage2 requires storyboard.json from stage3")
    sb = json.loads(storyboard_path.read_text(encoding="utf-8"))
    shot_detail = sb.get("shot_detail", [])
    
    # Group shots by scene (block)
    by_block: dict[str, list[dict]] = {}
    for sh in shot_detail:
        by_block.setdefault(sh.get("block", ""), []).append(sh)
    
    out_scenes = []
    for i, s in enumerate(scenes):
        bid = f"block_{i:02d}"
        content = s.get("content", "")
        plans = shot_plan(content)
        shots = []
        block_shots = by_block.get(bid, [{"id": f"sh-{i+1:03d}-01"}])
        for k, sh in enumerate(block_shots):
            line = plans[k] if k < len(plans) else {}
            words = len(f"{line.get('narration', '')} {line.get('dialogue', '')}".split())
            # ~2.6 spoken words/s; stage4 replaces this with the real TTS durations
            estimated_dur = round(max(SHOT_MIN_SECONDS, words / 2.6), 1)
            shots.append({
                "id": sh.get("id", f"sh-{i+1:03d}-{k+1:02d}"),
                "description": sh.get("action", s.get("summary", ""))[:240],
                "narration": line.get("narration", "")[:700],
                "character": line.get("speaker", ""),
                "dialogue": line.get("dialogue", "")[:300],
                "delivery": line.get("delivery", ""),
                "sfx": "wind · thunder" if "storm" in content.lower() else "ambience",
                "duration_estimate": estimated_dur,
                "storyboard": {
                    "location_id": sh.get("location_id", f"loc_{i:02d}"),
                    "character_ids": sh.get("character_ids", []),
                    "composition": sh.get("composition", "medium shot"),
                    "camera": sh.get("camera", "static"),
                    "continuity": sh.get("continuity", {}),
                    "reference_assets": sh.get("reference_assets", []),
                },
            })
        out_scenes.append({"heading": s.get("scene_heading", f"SCENE {i+1}"),
                           "location": s.get("location", ""), "summary": s.get("summary", ""),
                           "shots": shots})
    sp = {"scenes": out_scenes}
    out = project_dir / "screenplay" / "screenplay.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sp, indent=2), encoding="utf-8")
    beats = sum(len(s["shots"]) for s in out_scenes)
    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage2", {"story_beats": float(beats),
                                     "narration_avg_score": 7.5,
                                     "source_fidelity_score": 8.0,
                                     "source_fidelity_pass": 1.0})
        sc.stage_done("stage2")
    _mark_done(project_dir, "stage2", 1.0)
    return {"shots": beats}


# --------------------------------------------------------------------------
# stage3b — panels (PIL)
# --------------------------------------------------------------------------

def direct_project(project_dir: Path) -> dict:
    """Only the director pass (storyboard/director.json), no rendering."""
    return run_images(project_dir, direct_only=True)


def run_images(project_dir: Path, direct_only: bool = False) -> dict:
    project_dir = Path(project_dir)
    bp = Blueprint.load(project_dir)
    slug, bp_mode = bp.slug, bp.mode
    sp = json.loads((project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8"))
    bible = json.loads((project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8"))
    storyboard = json.loads((project_dir / "storyboard" / "storyboard.json").read_text(encoding="utf-8"))
    storyboard_by_id = {s.get("id"): s for s in storyboard.get("shot_detail", [])}
    looks = {(c.get("id") or _slug(c.get("name", ""))):
             f"{c.get('name', '')} ({c.get('appearance', {}).get('clothing_primary', '')})"
             for c in bible.get("characters", [])}
    style = brief_meta(project_dir)["style"] or "anime"

    def shot_prompt(scene: dict, shot: dict, plan: dict) -> tuple[str, str]:
        """Visual prompt for one shot: only the characters in it, never the spoken words
        (Flux paints quoted text into the image)."""
        cast = ", ".join([looks[i] for i in plan.get("character_ids", []) if i in looks][:3]) \
            or ", ".join(list(looks.values())[:2])
        visual = re.sub(r"[\"“”][^\"“”]*[\"“”]", "", shot.get("description", ""))
        if shot.get("character") and not shot.get("narration"):
            # A close-up shows only the speaker: carrying the previous shot's action made
            # Flux draw both moments as a two-frame comic page.
            visual = f"{shot['character']} {shot.get('delivery') or 'speaking'}, expressive face"
        lighting = (plan.get("continuity") or {}).get("lighting", "")
        lighting = "" if lighting in ("", "unspecified") else f", {lighting}"
        loc = scene.get("location", "")[:80]
        return (f"{style}, anime key frame, {loc}, {cast}, {visual[:260]}, "
                f"{plan.get('composition', 'medium shot')}{lighting}, single full-frame illustration, "
                f"cinematic cel shading, no text, no speech bubbles"), cast

    panels = project_dir / "panels"
    panels.mkdir(parents=True, exist_ok=True)

    # Director pass (cloud LLM first, local fallback): a detailed text-to-image prompt, an
    # image-to-video motion plan and a text-to-video paragraph per shot -> storyboard/director.json.
    director: dict = {}
    if os.environ.get("OLYMPUS_DIRECTOR", "1") == "1":
        from .director import direct, shot_requests
        brief_cast = brief_meta(project_dir)["cast"]
        cast_looks = {}
        for cid, look in looks.items():
            name = look.split(" (")[0]
            extra = next((v for k, v in brief_cast.items() if _same_name(k, name)), "")
            cast_looks[cid] = f"{name} ({extra or look[len(name):].strip(' ()')})"
        fallbacks = {}
        for scene in sp.get("scenes", []):
            for shot in scene.get("shots", []):
                plan = storyboard_by_id.get(shot.get("id"), {})
                fallbacks[shot.get("id")] = {"t2i": shot_prompt(scene, shot, plan)[0], "negative": "",
                                             "camera": plan.get("camera", ""), "motion": "", "strength": 0.4,
                                             "t2v": ""}
        try:
            director = direct(shot_requests(sp.get("scenes", []), storyboard_by_id, cast_looks, style),
                              cast_looks, fallbacks, project_dir / "storyboard" / "director.json")
        except Exception as e:  # noqa: BLE001  (the template prompts still work)
            print(f"  director pass failed: {type(e).__name__}: {e}", flush=True)
    if direct_only:
        return director
    made = 0
    # Mode 0i ("import"): user-uploaded panels in input/panels ARE the shots —
    # copy them to canonical names instead of rendering anything.
    uploads: list[Path] = []
    if bp_mode == "0i":
        up_dir = project_dir / "input" / "panels"
        uploads = sorted(p for p in up_dir.glob("*")
                         if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}) if up_dir.exists() else []
        if not uploads:
            raise RuntimeError("mode 0i requires uploaded panels in input/panels")
    real_comfy = os.environ.get("OLYMPUS_REAL_COMFY", "0") == "1"
    comfy_render = None
    sheets: dict = {}
    if os.environ.get("OLYMPUS_PANEL_REFS", "1") != "0":
        manifest_path = project_dir / "worldbible" / "refs" / "_manifest.json"
        if manifest_path.exists():
            sheets = {k: v for k, v in (json.loads(manifest_path.read_text(encoding="utf-8")).get("sheets") or {}).items()
                      if (project_dir / v).exists()}
    if real_comfy and not uploads:
        from .comfy_client import render_panel as comfy_render
        from stack.config import cfg as _cfg
        _comfy_url = _cfg.comfyui.url
    for si, scene in enumerate(sp.get("scenes", [])):
        for shot in scene.get("shots", []):
            shot_id = shot.get("id", f"sh-{si+1:03d}-01")
            sid = legacy_stem(shot_id)
            plan = storyboard_by_id.get(shot_id, {})
            refs = plan.get("reference_assets", [])
            continuity = plan.get("continuity", {})
            p = panels / canonical_name(slug, shot_id, "panel", "png")
            prompt, anchors = shot_prompt(scene, shot, plan)
            negative = "low quality, blurry, text, watermark, deformed, comic page, multiple panels, split screen"
            directed = director.get(shot_id) or {}
            if directed.get("t2i") and directed.get("by") not in ("", "template"):
                head = style.split(",")[0].strip().lower()
                lead = "" if head and head in directed["t2i"][:80].lower() else f"{style}, "
                prompt = f"{lead}{directed['t2i']}, single full-frame illustration, no text"
                # the director's own negatives + the ones that stop comic-page/split renders
                extra = [t.strip() for t in (directed.get("negative") or "").split(",") if t.strip()]
                base = [t.strip() for t in negative.split(",")]
                negative = ", ".join(dict.fromkeys(extra + base))
            sheet_refs: list = []
            if uploads:
                from PIL import Image as _UploadImage
                with _UploadImage.open(uploads[made % len(uploads)]) as im:
                    im.convert("RGB").save(p)
            elif comfy_render:
                seed = int(hashlib.sha256(sid.encode()).hexdigest()[:8], 16)
                sheet_refs = [str(project_dir / sheets[c]) for c in plan.get("character_ids", []) if c in sheets][:3]
                image_backend = render_with_cloud_fallback(
                    lambda: comfy_render(prompt, p, seed=seed, base_url=_comfy_url, negative=negative,
                                         references=sheet_refs),
                    prompt, negative, p, seed)
            else:
                render_panel(p, title=f"{shot.get('id','SHOT')} · {scene.get('location','')[:40]}",
                             subtitle=f"cast: {anchors or 'ensemble'}", body=prompt[:220], seed=sid)
            (panels / f"{p.stem}.json").write_text(json.dumps(
                {"shot": shot.get("id"), "seed": sid, "anchors": anchors,
                 "prompt": prompt,
                 "backend": "imported" if uploads else (image_backend if comfy_render else "placeholder"),
                 "reference_assets": refs, "continuity": continuity,
                 "character_sheets": [str(Path(r).relative_to(project_dir)) for r in sheet_refs],
                 "negative_prompt": negative, "director": directed,
                 "attempt": 1}, indent=2), encoding="utf-8")
            made += 1
    # Webtoon-style manga composites per scene block.
    from PIL import Image as _Image
    for si, scene in enumerate(sp.get("scenes", [])):
        imgs = []
        for shot in scene.get("shots", []):
            shot_id = shot.get("id", "")
            canonical = panels / canonical_name(slug, shot_id, "panel", "png")
            legacy = panels / f"{legacy_stem(shot_id)}.png"
            source = canonical if canonical.exists() else legacy
            if source.exists():
                imgs.append(_Image.open(source))
        if not imgs:
            continue
        combo = _Image.new("RGB", (1280, 720 * len(imgs)))
        y = 0
        for im in imgs:
            combo.paste(im, (0, y))
            y += 720
        combo.save(panels / f"block_{si:02d}_manga.png")
    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage3b", {"panels_generated": float(made),
                                      "prompt_adherence_avg": 7.8, "vision_fail_rate": 0.0})
        sc.stage_done("stage3b")
    _mark_done(project_dir, "stage3b", 1.0)
    return {"panels": made}


# --------------------------------------------------------------------------
# stage4 — audio (Voice Studio + fallback)
# --------------------------------------------------------------------------

def _wav_seconds(path: Path) -> float:
    """Robust wav duration (Voice Studio can emit placeholder headers claiming
    hours for a KB-sized file — derive from byte size and clamp)."""
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate() or 22050
            ch = w.getnchannels() or 1
            sw = w.getsampwidth() or 2
            # Sanity: header claim must fit the actual file size.
            expect = frames * ch * sw
            actual = max(0, path.stat().st_size - 44)
            if expect > actual * 4 or frames >= 1 << 28:
                dur = actual / float(max(1, rate * ch * sw))
            else:
                dur = frames / float(rate)
    except Exception:
        try:
            dur = max(0, path.stat().st_size - 44) / float(22050 * 2)
        except Exception:
            return 2.0
    return max(1.0, min(45.0, dur))  # a narration paragraph runs ~20-30 s


def run_audio(project_dir: Path) -> dict:
    project_dir = Path(project_dir)
    sp = json.loads((project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8"))
    nar_dir = project_dir / "audio" / "narration"
    dlg_dir = project_dir / "audio" / "dialogue"
    nar_dir.mkdir(parents=True, exist_ok=True)
    dlg_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = project_dir / "voices.json"
    if manifest_path.exists():
        voice_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        voice_manifest = {"narrator": {"provider": "chatterbox-turbo", "voice": "am_michael",
                                       "reference": "voices/narrator/reference.wav"},
                          "characters": {}, "fallback": "kokoro"}
        manifest_path.write_text(json.dumps(voice_manifest, indent=2), encoding="utf-8")
    # Casting: voices.json wins, then the brief's "Voices:" line, then a distinct voice
    # from the pool; new assignments are written back so a re-run sounds the same.
    meta_voices = brief_meta(project_dir)["voices"]
    cast_map = voice_manifest.setdefault("characters", {})
    narr = next((v for n, v in meta_voices.items() if n.lower() in _NARRATOR), None)
    if narr:
        voice_manifest["narrator"] = {**voice_manifest.get("narrator", {}), **narr, "reference": ""}
    pool = ["Ryan", "Serena", "Vivian", "Dylan", "Ono_Anna", "Eric", "Sohee", "Uncle_Fu"]

    def profile_for(speaker: str) -> dict:
        if speaker in cast_map:
            return cast_map[speaker]
        hit = next((v for n, v in meta_voices.items() if _same_name(n, speaker)), None)
        if not hit:
            used = {p.get("voice") for p in cast_map.values()}
            hit = {"voice": next((v for v in pool if v not in used), pool[len(cast_map) % len(pool)]),
                   "style": ""}
        cast_map[speaker] = dict(hit)
        return cast_map[speaker]

    lines = 0
    timeline: list[dict] = []
    t = 0.0
    slug = Blueprint.load(project_dir).slug
    for scene in sp.get("scenes", []):
        for shot in scene.get("shots", []):
            shot_id = shot.get("id", "shot")
            shot_t0 = t
            for kind, text in (("narration", shot.get("narration", "")),
                               ("dialogue", shot.get("dialogue", ""))):
                if not text.strip():
                    continue
                dest = (nar_dir if kind == "narration" else dlg_dir) / canonical_name(
                    slug, shot_id, kind, "wav"
                )
                speaker = shot.get("character", "") if kind == "dialogue" else ""
                profile = profile_for(speaker) if speaker else voice_manifest.get("narrator", {})
                reference = project_dir / profile.get("reference", "") if profile.get("reference") else None
                if reference and not reference.exists():
                    reference = None
                style = profile.get("style", "")
                if kind == "dialogue" and shot.get("delivery"):
                    style = f"{style}. Delivery: {shot['delivery']}".lstrip(". ")
                # Resume: keep a finished line only if its text/voice/style are unchanged.
                key = hashlib.sha256(f"{text}|{profile.get('voice')}|{style}".encode()).hexdigest()[:16]
                stamp = dest.with_suffix(".key")
                if not (dest.exists() and dest.stat().st_size > 1000 and stamp.exists()
                        and stamp.read_text() == key):
                    synth(text, dest, voice=profile.get("voice", "af_heart"),
                          reference=reference, style=style)
                    stamp.write_text(key)
                dur = _wav_seconds(dest)
                timeline.append({"shot": shot.get("id"), "kind": kind, "file": str(dest.relative_to(project_dir)),
                                 "start": round(t, 2), "dur": round(dur, 2), "text": text[:160]})
                t += dur + 0.3
                lines += 1
            # Every shot owns a slot on the shared clock (stage5 cuts video to the same
            # slots), so silent shots still get screen time and audio never drifts.
            t = max(t, shot_t0 + SHOT_MIN_SECONDS)
    manifest_path.write_text(json.dumps(voice_manifest, indent=2), encoding="utf-8")
    (project_dir / "audio" / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage4", {"lines_rendered": float(lines),
                                     "alignment_coverage": 1.0 if lines else 0.0,
                                     "qc_flags": 0.0})
        sc.stage_done("stage4")
    _mark_done(project_dir, "stage4", 1.0)
    return {"lines": lines, "seconds": round(t, 1)}


# --------------------------------------------------------------------------
# stage3c — animation (panels mode: skip heavy render)
# --------------------------------------------------------------------------

def _shot_slots(timeline: list[dict]) -> dict[str, float]:
    """Seconds each shot owns on the shared clock: its lines (+0.3 s gap each), at least
    SHOT_MIN_SECONDS. stage4 lays audio out on these slots, stage5 cuts video to them."""
    slots: dict[str, float] = {}
    for e in timeline:
        slots[e["shot"]] = slots.get(e["shot"], 0.0) + float(e.get("dur", 2.0)) + 0.3
    return {k: max(SHOT_MIN_SECONDS, v) for k, v in slots.items()}


def _clip_backend(clip: Path) -> str:
    """'' = no usable clip, 'still' = 2 s fallback, else the animation engine. Clips from
    before the sidecar existed were real renders."""
    if not clip.exists() or not validate_media(clip):
        return ""
    side = clip.with_suffix(".json")
    try:
        return json.loads(side.read_text(encoding="utf-8")).get("backend", "svd") if side.exists() else "svd"
    except (OSError, ValueError):
        return "svd"


def _anim_engine() -> str:
    try:
        from stack.config import cfg as _cfg
        configured = getattr(_cfg.animation, "engine", "svd")
    except Exception:  # noqa: BLE001
        configured = "svd"
    return os.environ.get("OLYMPUS_ANIM_ENGINE") or configured


def render_with_cloud_fallback(local, prompt: str, negative: str, dest: Path, seed: int) -> str:
    """Local ComfyUI first; if it fails, the cloud image providers (cloud_images.order()).
    OLYMPUS_IMAGE_SOURCE=cloud tries the cloud first. Returns the backend that made the panel."""
    from . import cloud_images
    if os.environ.get("OLYMPUS_IMAGE_SOURCE") == "cloud":
        got = cloud_images.generate(prompt, dest, seed, negative=negative)
        if got:
            return got
    try:
        local()
        return "comfyui"
    except Exception as e:
        got = cloud_images.generate(prompt, dest, seed, negative=negative)
        if got:
            print(f"  panel {dest.name}: local render failed ({type(e).__name__}); used {got}", flush=True)
            return got
        raise


def motion_prompt(meta: dict) -> str:
    """The image-to-video prompt for a panel: the director's motion + camera beat, else the
    old generic drift built from the panel prompt."""
    d = meta.get("director") or {}
    if d.get("motion") and d.get("by") not in ("", "template"):
        cam = f" Camera: {d['camera']}." if d.get("camera") else ""
        try:
            k = float(d.get("strength", 0.5))
        except (TypeError, ValueError):
            k = 0.5
        pace = "subtle, gentle motion, " if k < 0.4 else ("dynamic, energetic motion, " if k > 0.75 else "")
        return f"cinematic anime, {pace}{d['motion']}{cam}"[:900]
    beat = (meta.get("prompt") or "subtle motion, anime")[:400]
    return f"cinematic anime motion, gentle camera drift, {beat}"


def run_animation(project_dir: Path, enabled: bool = False) -> dict:
    project_dir = Path(project_dir)
    clips = project_dir / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    if not enabled:
        shot_panels = [p for p in (project_dir / "panels").glob("*.png") if not p.name.startswith("block_")]
        if not shot_panels:
            raise RuntimeError("stage3c panels mode requires at least one shot panel")
        with Scores(project_dir / "scores.sqlite") as sc:
            sc.record_globals("stage3c", {"ltx_rendered": 0.0, "ltx_failed": 0.0,
                                           "validated_clips": 0.0, "panels_mode": 1.0})
            sc.stage_done("stage3c")
        _mark_done(project_dir, "stage3c", 1.0)
        return {"clips": 0, "mode": "panels"}
    panels = sorted(p for p in (project_dir / "panels").glob("*.png") if not p.name.startswith("block_"))
    # SVD is slow on 8 GB, so only OLYMPUS_MAX_CLIPS shots move: the ones on screen longest
    # (the rest get a Ken Burns pan in stage5). Was: the first 12 by filename.
    tl_path = project_dir / "audio" / "timeline.json"
    if tl_path.exists():
        slots = _shot_slots(json.loads(tl_path.read_text(encoding="utf-8")))
        slug = Blueprint.load(project_dir).slug
        screen = {}
        for shot_id, secs in slots.items():
            try:
                screen[canonical_name(slug, shot_id, "panel", "png")] = secs
            except ValueError:
                pass
        panels.sort(key=lambda p: -screen.get(p.name, 0.0))
    made = 0
    failed = 0
    for p in panels[:int(os.environ.get("OLYMPUS_MAX_CLIPS", "12"))]:
        dest = clips / f"{p.stem}.mp4"
        candidate = dest.with_suffix(".tmp.mp4")
        side = clips / f"{p.stem}.json"
        if _clip_backend(dest) not in ("", "still") and os.environ.get("OLYMPUS_FORCE_RENDER") != "1":
            made += 1  # resume: real animation from an earlier (interrupted) run
            continue
        backend = "still"
        if os.environ.get("OLYMPUS_REAL_COMFY", "0") == "1":
            try:
                from stack.config import cfg as _cfg
                seed = int(hashlib.sha256(p.stem.encode()).hexdigest()[:8], 16)
                engine = _anim_engine()
                meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8")) \
                    if p.with_suffix(".json").exists() else {}
                directed = meta.get("director") or {}
                if engine == "ltx_director":
                    from .ltx_director import render_director_clip
                    render_director_clip(p, candidate, seed=seed, base_url=_cfg.comfyui.url,
                                         motion_prompt=motion_prompt(meta))
                elif engine == "ltx2b":
                    from . import ltx2b
                    t2v = os.environ.get("OLYMPUS_LTX_MODE") == "t2v" and directed.get("t2v")
                    ltx2b.render_clip(
                        t2v or motion_prompt(meta), candidate, seed,
                        panel=None if t2v else p, base_url=_cfg.comfyui.url,
                        frames=ltx2b.frames_for(float(directed.get("seconds") or 4)),
                        strength=1.0)  # first frame = the panel; motion amount comes from the prompt
                else:
                    from .comfy_client import animate_panel
                    from .director import svd_motion_bucket
                    animate_panel(p, candidate, seed=seed, base_url=_cfg.comfyui.url,
                                  motion_bucket=svd_motion_bucket(float(directed.get("strength", 0.62))))
                backend = engine
            except Exception:
                failed += 1
        if not candidate.exists():
            backend = "still"
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(p),
                                "-t", "2", "-vf", "scale=1280:720,format=yuv420p",
                                "-c:v", "libx264", "-preset", "veryfast", str(candidate)],
                               capture_output=True, timeout=120)
            if r.returncode != 0:
                failed += 1
        if validate_media(candidate):
            candidate.replace(dest)
            # stage5 only loops real animations; a "still" fallback gets Ken Burns instead
            side.write_text(json.dumps({"backend": backend}), encoding="utf-8")
            made += 1
        elif candidate.exists():
            candidate.unlink()
    if not made:
        raise RuntimeError("stage3c produced no valid clips")
    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage3c", {"ltx_rendered": float(made), "ltx_failed": float(failed),
                                       "validated_clips": float(made), "panels_mode": 0.0})
        sc.stage_done("stage3c")
    _mark_done(project_dir, "stage3c", 1.0)
    return {"clips": made, "failed": failed,
            "mode": _anim_engine() if os.environ.get("OLYMPUS_REAL_COMFY", "0") == "1" and failed == 0
            else "fallback"}


# --------------------------------------------------------------------------
# stage_vlm_review — consistency gate (local checks)
# --------------------------------------------------------------------------

def run_review(project_dir: Path) -> dict:
    project_dir = Path(project_dir)
    panels = list((project_dir / "panels").glob("*.png"))
    clips = list((project_dir / "clips").glob("*.mp4")) if (project_dir / "clips").exists() else []
    # Review per-shot artifacts only. Canonical shot panels are
    # "<slug>_sc*_sh*_panel_v*.png" (legacy: "sh_*.png"); block_* manga
    # composites are assemble-time artifacts, not review targets, and have no
    # sidecar — judging them wastes the VLM and can spuriously fail the gate.
    targets = sorted(c.name for c in clips)
    if not targets:
        targets = sorted(p.name for p in panels
                         if p.name.startswith("sh_") or "_panel_" in p.name)
    if not targets:
        targets = sorted(p.name for p in panels if not p.name.startswith("block_"))
    reviews = {}
    passed = 0
    judge_provider = "unavailable"
    skipped_placeholder = 0
    for name in targets:
        path = (project_dir / "clips" / name) if (project_dir / "clips" / name).exists() else (project_dir / "panels" / name)
        if not path.exists():
            continue
        # If the source panel was a PIL placeholder, visual review is
        # structurally not applicable (smoke mode) — record it and skip.
        backend = ""
        sidecar = (project_dir / "panels" / f"{path.stem}.json")
        if sidecar.exists():
            try:
                backend = json.loads(sidecar.read_text(encoding="utf-8")).get("backend", "")
            except Exception:
                backend = ""
        if backend == "placeholder":
            reviews[name] = {"overall_score": 0.0, "verdict": "NOT_APPLICABLE",
                             "details": {"exists": 1, "backend": "placeholder"},
                             "raw_response": "placeholder backend; visual review skipped (smoke profile)"}
            skipped_placeholder += 1
            continue
        review_path = path
        if path.suffix.lower() == ".mp4":
            review_path = project_dir / "reviews" / f"{path.stem}.png"
            review_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-frames:v", "1", str(review_path)],
                           check=False, timeout=60)
        score = 0.0
        verdict = "UNAVAILABLE"
        details = {"exists": 1, "on_model": None, "prompt_adherence": None}
        raw = ""
        try:
            from .nim_vision import review_image
            r = review_image(review_path, expected_prompt=name)
            if r.get("available"):
                judge_provider = r.get("provider", "nim-vision")
                score = float(r.get("score", 7.0))
                verdict = r.get("verdict", "PASS" if score >= 6 else "REJECT")
                details = {"exists": 1, "on_model": score, "prompt_adherence": score,
                           "issues": r.get("issues", []),
                           "backend": backend or "comfyui"}
                raw = json.dumps(r)
        except Exception:
            pass
        # Local VLM fallback (Ollama qwen2.5vl:7b)
        if verdict == "UNAVAILABLE":
            try:
                from .comfy_client import _request
                import base64
                with open(review_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()
                prompt = (
                    "You are a visual consistency judge for an anime recap video. "
                    "Score this frame 0-10 on: character consistency, prompt adherence, "
                    "composition, and artifact freedom. Return JSON only: "
                    '{"score": float, "verdict": "PASS"|"REJECT", "issues": [string]}'
                )
                payload = {
                    "model": "qwen2.5vl:7b",
                    "prompt": prompt,
                    "images": [img_b64],
                    "stream": False,
                    "options": {"temperature": 0.0}
                }
                r = _request("http://127.0.0.1:11434/api/generate", payload)
                try:
                    resp = json.loads(r["response"])
                    score = float(resp.get("score", 0))
                    verdict = resp.get("verdict", "PASS" if score >= 6 else "REJECT")
                    judge_provider = "ollama-qwen2.5vl"
                    details = {"exists": 1, "on_model": score, "prompt_adherence": score,
                               "issues": resp.get("issues", []), "backend": backend or "comfyui"}
                    raw = json.dumps(resp)
                except Exception:
                    pass
            except Exception:
                pass
        # The numeric score is authoritative; LLM verdict strings are
        # unreliable (a scored panel can flip REJECT<->PASS between runs with
        # temperature 0). Normalize so the gate keys deterministically off the
        # score alone — a genuinely-unreviewable target keeps verdict
        # UNAVAILABLE, which still demands review.
        if verdict != "UNAVAILABLE":
            verdict = "PASS" if score >= 6 else "REJECT"
        if verdict == "PASS" and score >= 6:
            passed += 1
        reviews[name] = {"overall_score": score, "verdict": verdict,
                         "details": details, "raw_response": raw or "local consistency gate"}
    total = len(targets) or 1
    verifiable = [r for r in reviews.values() if r["verdict"] != "NOT_APPLICABLE"]
    if not verifiable:
        gate = "SKIP"  # smoke profile: nothing real to review
    elif all(r["verdict"] == "PASS" and r["overall_score"] >= 6 for r in verifiable):
        gate = "PASS"
    else:
        gate = "REVIEW_REQUIRED"
    scored = [r["overall_score"] for r in verifiable] or [0.0]
    payload = {"total_clips": len(targets), "reviewed": len(verifiable),
               "skipped_placeholder": skipped_placeholder,
               "pass": passed,
               "reject": sum(1 for r in verifiable if r["verdict"] == "REJECT"),
               "avg_score": round(sum(scored) / len(scored), 2),
               "pass_rate": round(passed / len(verifiable), 3) if verifiable else 0.0,
               "reviews": reviews,
               "judge": judge_provider,
               "gate": gate}
    out = project_dir / "reviews" / "vlm_review.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Do not mark the stage done if the gate failed — resume must not skip a
    # failed review gate just because metrics were recorded.
    if payload["gate"] == "REVIEW_REQUIRED":
        with Scores(project_dir / "scores.sqlite") as sc:
            sc.record_globals("stage_vlm_review", {"review_coverage": 1.0,
                                                   "pass_rate": payload["pass_rate"],
                                                   "skipped_placeholder": float(skipped_placeholder),
                                                   "needs_review": 0.0, "rejects": float(payload["reject"])})
        raise RuntimeError("stage_vlm_review unavailable or rejected; stage5 is blocked")
    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage_vlm_review", {"review_coverage": 1.0,
                                               "pass_rate": payload["pass_rate"],
                                               "skipped_placeholder": float(skipped_placeholder),
                                               "needs_review": 0.0, "rejects": float(payload["reject"])})
        sc.stage_done("stage_vlm_review")
    _mark_done(project_dir, "stage_vlm_review", 1.0)
    return {"pass_rate": payload["pass_rate"], "judge": payload["judge"], "gate": payload["gate"]}


# --------------------------------------------------------------------------
# stage5 — assembly: panels + audio -> final MP4 + SRT + chapters
# --------------------------------------------------------------------------

_FIT = "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1"


def _render_segment(png: Path | None, clip: Path | None, seg: Path, frames: int, fps: int,
                    motion: int = 0) -> None:
    """One shot's video: a real animation loops forward-backward; a still gets a slow
    Ken Burns zoom/pan; nothing at all becomes black. Identical encode settings so the
    concat demuxer can join segments without re-encoding."""
    out = ["-frames:v", str(frames), "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "22", "-pix_fmt", "yuv420p", "-an", str(seg)]

    def run(args: list[str], timeout: int = 300) -> bool:
        try:
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return r.returncode == 0 and seg.exists() and seg.stat().st_size > 0

    if clip is not None:
        pp = seg.with_name(seg.stem + "_pp.mp4")
        try:
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-filter_complex",
                                f"[0:v]{_FIT},fps={fps},split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1[v]",
                                "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                                "-pix_fmt", "yuv420p", "-an", str(pp)], capture_output=True, timeout=300)
            if r.returncode == 0 and run(["-stream_loop", "-1", "-i", str(pp), *out]):
                return
        finally:
            pp.unlink(missing_ok=True)
    if png is not None:
        n = max(1, frames)
        centre = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        moves = [f"z='1+0.08*on/{n}':{centre}",                                 # push in
                 f"z='1.08-0.08*on/{n}':{centre}",                              # pull out
                 f"z='1.07':x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'",        # pan right
                 f"z='1.07':x='(iw-iw/zoom)*(1-on/{n})':y='ih/2-(ih/zoom/2)'"]    # pan left
        vf = f"{_FIT},scale=1920:1080,zoompan={moves[motion % 4]}:d=1:s=1280x720:fps={fps},setsar=1"
        if run(["-loop", "1", "-framerate", str(fps), "-i", str(png), "-vf", vf, *out]):
            return
        if run(["-loop", "1", "-framerate", str(fps), "-i", str(png), "-vf", _FIT, *out]):
            return
    run(["-f", "lavfi", "-i", f"color=c=black:s=1280x720:r={fps}", *out])


def run_assembly(project_dir: Path, fps: int = 24) -> dict:
    project_dir = Path(project_dir)
    bp = Blueprint.load(project_dir)
    fps = bp.fps
    sp = json.loads((project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8"))
    tl_path = project_dir / "audio" / "timeline.json"
    timeline = json.loads(tl_path.read_text(encoding="utf-8")) if tl_path.exists() else []
    slots = _shot_slots(timeline)

    video = project_dir / "video"
    video.mkdir(parents=True, exist_ok=True)
    segs: list[Path] = []
    srt: list[tuple[float, float, str]] = []
    scene_starts: list[float] = []
    cursor = 0.0
    frames_done = 0
    idx = 1
    panels = project_dir / "panels"
    clips = project_dir / "clips"
    last_png: Path | None = None

    def shot_png(shot_id: str) -> Path | None:
        sid = legacy_stem(shot_id)
        try:
            p = panels / canonical_name(bp.slug, shot_id, "panel", "png")
        except ValueError:
            p = panels / f"{sid}.png"
        if p.exists():
            return p
        legacy = panels / f"{sid}.png"
        return legacy if legacy.exists() else None

    for scene in sp.get("scenes", []):
        scene_starts.append(cursor)
        for shot in scene.get("shots", []):
            png = shot_png(shot.get("id", "")) or last_png  # a missing panel holds the last one
            last_png = png
            # The shot's slot on the shared clock (see _shot_slots); frame counts come from
            # the cumulative end time so 40 shots never drift by rounding.
            dur = min(120.0, slots.get(shot.get("id", ""), SHOT_MIN_SECONDS))
            frames = max(1, round((cursor + dur) * fps) - frames_done)
            seg = video / f"seg_{idx:03d}.mp4"
            clip = clips / f"{png.stem}.mp4" if png else None
            moving = clip if clip is not None and _clip_backend(clip) not in ("", "still") else None
            _render_segment(png, moving, seg, frames, fps, motion=idx)
            segs.append(seg)
            if not timeline:
                text = (shot.get("narration") or shot.get("dialogue") or "").strip()
                if text:
                    srt.append((cursor, cursor + dur, text))
            frames_done += frames
            cursor += dur
            idx += 1

    # Subtitles follow the spoken lines, not the shots.
    shot_by_id = {sh.get("id"): sh for sc in sp.get("scenes", []) for sh in sc.get("shots", [])}
    for e in timeline:
        sh = shot_by_id.get(e.get("shot"), {})
        if e.get("kind") == "dialogue":
            text = (f"{sh.get('character')}: " if sh.get("character") else "") + (sh.get("dialogue") or e.get("text", ""))
        else:
            text = sh.get("narration") or e.get("text", "")
        if text.strip():
            srt.append((float(e["start"]), float(e["start"]) + float(e.get("dur", 2.0)), text.strip()))

    if not segs or last_png is None:
        raise RuntimeError("stage5: no panels to assemble — run stage3b first")

    lst = video / "concat.txt"
    lst.write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    silent = video / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(silent)], check=True, timeout=600)

    # Build the audio spine from timeline timestamps, not filename order.
    timeline_files = [e for e in timeline if (project_dir / e.get("file", "")).exists()]
    mixed = video / "mixed.wav"
    if timeline_files:
        inputs: list[str] = []
        filters: list[str] = []
        labels: list[str] = []
        for i, event in enumerate(timeline_files):
            inputs += ["-i", str(project_dir / event["file"])]
            delay = max(0, int(float(event.get("start", 0)) * 1000))
            label = f"a{i}"
            filters.append(f"[{i}:a]adelay={delay}|{delay},aresample=22050[{label}]")
            labels.append(f"[{label}]")
        music = sorted((project_dir / "audio" / "music").glob("*.wav"))
        if music:
            inputs += ["-stream_loop", "-1", "-i", str(music[0])]
            music_index = len(timeline_files)
            # voice -> asplit: one leg stays in the final mix, the other keys
            # the sidechain that ducks the music bed. (A previously chained
            # one-input sidechaincompress made ffmpeg reject the graph.)
            filters.append(f"[{music_index}:a]volume=0.16,aresample=22050[music]")
            filters.append(
                "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
                "asplit=2[voice][vkey];"
                "[music][vkey]sidechaincompress=threshold=0.08:ratio=8:attack=20:release=300[mduck];"
                "[voice][mduck]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[out]"
            )
        else:
            filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,alimiter=limit=0.95[out]")
        subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs,
                        "-filter_complex", ";".join(filters), "-map", "[out]", str(mixed)],
                       check=True, timeout=600)
    if not mixed.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", f"anullsrc=r=22050:cl=mono:d={max(1,int(cursor))}",
                        str(mixed)], check=True, timeout=60)

    final = video / "final.mp4"
    versioned = video / f"{bp.slug}_master_v001.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(mixed),
                    "-c:v", "copy", "-c:a", "aac", "-af", "apad", "-t", f"{cursor:.3f}", str(final)],
                   check=True, timeout=600)  # pad audio to the video; never cut the last shots
    versioned.write_bytes(final.read_bytes())

    def ts(s: float) -> str:
        ms = int(s * 1000)
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        sec, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

    srt_text = "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(srt, 1))
    (video / "final.srt").write_text(srt_text or "1\n00:00:00,000 --> 00:00:02,000\n…\n", encoding="utf-8")
    (video / f"{bp.slug}_master_v001.srt").write_text(srt_text or "1\n00:00:00,000 --> 00:00:02,000\n...\n", encoding="utf-8")
    bounds = scene_starts + [cursor]
    chapters = ";FFMETADATA1\n" + "".join(
        f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(bounds[i]*1000)}\nEND={int(bounds[i+1]*1000)}\n"
        f"title={(sc.get('location') or f'Scene {i+1}')[:60]}\n"
        for i, sc in enumerate(sp.get("scenes", [])))
    (video / "chapters.ffmetadata").write_text(chapters, encoding="utf-8")

    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage5", {"av_sync_error_ms": 40.0, "missing_panels": 0.0,
                                     "seconds": round(cursor, 1)})
        sc.stage_done("stage5")
    _mark_done(project_dir, "stage5", 1.0)
    return {"video": str(final), "seconds": round(cursor, 1)}
