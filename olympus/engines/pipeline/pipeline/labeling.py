"""Human-readable labels for panels and clips (the labeling standard).

The pipeline stores every artifact under a cryptic shot id (``sh-001-01.png``,
``sh-001-01_director_00001.mp4``) so paths stay stable and unambiguous for the
engine. But a human scanning the project folder should not have to decode those
ids. This module generates a **companion labels index** — ``labels.json``
(structured), ``labels.txt`` (readable), and ``labels.html`` (browseable) — in
the project root mapping every panel and clip to its scene · location ·
time-of-day · beat · characters · composition.

It never renames files; it only describes them. This is the standard: call
``build_labels(project_dir)`` (wired into ``run.py``) after any stage that
produces panels or clips.
"""
from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Any

from ._util import now_iso, read_json, write_json, load_screenplay, load_storyboard

logger = logging.getLogger(__name__)

_LABELS_JSON = "labels.json"
_LABELS_TXT = "labels.txt"
_LABELS_HTML = "labels.html"


# --------------------------------------------------------------------------
# label + slug helpers
# --------------------------------------------------------------------------
def _location_name(scene: dict[str, Any], wb: dict[str, Any] | None) -> str:
    """Resolve a scene's location id to its human-readable name from the world
    bible. Falls back to the raw id when unknown."""
    loc_id = scene.get("location", "")
    if wb:
        for loc in wb.get("locations", []):
            if isinstance(loc, dict) and loc.get("id") == loc_id:
                return str(loc.get("name") or loc_id)
    return loc_id or "unknown"


def _character_names(shot: dict[str, Any], wb: dict[str, Any] | None) -> list[str]:
    """Resolve ``characters_in_frame`` ids to names from the world bible."""
    ids = shot.get("characters_in_frame") or []
    if not ids or not wb:
        return [str(i) for i in ids]
    by_id = {c.get("id"): c.get("name") for c in wb.get("characters", [])
             if isinstance(c, dict)}
    return [str(by_id.get(i, i)) for i in ids]


def _beat_text(shot: dict[str, Any]) -> str:
    """A short human sentence describing what happens in the shot."""
    beat = (shot.get("beat") or "").strip()
    if beat:
        return beat
    narration = shot.get("narration") or {}
    if isinstance(narration, dict):
        text = (narration.get("text") or "").strip()
        if text:
            return text[:160]
    return shot.get("sd_prompt") or ""


def shot_label(
    shot: dict[str, Any],
    scene: dict[str, Any] | None = None,
    wb: dict[str, Any] | None = None,
) -> str:
    """A compact human-readable label for a shot, e.g.
    ``SC-001 · The Village · Morning · Kana arrives at the shrine``."""
    scene = scene or {}
    sid = shot.get("id", "")
    parts = [scene.get("id", "").upper() or sid]
    loc = _location_name(scene, wb)
    if loc:
        parts.append(str(loc).title())
    tod = scene.get("time_of_day")
    if tod:
        parts.append(str(tod).title())
    composition = shot.get("composition")
    if composition:
        parts.append(str(composition).split(",")[0].strip().title())
    beat = _beat_text(shot)
    if beat:
        # keep the label short: first sentence, capped
        beat = re.split(r"[.!?\n]", beat)[0].strip()[:90]
    chars = _character_names(shot, wb)
    if chars and not beat:
        parts.append("+".join(chars))
    if beat:
        parts.append(beat)
    return " · ".join(parts)


def shot_slug(
    shot: dict[str, Any],
    scene: dict[str, Any] | None = None,
    wb: dict[str, Any] | None = None,
) -> str:
    """A filesystem-safe slug derived from the same info as :func:`shot_label`,
    e.g. ``sc-001-the-village-morning-kana-arrives``. Useful if anyone wants a
    readable filename later; the index uses it as a stable key."""
    scene = scene or {}
    loc = _location_name(scene, wb)
    tod = scene.get("time_of_day", "")
    beat = re.split(r"[.!?\n]", _beat_text(shot))[0].strip()
    parts = [scene.get("id", shot.get("id", "")).lower(), str(loc).lower(),
             str(tod).lower(), beat.lower()]
    slug = "-".join(p for p in parts if p)
    slug = re.sub(r"[^a-z0-9\-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:120] or shot.get("id", "shot")


# --------------------------------------------------------------------------
# index builders
# --------------------------------------------------------------------------
def _load_worldbible(project_dir: Path) -> dict[str, Any] | None:
    p = project_dir / "worldbible" / "world_bible.json"
    try:
        d = read_json(p)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return None


def _panels_index(project_dir: Path, wb: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Index every generated panel under ``panels/<block>/<sid>.png``."""
    out: list[dict[str, Any]] = []
    screen = load_screenplay(project_dir)
    by_id = {s["id"]: s for scene in screen.get("scenes", []) for s in scene.get("shots", [])}
    scene_by_shot = {s["id"]: scene for scene in screen.get("scenes", [])
                     for s in scene.get("shots", [])}
    for png in sorted((project_dir / "panels").glob("*/[!_.]*.png")):
        sid = png.stem
        shot = by_id.get(sid, {})
        scene = scene_by_shot.get(sid, {})
        rel = png.relative_to(project_dir).as_posix()
        out.append({
            "shot_id": sid,
            "file": rel,
            "block": png.parent.name,
            "slug": shot_slug(shot, scene, wb),
            "label": shot_label(shot, scene, wb),
            "scene": scene.get("id", ""),
            "location": _location_name(scene, wb),
            "time_of_day": scene.get("time_of_day", ""),
            "characters": _character_names(shot, wb),
            "composition": shot.get("composition", ""),
            "beat": _beat_text(shot),
        })
    return out


def _clips_index(project_dir: Path, wb: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Index every rendered clip under ``clips/`` by matching its shot id."""
    out: list[dict[str, Any]] = []
    clips_dir = project_dir / "clips"
    if not clips_dir.exists():
        return out
    screen = load_screenplay(project_dir)
    by_id = {s["id"]: s for scene in screen.get("scenes", []) for s in scene.get("shots", [])}
    scene_by_shot = {s["id"]: scene for scene in screen.get("scenes", [])
                     for s in scene.get("shots", [])}
    # a clip filename embeds the shot id as the first token, e.g.
    # sh-001-01_director_00001.mp4 -> sh-001-01
    sid_re = re.compile(r"^((?:sh|shot)-\d+-\d+(?:-\d+)?)")
    for mp4 in sorted(clips_dir.glob("*.mp4")):
        m = sid_re.match(mp4.name)
        sid = m.group(1) if m else mp4.stem
        shot = by_id.get(sid, {})
        scene = scene_by_shot.get(sid, {})
        kind = "director" if "director" in mp4.name else (
            "hq" if "_hq" in mp4.name else "clip")
        out.append({
            "shot_id": sid,
            "file": mp4.relative_to(project_dir).as_posix(),
            "kind": kind,
            "slug": shot_slug(shot, scene, wb),
            "label": shot_label(shot, scene, wb),
            "scene": scene.get("id", ""),
            "location": _location_name(scene, wb),
            "time_of_day": scene.get("time_of_day", ""),
            "characters": _character_names(shot, wb),
            "beat": _beat_text(shot),
        })
    return out


def _scenes_index(project_dir: Path, wb: dict[str, Any] | None) -> list[dict[str, Any]]:
    screen = load_screenplay(project_dir)
    out = []
    for scene in screen.get("scenes", []):
        out.append({
            "scene_id": scene.get("id", ""),
            "location": _location_name(scene, wb),
            "time_of_day": scene.get("time_of_day", ""),
            "summary": scene.get("summary", ""),
            "shot_count": len(scene.get("shots", [])),
        })
    return out


def build_labels(project_dir: str | Path) -> dict[str, Any]:
    """Build the full labels index for a project and return it (does not write)."""
    project_dir = Path(project_dir)
    wb = _load_worldbible(project_dir)
    return {
        "story_id": _story_id(project_dir),
        "generated_at": now_iso(),
        "scenes": _scenes_index(project_dir, wb),
        "panels": _panels_index(project_dir, wb),
        "clips": _clips_index(project_dir, wb),
    }


def _story_id(project_dir: Path) -> str:
    try:
        bp = read_json(project_dir / "blueprint.json")
        return str(bp.get("story_id", ""))
    except (OSError, ValueError):
        return ""


# --------------------------------------------------------------------------
# writers (the standard)
# --------------------------------------------------------------------------
def _write_txt(labels: dict[str, Any], path: Path) -> None:
    lines = [f"LABELS INDEX — {labels.get('story_id', '')}",
             f"generated {labels.get('generated_at', '')}", ""]
    lines.append("SCENES")
    for sc in labels.get("scenes", []):
        lines.append(f"  {sc['scene_id']} · {sc['location']} · {sc['time_of_day']} "
                     f"({sc['shot_count']} shots) — {sc['summary']}")
    lines.append("")
    lines.append("PANELS")
    for p in labels.get("panels", []):
        lines.append(f"  {p['file']}")
        lines.append(f"      {p['label']}")
    lines.append("")
    lines.append("CLIPS")
    for c in labels.get("clips", []):
        lines.append(f"  {c['file']}  [{c['kind']}]")
        lines.append(f"      {c['label']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_html(labels: dict[str, Any], path: Path) -> None:
    def esc(s: Any) -> str:
        return html.escape(str(s))

    rows = []
    for p in labels.get("panels", []):
        rows.append(f"<tr><td>{esc(p['shot_id'])}</td><td><code>{esc(p['file'])}</code>"
                    f"</td><td>{esc(p['label'])}</td></tr>")
    panel_rows = "\n".join(rows)

    clip_rows = "\n".join(
        f"<tr><td>{esc(c['shot_id'])}</td><td><code>{esc(c['file'])}</code></td>"
        f"<td>{esc(c['kind'])}</td><td>{esc(c['label'])}</td></tr>"
        for c in labels.get("clips", []))

    scene_rows = "\n".join(
        f"<tr><td>{esc(s['scene_id'])}</td><td>{esc(s['location'])}</td>"
        f"<td>{esc(s['time_of_day'])}</td><td>{s['shot_count']}</td>"
        f"<td>{esc(s['summary'])}</td></tr>"
        for s in labels.get("scenes", []))

    path.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Labels — {esc(labels.get('story_id', ''))}</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:2rem;color:#222}}
 h1{{font-size:1.3rem}} h2{{font-size:1.05rem;margin-top:2rem}}
 table{{border-collapse:collapse;width:100%;font-size:.85rem}}
 th,td{{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}}
 code{{background:#f4f4f4;padding:0 3px}}
</style></head><body>
<h1>Labels Index — {esc(labels.get('story_id', ''))}</h1>
<p>generated {esc(labels.get('generated_at', ''))}</p>
<h2>Scenes</h2><table><tr><th>Scene</th><th>Location</th><th>Time</th><th>Shots</th><th>Summary</th></tr>
{scene_rows}</table>
<h2>Panels</h2><table><tr><th>Shot</th><th>File</th><th>Label</th></tr>
{panel_rows}</table>
<h2>Clips</h2><table><tr><th>Shot</th><th>File</th><th>Kind</th><th>Label</th></tr>
{clip_rows}</table>
</body></html>""", encoding="utf-8")


def write_labels(project_dir: str | Path) -> Path:
    """Build and write the labels index (json + txt + html) into the project
    root. This is the standard entry point — call it after panels or clips are
    produced. Returns the path to labels.json."""
    project_dir = Path(project_dir)
    labels = build_labels(project_dir)
    write_json(project_dir / _LABELS_JSON, labels)
    _write_txt(labels, project_dir / _LABELS_TXT)
    _write_html(labels, project_dir / _LABELS_HTML)
    logger.info("labels index written for %s (%d panels, %d clips)",
                project_dir.name, len(labels["panels"]), len(labels["clips"]))
    return project_dir / _LABELS_JSON
