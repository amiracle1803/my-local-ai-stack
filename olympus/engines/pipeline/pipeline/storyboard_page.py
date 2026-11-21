"""Storyboard data for the Studio page (2026-11-21): one live view for every project.

storyboard(project_dir) reads what the pipeline already wrote (screenplay, timeline, panels and
their key frames, chapters, master, thumbnail) and returns JSON for Studio's STORYBOARD panel.
Nothing is generated per project: the kernel serves it at GET /api/pipeline/<slug>/storyboard and
the files through /api/pipeline/<slug>/view/<path> (frame previews via /thumb).
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _scene_titles(brief: str) -> list[tuple[str, str]]:
    """SCENE lines of the brief (or its embedded source script) -> (title, summary)."""
    out = []
    for line in re.findall(r"(?im)^\s*SCENE\s+\d+\s*[-—–:]\s*(.+)$", brief or ""):
        title, _, summary = line.strip().partition(". ")
        out.append((title.strip().rstrip("."), summary.strip()))
    return out


def _chapters(path: Path) -> list[tuple[float, float]]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [(int(a) / 1000, int(b) / 1000) for a, b in re.findall(r"START=(\d+)\nEND=(\d+)", text)]


def _master(video: Path, slug: str) -> Path | None:
    p = video / f"{slug}_master_v001.mp4"
    if p.exists():
        return p
    found = sorted(video.glob("*master*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
    return found[0] if found else None


def storyboard(project_dir: Path) -> dict:
    """Everything the Studio storyboard view shows, as project-relative paths."""
    from .edit import episode_title
    from .identity import canonical_name
    from .stages import _shot_slots, shot_frames

    project_dir = Path(project_dir)
    slug = project_dir.name
    video = project_dir / "video"
    sp_path = project_dir / "screenplay" / "screenplay.json"
    brief_p = project_dir / "input" / "brief.md"
    brief = brief_p.read_text(encoding="utf-8", errors="replace") if brief_p.exists() else ""
    out: dict = {"slug": slug, "title": episode_title(brief, slug), "eyebrow": "", "master": "",
                 "thumbnail": "", "seconds": 0.0, "scenes": []}
    series = re.search(r"(?im)^\s*Series:\s*([^—\n]+?)\s*(?:—|$)", brief)
    ep = re.search(r"(?im)EPISODE\s*(\d+)", brief)
    out["eyebrow"] = " · ".join(x for x in ((series.group(1).strip() if series else ""),
                                            f"Episode {int(ep.group(1)):02d}" if ep else "") if x)
    if not sp_path.exists():
        return out
    sp = json.loads(sp_path.read_text(encoding="utf-8"))
    tl = project_dir / "audio" / "timeline.json"
    slots = _shot_slots(json.loads(tl.read_text(encoding="utf-8"))) if tl.exists() else {}
    master = _master(video, slug)
    thumb = video / f"{slug}_thumbnail_v001.png"
    out["master"] = str(master.relative_to(project_dir)) if master else ""
    out["thumbnail"] = str(thumb.relative_to(project_dir)) if thumb.exists() else ""
    titles = _scene_titles(brief)
    bounds = _chapters(video / "chapters.ffmetadata") if master else []
    t = 0.0
    for i, sc in enumerate(sp.get("scenes", [])):
        shots = []
        for sh in sc.get("shots", []):
            main = project_dir / "panels" / canonical_name(slug, sh["id"], "panel", "png")
            frames = [str(f.relative_to(project_dir)) for f in (shot_frames(main) if main.exists() else [])]
            shots.append({"id": main.stem.split("_panel")[0].replace(slug + "_", ""),
                          "seconds": round(slots.get(sh["id"], 0.0) or sh.get("duration_estimate", 0.0), 1),
                          "narration": sh.get("narration") or "", "speaker": sh.get("character") or "",
                          "line": sh.get("dialogue") or "", "delivery": sh.get("delivery") or "",
                          "frames": frames})
        span = sum(s["seconds"] for s in shots)
        start, end = bounds[i] if i < len(bounds) else (t, t + span)
        t = end
        title, summary = titles[i] if i < len(titles) else (sc.get("location", "") or f"Scene {i + 1}",
                                                            sc.get("summary", ""))
        out["scenes"].append({"n": i + 1, "title": title, "summary": summary, "start": round(start, 2),
                              "end": round(end, 2), "shots": shots})
    out["seconds"] = round(t, 1)
    return out
