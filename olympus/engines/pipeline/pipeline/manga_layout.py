"""Manga vertical layout — composite each block's panels into manga pages.

Since we assemble panels (no animation), the story reads best as manga pages:
panels stacked one-under-the-other in story order, exactly like a webtoon /
vertical-scroll manga. Individual panels stay untouched (the video assembly
uses them for Ken Burns); the composite is an extra deliverable plus a
source-of-truth page for the storyboard viewer.

Pages are built in layers (design: background -> characters -> text):

1. **Background pass** — the page canvas is filled with the scene plate
   (``panels/<block>/_plates/<scene>.png``), cover-fit, so every page sits on
   its scene's own background.
2. **Character pass** — the rendered panels (characters + action) are pasted
   in as bordered manga frames, stacked top-to-bottom.
3. **Text pass** — narration boxes and dialogue speech bubbles are drawn with
   PIL directly from the screenplay text, so spelling is always correct (never
   AI-generated gibberish). Only shots that carry narration/dialogue get a box.

A page never stacks more than ``_PANELS_PER_PAGE`` panels, and scenes are kept
together (a block spanning several scenes splits into per-scene pages first).

Outputs per block:
  panels/<block_id>_manga_p01.png    — page 1 (<=3 panels, layered composite)
  panels/<block_id>_manga_p02.png    — page 2, ...
  panels/manga.json                  — page index: block -> page -> shots -> files
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PANELS_PER_PAGE = 3    # hard cap: no more than 3 panels stacked per page
_PAGE_GAP = 14          # px gap between stacked panels
_PAGE_MARGIN = 18       # px page margin around the panel column
_BG = (20, 24, 32)      # dark page background when no plate is available
_BORDER_W = 4           # manga frame border drawn around each pasted panel

# Text-box styling (manga narration box + speech bubble).
_TEXT_BG = (255, 252, 240)   # warm paper white (narration box)
_TEXT_BORDER = (30, 30, 30)
_TEXT_FG = (30, 30, 30)
_DIALOGUE_BG = (255, 255, 255)
_BOX_RADIUS = 12
_BOX_PAD = 14           # inner padding of a text box
_LINE_GAP = 6           # extra vertical space between wrapped lines
_TAIL = 18              # speech-bubble tail length

_FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/google-noto/NotoSans-CondensedBlack.ttf",
    "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
_FONT_SIZE = 22


def _find_font() -> str | None:
    """First existing font path from the candidates, or None."""
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def _font(size: int = _FONT_SIZE):
    """Load the bold manga-style font at ``size`` (default bitmap fallback)."""
    from PIL import ImageFont

    path = _find_font()
    if path is None:
        logger.warning("manga layout: no TrueType font found; text uses default bitmap font")
        return ImageFont.load_default()
    return ImageFont.truetype(path, size)


def _panel_paths(block_dir: Path, shots: list[str], project: str) -> list[Path]:
    """Resolve the rendered panel PNG for each shot in story order.

    Panels are named with the canonical identity pattern
    ``{project}_sc001_sh001_pn01_render_v001.png``; fall back to any PNG whose
    name embeds the shot id for legacy projects.
    """
    from . import identity

    out: list[Path] = []
    for sid in shots:
        canonical = identity.canonical_shot_id(sid, project)
        matches = sorted(block_dir.glob(f"{canonical}_pn*.png"))
        if not matches and canonical != sid:
            matches = sorted(block_dir.glob(f"{sid}_pn*.png"))
        if matches:
            out.append(matches[0])
        else:
            logger.warning("manga layout: no panel found for %s in %s", sid, block_dir.name)
    return out


def _shots_by_scene(project_dir: Path, storyboard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map scene id -> {scene, shots_by_id} from the screenplay (authoritative)
    with the storyboard's embedded scenes as a fallback (test fixtures)."""
    lookup: dict[str, dict[str, Any]] = {}
    scenes: list[Any] = []

    sp = project_dir / "screenplay" / "screenplay.json"
    if sp.exists():
        try:
            screenplay = json.loads(sp.read_text(encoding="utf-8"))
            scenes.extend(screenplay.get("scenes", []))
        except (OSError, ValueError) as exc:
            logger.warning("manga layout: screenplay unreadable (%s): %s", sp, exc)
    scenes.extend(storyboard.get("scenes", []))

    for scene in scenes:
        sid = scene.get("id")
        if not sid:
            continue
        shots_by_id = {sh["id"]: sh for sh in scene.get("shots", [])}
        lookup.setdefault(sid, {"scene": scene, "shots": shots_by_id})
    return lookup


def _chunk_pages(shots: list[str], scene_lookup) -> list[dict[str, Any]]:
    """Split a block's shots into pages: scenes stay together and every page
    has at most ``_PANELS_PER_PAGE`` panels."""
    pages: list[dict[str, Any]] = []
    current_scene: str | None = None
    current: list[str] = []
    for sid in shots:
        scene = _scene_for_shot(sid, scene_lookup)
        if scene is not None and scene != current_scene and current:
            # scene boundary -> flush, then start a fresh page
            pages.extend(_chunk_cap(current))
            current = []
        current_scene = scene
        current.append(sid)
    pages.extend(_chunk_cap(current))
    return pages


def _chunk_cap(sids: list[str]) -> list[dict[str, Any]]:
    """Chunk one scene's shot list into pages of at most ``_PANELS_PER_PAGE``."""
    return [{"shots": sids[i:i + _PANELS_PER_PAGE]}
            for i in range(0, len(sids), _PANELS_PER_PAGE)]


def _scene_for_shot(sid: str, scene_lookup):
    """The scene dict containing ``sid`` (or None)."""
    from . import identity

    canon = identity.scene_id_from_shot(sid)          # sc001
    for sc_id, entry in scene_lookup.items():
        if sc_id == canon or sc_id.replace("-", "") == canon.replace("-", ""):
            if sid in entry["shots"]:
                return entry
    return None


def _plate_path(block_dir: Path, scene, project: str) -> Path | None:
    """The scene plate for a page background (legacy or canonical name)."""
    from . import identity

    plate_dir = block_dir / "_plates"
    if scene is None:
        return None
    sid = scene["id"]
    cands = [plate_dir / f"{sid}.png"]
    if project:
        cands.append(plate_dir / identity.artifact_name(
            f"{project}_{sid.replace('sc-', 'sc')}", "plate", version=1, ext="png"
        ))
    for c in cands:
        if c.exists():
            return c
    return None


def _cover(img, w: int, h: int):
    """Resize ``img`` to cover ``(w, h)`` and center-crop into it (RGB)."""
    from PIL import Image

    src = img.convert("RGB")
    scale = max(w / src.width, h / src.height)
    rw, rh = max(1, round(src.width * scale)), max(1, round(src.height * scale))
    src = src.resize((rw, rh), Image.LANCZOS)
    x = (rw - w) // 2
    y = (rh - h) // 2
    return src.crop((x, y, x + w, y + h))


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    """Word-wrap ``text`` to fit ``max_w`` px with ``draw.textlength``."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _rounded_box(draw, x0: int, y0: int, x1: int, y1: int, *, radius: int,
                 fill: tuple[int, int, int], outline: tuple[int, int, int],
                 width: int = 3) -> None:
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius,
                           fill=fill, outline=outline, width=width)


def _box_h(font, lines: list[str]) -> int:
    return len(lines) * (font.size + _LINE_GAP) + 2 * _BOX_PAD


def _fit_text(draw, text: str, max_w: int, max_h: int) -> tuple[Any, list[str]]:
    """Largest font whose wrapped text fits ``max_w`` x ``max_h``.

    Long narration previously overflowed the panel region (NIM calibration
    flagged "text cut off at the bottom of the page"). Shrink the font until
    the wrapped lines fit, floored at 12px; if even that is too tall, hard-
    clamp by truncating lines with an ellipsis so a box NEVER overflows the
    region (better a clean cut than bleeding into the next panel)."""
    size = _FONT_SIZE
    while size >= 12:
        font = _font(size)
        lines = _wrap(draw, text, font, max_w)
        if _box_h(font, lines) <= max_h:
            return font, lines
        size -= 2
    font = _font(12)
    lines = _wrap(draw, text, font, max_w)
    while lines and _box_h(font, lines) > max_h:
        lines = lines[:-1]
    if not lines:
        lines = ["…"]
    else:
        lines[-1] = lines[-1].rstrip() + "…"
    return font, lines


def _draw_narration(draw, region: tuple[int, int, int, int], text: str) -> None:
    """Top-right paper-white narration box (no tail), wrapped to fit the panel."""
    rx0, ry0, rx1, ry1 = region
    max_w = max(80, (rx1 - rx0) - 4 * _BOX_PAD)
    max_h = max(40, (ry1 - ry0) - 2 * _BOX_PAD)
    font, lines = _fit_text(draw, text, max_w, max_h)
    line_h = font.size + _LINE_GAP
    box_w = max(int(max(draw.textlength(ln, font=font) for ln in lines)), 0) + 2 * _BOX_PAD
    box_h = _box_h(font, lines)
    bx1 = rx1 - _BOX_PAD
    bx0 = bx1 - box_w
    by0 = ry0 + _BOX_PAD
    by1 = by0 + box_h
    _rounded_box(draw, bx0, by0, bx1, by1, radius=_BOX_RADIUS,
                 fill=_TEXT_BG, outline=_TEXT_BORDER)
    y = by0 + _BOX_PAD
    for ln in lines:
        draw.text((bx0 + _BOX_PAD, y), ln, font=font, fill=_TEXT_FG)
        y += line_h


def _draw_dialogue(draw, region: tuple[int, int, int, int], speaker: str,
                   text: str) -> None:
    """Bottom speech bubble (white, with a small tail) for a dialogue line."""
    rx0, ry0, rx1, ry1 = region
    label = f"{speaker}: {text}" if speaker else text
    # the tail hangs below the box; keep it inside the panel region.
    max_w = max(80, (rx1 - rx0) - 4 * _BOX_PAD)
    max_h = max(40, (ry1 - ry0) - 2 * _BOX_PAD - _TAIL)
    font, lines = _fit_text(draw, label, max_w, max_h)
    line_h = font.size + _LINE_GAP
    widths = [draw.textlength(ln, font=font) for ln in lines]
    box_w = max(int(max(widths)), 0) + 2 * _BOX_PAD
    box_h = _box_h(font, lines)
    cx = (rx0 + rx1) // 2
    bx0 = max(rx0 + 2, cx - box_w // 2)
    bx1 = min(rx1 - 2, bx0 + box_w)
    by1 = ry1 - _BOX_PAD - _TAIL
    by0 = by1 - box_h
    _rounded_box(draw, bx0, by0, bx1, by1, radius=_BOX_RADIUS,
                 fill=_DIALOGUE_BG, outline=_TEXT_BORDER)
    # small downward tail centered at the bubble base.
    tx = (bx0 + bx1) // 2
    draw.polygon([(tx, by1), (tx - _TAIL // 2, by1 + _TAIL), (tx + _TAIL // 2, by1 + _TAIL)],
                 fill=_DIALOGUE_BG, outline=_TEXT_BORDER)
    y = by0 + _BOX_PAD
    for ln in lines:
        draw.text((bx0 + _BOX_PAD, y), ln, font=font, fill=_TEXT_FG)
        y += line_h


def _build_page(
    paths: list[Path],
    shot_meta: list[dict[str, Any]],
    out_path: Path,
    plate: Path | None,
) -> Path | None:
    """Composite one page: plate background -> bordered panels -> text boxes."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("PIL unavailable — skipping manga composite %s", out_path.name)
        return None

    try:
        images = [Image.open(p).convert("RGB") for p in paths]
    except OSError as exc:
        logger.warning("manga layout: could not open panels for %s: %s", out_path.name, exc)
        return None
    if not images:
        return None

    panel_w = max(im.width for im in images)
    content_h = sum(im.height for im in images) + _PAGE_GAP * (len(images) - 1)
    page_w = panel_w + 2 * _PAGE_MARGIN
    page_h = content_h + 2 * _PAGE_MARGIN

    page = Image.new("RGB", (page_w, page_h), _BG)
    if plate is not None:
        try:
            bg = _cover(Image.open(plate), page_w, page_h)
            page.paste(bg, (0, 0))
        except OSError as exc:
            logger.warning("manga layout: plate %s unreadable: %s", plate, exc)

    draw = ImageDraw.Draw(page)
    y = _PAGE_MARGIN
    for idx, im in enumerate(images):
        x = _PAGE_MARGIN + (panel_w - im.width) // 2
        page.paste(im, (x, y))
        region = (x, y, x + im.width, y + im.height)
        # manga frame border around the pasted panel.
        draw.rectangle(region, outline=(15, 15, 18), width=_BORDER_W)

        meta = shot_meta[idx] if idx < len(shot_meta) else {}
        narration = (meta.get("narration") or {}).get("text")
        dialogue = meta.get("dialogue") or []
        if narration:
            _draw_narration(draw, region, narration)
        if dialogue:
            _draw_dialogue(draw, region, dialogue[0].get("char_id", ""),
                           dialogue[0].get("text", ""))
        y += im.height + _PAGE_GAP

    page.save(out_path)
    return out_path


def build_manga_pages(project_dir: str | Path, storyboard: dict[str, Any]) -> dict[str, Any]:
    """Build paginated, layered manga composites for every block.

    Pages keep scenes together and cap at ``_PANELS_PER_PAGE`` stacked panels.
    Returns ``{"pages": [{block, page, scene, file, shots, panels}], "root": ...}``
    suitable for ``panels/manga.json``. Missing panels are logged and skipped.
    """
    project_dir = Path(project_dir)
    project = identity_code(project_dir)
    scene_lookup = _shots_by_scene(project_dir, storyboard)
    pages: list[dict[str, Any]] = []

    for block in storyboard.get("blocks", []):
        shots = block.get("shots", [])
        block_dir = project_dir / "panels" / block["id"]
        if not block_dir.exists():
            continue
        paths = _panel_paths(block_dir, shots, project)
        if not paths:
            continue
        plan = _chunk_pages(shots, scene_lookup)
        for page_no, chunk in enumerate(plan, start=1):
            page_shots = chunk["shots"]
            idx = {sid: i for i, sid in enumerate(shots)}
            page_paths = [paths[idx[sid]] for sid in page_shots if sid in idx]
            if not page_paths:
                continue
            scene_entry = _scene_for_shot(page_shots[0], scene_lookup)
            scene = scene_entry["scene"] if scene_entry else None
            plate = _plate_path(block_dir, scene, project)
            meta = []
            for sid in page_shots:
                shot = scene_entry["shots"].get(sid, {}) if scene_entry else {}
                meta.append(shot)
            out = block_dir / f"{block['id']}_manga_p{page_no:02d}.png"
            if _build_page(page_paths, meta, out, plate):
                pages.append({
                    "block": block["id"],
                    "page": page_no,
                    "scene": scene["id"] if scene else None,
                    "file": str(out.relative_to(project_dir)),
                    "shots": page_shots,
                    "panels": [str(p.relative_to(project_dir)) for p in page_paths],
                })

    index = {"root": project, "pages": pages}
    panels_root = project_dir / "panels"
    panels_root.mkdir(parents=True, exist_ok=True)
    (panels_root / "manga.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if pages:
        logger.info("manga layout: composited %d page(s) for %s", len(pages), project)
    return index


def identity_code(project_dir: Path) -> str:
    """Small local copy of identity.project_code to avoid a circular import."""
    from . import identity

    return identity.project_code(project_dir)