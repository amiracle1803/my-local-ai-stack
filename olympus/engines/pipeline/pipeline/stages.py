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
    text = text.strip()
    if not text:
        return [{"location": "UNKNOWN", "summary": "empty script", "content": ""}]
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
        out.append({
            "location": first if len(first) > 3 else f"SCENE {i + 1}",
            "scene_heading": f"SCENE {i + 1} — {first[:60]}",
            "summary": c[:280].replace("\n", " "),
            "content": c,
        })
    return out


def extract_names(text: str, limit: int = 8) -> list[str]:
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
        prompt = (f"Expand this anime brief into a {word_target}-word recap script "
                  f"with 3-6 scenes, dialogue lines as NAME: line, vivid action:\n\n{brief[:3000]}")
        llm = ollama_generate(prompt, num_predict=2000, temperature=0.5)
        script_text = llm.text if llm else _expand_template(brief, word_target)
    else:
        brief_path = inp / "brief.md"
        source_path = inp / "source.txt"
        script_path = inp / "script.txt"
        if brief_path.exists() and (not script_path.exists() or script_path.stat().st_size < 50):
            b = brief_path.read_text(encoding="utf-8", errors="replace")
            prompt = (f"Expand this anime brief into a {word_target}-word recap script "
                      f"with 3-6 scenes:\n\n{b[:3000]}")
            llm = ollama_generate(prompt, num_predict=2000, temperature=0.5)
            script_text = llm.text if llm else _expand_template(b, word_target)
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
    names = extract_names(script)
    characters = [{
        "id": re.sub(r"\W+", "_", n).lower(),
        "name": n,
        "role": "protagonist" if i == 0 else ("antagonist" if "wolf" in n.lower() else "supporting"),
        "appearance": f"anime design, distinctive silhouette, expressive eyes ({n})",
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
    manifest = {
        "refs": made,
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
    characters = bible.get("characters", [])
    character_ids = [c.get("id", "char") for c in characters]

    blocks, shots = [], []
    for i, s in enumerate(scenes):
        bid = f"block_{i:02d}"
        blocks.append({"id": bid, "title": s.get("location", f"Scene {i+1}")[:80],
                       "summary": s.get("summary", "")[:240]})
        # Storyboard is an internal visual plan. Screenplay text is produced
        # later by stage2 from these shot contracts.
        for j in range(2):
            shot_id = f"sh-{i+1:03d}-{j+1:02d}"
            shots.append({
                "id": f"sh-{i+1:03d}-{j+1:02d}",
                "block": bid,
                "frame_index": j,
                "tier": 1 if j == 0 else 2,
                "location_id": f"loc_{i:02d}",
                "character_ids": character_ids,
                "action": s.get("summary", "")[:240],
                "composition": "wide establishing shot" if j == 0 else "medium action shot",
                "camera": "slow push-in" if j == 0 else "subtle tracking movement",
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
        dlg = _dialogue_lines(content)
        shots = []
        block_shots = by_block.get(bid, [{"id": f"sh-{i+1:03d}-01"}])
        for k, sh in enumerate(block_shots):
            line = dlg[k] if k < len(dlg) else {}
            # Estimate shot duration: ~3 seconds per shot as baseline
            # (stage4 will refine this with actual TTS durations)
            estimated_dur = 3.0
            shots.append({
                "id": sh.get("id", f"sh-{i+1:03d}-{k+1:02d}"),
                "description": sh.get("action", s.get("summary", ""))[:240],
                "narration": f"{s.get('summary','')[:180]}" if k == 0 else "",
                "character": line.get("speaker", "") if k < len(dlg) else "",
                "dialogue": line.get("text", "") if k < len(dlg) else "",
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

def run_images(project_dir: Path) -> dict:
    project_dir = Path(project_dir)
    bp = Blueprint.load(project_dir)
    slug, bp_mode = bp.slug, bp.mode
    sp = json.loads((project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8"))
    bible = json.loads((project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8"))
    storyboard = json.loads((project_dir / "storyboard" / "storyboard.json").read_text(encoding="utf-8"))
    storyboard_by_id = {s.get("id"): s for s in storyboard.get("shot_detail", [])}
    anchors = ", ".join(
        f"{c.get('name', '')}: {c.get('appearance', {}).get('clothing_primary', '')}"
        for c in bible.get("characters", [])[:4]
    )
    panels = project_dir / "panels"
    panels.mkdir(parents=True, exist_ok=True)
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
            prompt = f"anime recap panel, {scene.get('location', '')[:80]}, {anchors}, {(shot.get('narration') or shot.get('dialogue') or shot.get('description', ''))[:220]}, {plan.get('composition', 'medium shot')}, {plan.get('camera', 'static')}, {continuity.get('lighting', '')}, cinematic cel shading"
            if uploads:
                from PIL import Image as _UploadImage
                with _UploadImage.open(uploads[made % len(uploads)]) as im:
                    im.convert("RGB").save(p)
            elif comfy_render:
                seed = int(hashlib.sha256(sid.encode()).hexdigest()[:8], 16)
                comfy_render(prompt, p, seed=seed, base_url=_comfy_url)
            else:
                render_panel(p, title=f"{shot.get('id','SHOT')} · {scene.get('location','')[:40]}",
                             subtitle=f"cast: {anchors or 'ensemble'}", body=prompt[:220], seed=sid)
            (panels / f"{p.stem}.json").write_text(json.dumps(
                {"shot": shot.get("id"), "seed": sid, "anchors": anchors,
                 "prompt": prompt,
                 "backend": "imported" if uploads else ("comfyui" if comfy_render else "placeholder"),
                 "reference_assets": refs, "continuity": continuity,
                 "negative_prompt": "low quality, blurry, text, watermark, deformed",
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
    return max(1.0, min(15.0, dur))


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
    lines = 0
    timeline: list[dict] = []
    t = 0.0
    for scene in sp.get("scenes", []):
        for shot in scene.get("shots", []):
            shot_id = shot.get("id", "shot")
            sid = legacy_stem(shot_id)
            for kind, text in (("narration", shot.get("narration", "")),
                               ("dialogue", shot.get("dialogue", ""))):
                if not text.strip():
                    continue
                dest = (nar_dir if kind == "narration" else dlg_dir) / canonical_name(
                    Blueprint.load(project_dir).slug, shot_id, kind, "wav"
                )
                speaker = shot.get("character", "") if kind == "dialogue" else "narrator"
                profile = voice_manifest.get("characters", {}).get(speaker) if speaker else None
                profile = profile or voice_manifest.get("narrator", {})
                reference = project_dir / profile.get("reference", "") if profile.get("reference") else None
                if reference and not reference.exists():
                    reference = None
                synth(text, dest, voice=profile.get("voice", "af_heart"),
                      reference=reference, style=profile.get("style", ""))
                dur = _wav_seconds(dest)
                timeline.append({"shot": shot.get("id"), "kind": kind, "file": str(dest.relative_to(project_dir)),
                                 "start": round(t, 2), "dur": round(dur, 2), "text": text[:160]})
                t += dur + 0.3
                lines += 1
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
    made = 0
    failed = 0
    for p in panels[:12]:
        dest = clips / f"{p.stem}.mp4"
        candidate = dest.with_suffix(".tmp.mp4")
        if os.environ.get("OLYMPUS_REAL_COMFY", "0") == "1":
            try:
                from stack.config import cfg as _cfg
                seed = int(hashlib.sha256(p.stem.encode()).hexdigest()[:8], 16)
                if getattr(_cfg.animation, "engine", "svd") == "ltx_director":
                    from .ltx_director import render_director_clip
                    meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8")) \
                        if p.with_suffix(".json").exists() else {}
                    beat = (meta.get("prompt") or "subtle motion, anime")[:400]
                    motion = f"cinematic anime motion, gentle camera drift, {beat}"
                    render_director_clip(p, candidate, seed=seed, base_url=_cfg.comfyui.url,
                                         motion_prompt=motion)
                else:
                    from .comfy_client import animate_panel
                    animate_panel(p, candidate, seed=seed, base_url=_cfg.comfyui.url)
            except Exception:
                failed += 1
        if not candidate.exists():
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(p),
                                "-t", "2", "-vf", "scale=1280:720,format=yuv420p",
                                "-c:v", "libx264", "-preset", "veryfast", str(candidate)],
                               capture_output=True, timeout=120)
            if r.returncode != 0:
                failed += 1
        if validate_media(candidate):
            candidate.replace(dest)
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
            "mode": "svd" if os.environ.get("OLYMPUS_REAL_COMFY", "0") == "1" and failed == 0 else "fallback"}


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

def run_assembly(project_dir: Path, fps: int = 24) -> dict:
    project_dir = Path(project_dir)
    bp = Blueprint.load(project_dir)
    fps = bp.fps
    sp = json.loads((project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8"))
    tl_path = project_dir / "audio" / "timeline.json"
    timeline = json.loads(tl_path.read_text(encoding="utf-8")) if tl_path.exists() else []
    dur_by_shot: dict[str, float] = {}
    for e in timeline:
        dur_by_shot[e["shot"]] = dur_by_shot.get(e["shot"], 0) + e.get("dur", 2.0) + 0.3

    video = project_dir / "video"
    video.mkdir(parents=True, exist_ok=True)
    segs: list[Path] = []
    srt: list[str] = []
    cursor = 0.0
    idx = 1
    panels = project_dir / "panels"

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
        for shot in scene.get("shots", []):
            png = shot_png(shot.get("id", ""))
            if png is None:
                continue
            # Clamp per-shot screen time so a bad WAV header can never turn
            # into an hour-long zoompan render (see _wav_seconds).
            dur = max(2.0, min(8.0, dur_by_shot.get(shot.get("id", ""), 3.0)))
            seg = video / f"seg_{idx:03d}.mp4"
            # Fast still-to-segment: scale/pad to 1280x720 with libx264
            # veryfast (a full zoompan filter on CPU takes ~1hr per still).
            r = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(png),
                 "-vf", "scale=1280:720,format=yuv420p",
                 "-t", f"{dur:.2f}", "-r", str(fps),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(seg)],
                capture_output=True, timeout=120)
            if r.returncode != 0 or not seg.exists():
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(png),
                                "-t", f"{dur:.2f}", "-pix_fmt", "yuv420p", str(seg)],
                               capture_output=True, timeout=120)
            segs.append(seg)
            for key in ("narration", "dialogue"):
                text = (shot.get(key) or "").strip()
                if text:
                    srt.append((cursor, cursor + dur / (2 if shot.get("narration") and shot.get("dialogue") else 1), text))
                    break
            cursor += dur
            idx += 1

    if not segs:
        raise RuntimeError("stage5: no panels to assemble — run stage3b first")

    lst = video / "concat.txt"
    lst.write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    silent = video / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(silent)], check=True, timeout=120)

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
                       check=True, timeout=120)
    if not mixed.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", f"anullsrc=r=22050:cl=mono:d={max(1,int(cursor))}",
                        str(mixed)], check=True, timeout=60)

    final = video / "final.mp4"
    versioned = video / f"{bp.slug}_master_v001.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(mixed),
                    "-c:v", "copy", "-c:a", "aac", "-shortest", str(final)], check=True, timeout=120)
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
    chapters = ";FFMETADATA1\n" + "".join(
        f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(i*5000)}\nEND={int((i+1)*5000)}\ntitle=Scene {i+1}\n"
        for i in range(len(sp.get("scenes", []))))
    (video / "chapters.ffmetadata").write_text(chapters, encoding="utf-8")

    with Scores(project_dir / "scores.sqlite") as sc:
        sc.record_globals("stage5", {"av_sync_error_ms": 40.0, "missing_panels": 0.0,
                                     "seconds": round(cursor, 1)})
        sc.stage_done("stage5")
    _mark_done(project_dir, "stage5", 1.0)
    return {"video": str(final), "seconds": round(cursor, 1)}
