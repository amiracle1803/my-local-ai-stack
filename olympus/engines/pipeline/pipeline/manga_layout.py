"""Manga vertical layout — composite each block's panels into a manga page.

Since we assemble panels (no animation), the story reads best as a manga page:
panels stacked one-under-the-other in story order, exactly like a webtoon /
vertical-scroll manga. Individual panels stay untouched (the video assembly
uses them for Ken Burns); the composite is an extra deliverable plus a
source-of-truth page for the storyboard viewer.

Outputs per block:
  panels/<block_id>_manga.png      — vertical strip of that block's panels
  panels/manga.json                — page index: block → shot order → panel files
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PAGE_GAP = 12          # px gap between stacked panels
_BG = (20, 24, 32)      # dark page background between panels


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


def _stack_vertical(paths: list[Path], out_path: Path, gap: int = _PAGE_GAP) -> Path | None:
    """Paste the panels one-under-the-other (fixed-width canvas, tallest wins),
    writing the composite to ``out_path``. Returns the path, or None on failure."""
    try:
        from PIL import Image
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

    # Fixed width = the widest panel; each panel is center-anchored on the strip.
    width = max(im.width for im in images)
    height = sum(im.height for im in images) + gap * (len(images) - 1)
    page = Image.new("RGB", (width, height), _BG)
    y = 0
    for im in images:
        x = (width - im.width) // 2
        page.paste(im, (x, y))
        y += im.height + gap

    page.save(out_path)
    return out_path


def build_manga_pages(project_dir: str | Path, storyboard: dict[str, Any]) -> dict[str, Any]:
    """Build the vertical manga composite for every block in the storyboard.

    Returns ``{"pages": [{block, file, shots, panels}], "root": "<project>"}``
    suitable for ``panels/manga.json``. Missing panels are logged and skipped.
    """
    project_dir = Path(project_dir)
    project = identity_code(project_dir)
    pages: list[dict[str, Any]] = []

    for block in storyboard.get("blocks", []):
        shots = block.get("shots", [])
        block_dir = project_dir / "panels" / block["id"]
        if not block_dir.exists():
            continue
        paths = _panel_paths(block_dir, shots, project)
        if not paths:
            continue
        out = block_dir / f"{block['id']}_manga.png"
        if _stack_vertical(paths, out):
            pages.append({
                "block": block["id"],
                "file": str(out.relative_to(project_dir)),
                "shots": shots,
                "panels": [str(p.relative_to(project_dir)) for p in paths],
            })

    index = {"root": project, "pages": pages}
    (project_dir / "panels" / "manga.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if pages:
        logger.info("manga layout: composited %d page(s) for %s", len(pages), project)
    return index


def identity_code(project_dir: Path) -> str:
    """Small local copy of identity.project_code to avoid a circular import."""
    from . import identity

    return identity.project_code(project_dir)