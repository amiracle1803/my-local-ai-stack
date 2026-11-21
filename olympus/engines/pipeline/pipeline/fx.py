"""Pillow-only overlay generators: system window, caption, speed lines, thumbnail."""

from __future__ import annotations

import math
import random
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


@lru_cache(maxsize=1)
def _font_path() -> str | None:
    """Locate a bold TTF through fontconfig (cached)."""
    for family in ("DejaVu Sans:bold", "Noto Sans:bold"):
        try:
            out = subprocess.run(
                ["fc-match", "-f", "%{file}", family],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if out and Path(out).exists():
            return out
    return None


@lru_cache(maxsize=128)
def _font(size: int) -> Font:
    path = _font_path()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Font, max_w: int, stroke: int = 0) -> list[str]:
    """Greedy word wrap; over-long words are split by character."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        while draw.textlength(word, font=font) + 2 * stroke > max_w and len(word) > 1:
            cut = len(word)
            while cut > 1 and draw.textlength(word[:cut], font=font) + 2 * stroke > max_w:
                cut -= 1
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:cut])
            word = word[cut:]
        trial = f"{cur} {word}".strip()
        if cur and draw.textlength(trial, font=font) + 2 * stroke > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _fit(
    text: str, max_w: int, max_h: int, max_lines: int, start: int, min_size: int = 12,
    stroke_div: int = 0, line_gap: float = 1.15,
) -> tuple[Font, list[str], int, int]:
    """Shrink font until text fits; returns (font, lines, size, stroke). Truncates as last resort."""
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    size = start
    while True:
        font = _font(size)
        stroke = max(1, size // stroke_div) if stroke_div else 0
        lines = _wrap(probe, text, font, max_w, stroke)
        height = int(len(lines) * size * line_gap) + 2 * stroke
        if (len(lines) <= max_lines and height <= max_h) or size <= min_size:
            break
        size -= 2
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and probe.textlength(last + "...", font=font) + 2 * stroke > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "..."
    return font, lines, size, stroke


def _hex(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha


def system_window(text: str, dest: Path, width: int = 1920, height: int = 1080, title: str = "SYSTEM") -> Path:
    """Glowing holographic game-UI panel in the upper-middle of the frame."""
    cyan = _hex("#5FE3FF")
    pw = int(width * 0.46)
    pad = int(pw * 0.05)
    header_h = int(height * 0.06)
    body_start = max(20, int(height * 0.036))
    body_w = pw - 2 * pad
    max_body_h = int(height * 0.30)
    font, lines, size, _ = _fit(text, body_w, max_body_h, 4, body_start, line_gap=1.3)
    line_h = int(size * 1.3)
    ph = header_h + pad + line_h * len(lines) + pad
    x0 = (width - pw) // 2
    y0 = int(height * 0.10)
    box = (x0, y0, x0 + pw, y0 + ph)
    radius = max(10, int(height * 0.02))
    bw = max(3, height // 300)

    out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle(box, radius, outline=cyan, width=bw * 4)
    glow = glow.filter(ImageFilter.GaussianBlur(max(8, height // 70)))
    out.alpha_composite(glow)
    out.alpha_composite(glow)

    panel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle(box, radius, fill=(10, 20, 52, 190))
    out.alpha_composite(panel)
    hdr = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(hdr).rounded_rectangle(
        (x0, y0, x0 + pw, y0 + header_h), radius, fill=(40, 120, 180, 120), corners=(True, True, False, False),
    )
    out.alpha_composite(hdr)

    d = ImageDraw.Draw(out)
    d.rounded_rectangle(box, radius, outline=cyan, width=bw)
    # header: icon + title
    ir = int(header_h * 0.22)
    icx, icy = x0 + pad + ir, y0 + header_h // 2
    d.ellipse((icx - ir, icy - ir, icx + ir, icy + ir), outline=cyan, width=max(2, bw - 1))
    d.ellipse((icx - ir // 3, icy - ir // 3, icx + ir // 3, icy + ir // 3), fill=cyan)
    tfont = _font(max(14, int(header_h * 0.46)))
    d.text((icx + ir + pad // 2, icy), title.upper(), font=tfont, fill=cyan, anchor="lm")
    # divider
    dy = y0 + header_h
    d.line((x0 + pad // 2, dy, x0 + pw - pad // 2, dy), fill=_hex("#5FE3FF", 200), width=2)
    # body
    ty = dy + pad
    for ln in lines:
        d.text((x0 + pad, ty), ln, font=font, fill=(255, 255, 255, 255))
        ty += line_h
    return _save(out, dest)


def caption(
    text: str, dest: Path, width: int = 1920, height: int = 1080,
    color: str = "#FFD43B", position: str = "lower",
) -> Path:
    """Big bold uppercase impact caption with thick black stroke and soft shadow."""
    max_w = int(width * 0.86)
    start = int(height * 0.12)
    font, lines, size, stroke = _fit(
        text.upper(), max_w, int(height * 0.30), 2, start, min_size=16, stroke_div=9, line_gap=1.12,
    )
    line_h = int(size * 1.12)
    block_h = line_h * len(lines)
    y = int(height * 0.88) - block_h if position != "upper" else int(height * 0.08)
    y = max(stroke, y)

    def draw_lines(d: ImageDraw.ImageDraw, dx: int, dy: int, fill, stroke_fill, sw: int) -> None:
        for i, ln in enumerate(lines):
            d.text((width // 2 + dx, y + i * line_h + dy), ln, font=font, fill=fill,
                   stroke_width=sw, stroke_fill=stroke_fill, anchor="mt")

    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    off = max(3, size // 14)
    draw_lines(ImageDraw.Draw(shadow), off, off, (0, 0, 0, 200), (0, 0, 0, 200), stroke)
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, size // 18)))
    shadow.putalpha(shadow.getchannel("A").point(lambda v: min(255, int(v * 1.3))))
    out = shadow
    draw_lines(ImageDraw.Draw(out), 0, 0, _hex(color), (0, 0, 0, 255), stroke)
    return _save(out, dest)


def speed_lines(dest: Path, width: int = 1920, height: int = 1080, seed: int = 0, density: int = 140) -> Path:
    """Manga radial speed lines converging on the center, deterministic per seed."""
    rng = random.Random(seed)
    scale = 2  # supersample for smooth edges
    img = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = width * scale / 2, height * scale / 2
    far = math.hypot(cx, cy) * 1.05
    ry = height * scale * 0.35
    rx = ry * 1.6
    for _ in range(density):
        a = rng.uniform(0, 2 * math.pi)
        ca, sa = math.cos(a), math.sin(a)
        # radius of the clear ellipse along this direction
        inner = 1.0 / math.sqrt((ca / rx) ** 2 + (sa / ry) ** 2)
        start = inner + rng.uniform(0.0, 0.35) * (far - inner)
        length = rng.uniform(0.25, 0.65) * (far - inner)
        end = min(far, start + length)
        half = rng.uniform(0.002, 0.011)  # angular half-width of the wedge
        alpha = rng.randint(90, 200)
        p_far = (cx + ca * end, cy + sa * end)
        # wedge: wide at the outside, tapering to a point toward the center
        a1, a2 = a - half, a + half
        p1 = (cx + math.cos(a1) * end, cy + math.sin(a1) * end)
        p2 = (cx + math.cos(a2) * end, cy + math.sin(a2) * end)
        tip = (cx + ca * start, cy + sa * start)
        d.polygon([tip, p1, p2], fill=(255, 255, 255, alpha))
        _ = p_far
    img = img.resize((width, height), Image.LANCZOS)
    return _save(img, dest)


def _vignette(size: tuple[int, int], strength: float = 0.75) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((-w * 0.25, -h * 0.35, w * 1.25, h * 1.35), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 6))
    dark = Image.new("RGBA", size, (0, 0, 0, int(255 * strength)))
    dark.putalpha(mask.point(lambda v: int((255 - v) * strength)))
    return dark


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def thumbnail(image: Path, title: str, dest: Path, episode: int | None = None) -> Path:
    """1280x720 clickbait thumbnail: punchy background, huge two-colour title, episode number."""
    w, h = 1280, 720
    bg = _cover(Image.open(image).convert("RGB"), w, h)
    bg = ImageEnhance.Color(bg).enhance(1.35)
    bg = ImageEnhance.Contrast(bg).enhance(1.15)
    canvas = bg.convert("RGBA")
    canvas.alpha_composite(_vignette((w, h)))

    words = title.upper().split()
    if len(words) >= 2:
        # split into two balanced lines by character count
        best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        parts = [" ".join(words[:best]), " ".join(words[best:])]
    else:
        parts = [title.upper()]
    max_w = int(w * 0.62)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    size = 150
    while size > 20:
        f = _font(size)
        if max(probe.textlength(p, font=f) for p in parts) + 20 <= max_w and size * 1.1 * len(parts) <= h * 0.7:
            break
        size -= 2
    font = _font(size)
    stroke = max(6, min(10, size // 8))
    colors = [_hex("#FF3B30"), _hex("#FFD43B")]

    def render(layer: Image.Image, dx: int, dy: int, shadow: bool) -> None:
        d = ImageDraw.Draw(layer)
        for i, p in enumerate(parts):
            fill = (0, 0, 0, 200) if shadow else colors[i % 2]
            d.text((40 + dx, 36 + dy + i * int(size * 1.08)), p, font=font, fill=fill,
                   stroke_width=stroke, stroke_fill=(0, 0, 0, 255))

    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    render(sh, 8, 8, True)
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)))
    top = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    render(top, 0, 0, False)
    canvas.alpha_composite(top)

    if episode is not None:
        num = str(int(episode))
        esize = 260
        while esize > 40:
            ef = _font(esize)
            if probe.textlength(num, font=ef) <= w * 0.28:
                break
            esize -= 4
        ef = _font(esize)
        est = max(8, esize // 14)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((w - 40 + 8, 20 + 8), num, font=ef, fill=(0, 0, 0, 200), anchor="ra",
                stroke_width=est, stroke_fill=(0, 0, 0, 200))
        canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(4)))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((w - 40, 20), num, font=ef, fill=_hex("#FFD43B"), anchor="ra",
                                   stroke_width=est, stroke_fill=(0, 0, 0, 255))
        canvas.alpha_composite(layer)

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(dest, "PNG")
    return dest


def _save(img: Image.Image, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")
    return dest
