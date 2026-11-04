"""Deterministic anime-style placeholder art (PIL, no GPU needed).

Keeps the Studio pipeline fully local and offline-capable: every panel
and reference is a 1280x720 composition with gradient sky, sun/moon disc,
speed-line accents, and the shot/character text baked in. When ComfyUI is
configured later, stage3b can swap ``render_panel`` for diffusion output
without changing any JSON contract.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720


def _palette(seed: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    tops = [(38, 52, 110), (86, 36, 96), (24, 78, 100), (96, 44, 62), (30, 60, 60)]
    bots = [(150, 120, 190), (235, 150, 130), (130, 200, 220), (240, 190, 140), (160, 220, 190)]
    return tops[h % len(tops)], bots[(h // 7) % len(bots)]


def _font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        for p in (f"/usr/share/fonts/truetype/dejavu/{name}", f"/usr/share/fonts/{name}"):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:8]


def render_panel(path: Path, title: str, subtitle: str = "", body: str = "", seed: str = "panel") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    top, bot = _palette(seed)
    img = Image.new("RGB", (W, H), top)
    px = img.load()
    for y in range(H):
        t = y / H
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        for x in range(0, W, 4):
            px[x, y] = (r, g, b)
            if x + 1 < W:
                px[x + 1, y] = (r, g, b)
            if x + 2 < W:
                px[x + 2, y] = (r, g, b)
            if x + 3 < W:
                px[x + 3, y] = (r, g, b)
    d = ImageDraw.Draw(img)
    cx, cy = int(W * 0.78), int(H * 0.30)
    for rad, col in ((120, (255, 240, 200)), (90, (255, 250, 225)), (60, (255, 255, 245))):
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=col)
    for i in range(24):
        x0 = (i * 173) % W
        d.line([x0, 0, x0 + 60, H], fill=(255, 255, 255, 40), width=1)
    d.rectangle([24, 24, W - 24, H - 24], outline=(255, 255, 255), width=3)
    y = 70
    for line, size in ((title, 54), (subtitle, 34)):
        if not line:
            continue
        f = _font(size)
        for ln in _wrap(d, line[:160], f, W - 160):
            d.text((70, y), ln, font=f, fill=(255, 255, 255),
                   stroke_width=2, stroke_fill=(10, 10, 30))
            y += size + 12
    if body:
        f = _font(28)
        y += 10
        for ln in _wrap(d, body[:420], f, W - 160):
            d.text((70, y), ln, font=f, fill=(240, 240, 255),
                   stroke_width=1, stroke_fill=(10, 10, 30))
            y += 40
    d.text((70, H - 60), "OLYMPUS STUDIO · local render", font=_font(22), fill=(220, 220, 235))
    img.save(path, "PNG")
    return path
