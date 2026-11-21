"""stage5 storyboard page (2026-11-21): the finished episode strung back into its scenes, on disk.

Writes into the project's video/ folder (nothing leaves the machine):
  video/scenes/<slug>_sceneNN.mp4   each scene cut from the master at its chapter marks
  video/storyboard/<frame>.jpg      640px previews of every key frame
  video/storyboard.html             scene players + shot timeline + every frame + lines

Open video/storyboard.html from disk, or through the Studio API:
  http://<studio>:4600/api/pipeline/<slug>/view/video/storyboard.html
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

TEMPLATE = Path(__file__).parent / "templates" / "storyboard.html"


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


def _preview(src: Path, dest: Path, width: int = 640) -> None:
    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        return
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((width, width))
        im.save(dest, "JPEG", quality=80, optimize=True)


def build(project_dir: Path, master: Path | None = None) -> Path | None:
    """Scene clips + storyboard.html for a finished project; None when there is no master yet."""
    from .edit import episode_title
    from .identity import canonical_name
    from .stages import _shot_slots, shot_frames

    project_dir = Path(project_dir)
    slug = project_dir.name
    video = project_dir / "video"
    master = master or video / f"{slug}_master_v001.mp4"
    sp_path = project_dir / "screenplay" / "screenplay.json"
    if not master.exists() or not sp_path.exists():
        return None
    sp = json.loads(sp_path.read_text(encoding="utf-8"))
    tl = project_dir / "audio" / "timeline.json"
    slots = _shot_slots(json.loads(tl.read_text(encoding="utf-8"))) if tl.exists() else {}
    brief_p = project_dir / "input" / "brief.md"
    brief = brief_p.read_text(encoding="utf-8", errors="replace") if brief_p.exists() else ""
    titles = _scene_titles(brief)
    bounds = _chapters(video / "chapters.ffmetadata")
    scenes_dir, frames_dir = video / "scenes", video / "storyboard"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    scenes = []
    for i, sc in enumerate(sp.get("scenes", [])):
        if i >= len(bounds):
            break
        a, b = bounds[i]
        clip = scenes_dir / f"{slug}_scene{i + 1:02d}.mp4"
        if not clip.exists() or clip.stat().st_mtime < master.stat().st_mtime:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(master),
                            "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-c:a", "aac", "-b:a", "160k",
                            "-movflags", "+faststart", str(clip)], check=True, timeout=1800)
        shots = []
        for sh in sc.get("shots", []):
            main = project_dir / "panels" / canonical_name(slug, sh["id"], "panel", "png")
            frames = []
            for f in (shot_frames(main) if main.exists() else []):
                jpg = frames_dir / f"{f.stem}.jpg"
                _preview(f, jpg)
                frames.append(f"storyboard/{jpg.name}")
            shots.append({"id": main.stem.split("_panel")[0].replace(slug + "_", ""),
                          "seconds": round(slots.get(sh["id"], 2.5), 1),
                          "narration": sh.get("narration") or "", "speaker": sh.get("character") or "",
                          "line": sh.get("dialogue") or "", "delivery": sh.get("delivery") or "",
                          "frames": frames})
        title, summary = titles[i] if i < len(titles) else (sc.get("location", "") or f"Scene {i + 1}", "")
        scenes.append({"n": i + 1, "title": title, "summary": summary, "start": a, "end": b,
                       "video": f"scenes/{clip.name}", "file": str(clip), "shots": shots})
    if not scenes:
        return None
    series = re.search(r"(?im)^\s*Series:\s*([^—\-\n]+)", brief)
    ep = re.search(r"(?im)EPISODE\s*(\d+)", brief)
    eyebrow = " · ".join(x for x in ((series.group(1).strip() if series else slug),
                                     f"Episode {int(ep.group(1)):02d}" if ep else "") if x)
    thumb = video / f"{slug}_thumbnail_v001.png"
    data = {"slug": slug, "title": episode_title(brief, slug), "eyebrow": eyebrow, "scenes": scenes,
            "thumb": thumb.name if thumb.exists() else ""}
    (video / "scenes.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    page = video / "storyboard.html"
    page.write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps(data)), encoding="utf-8")
    return page
