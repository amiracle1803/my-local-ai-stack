#!/usr/bin/env python3
"""Generate viseme mouth masks for lip-sync inpaint.

Creates 9 white-on-black PNG masks (512x512) for each Preston Blair viseme class:
A, E, I, O, U, M, F, L, REST

Masks define the mouth region to inpaint for each viseme shape.
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

OUTPUT_DIR = Path("ComfyUI/input/masks")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Base face proportions (512x512 canvas)
CANVAS = 512
# Mouth region: roughly lower third of face, centered horizontally
MOUTH_CX = CANVAS // 2
MOUTH_CY = int(CANVAS * 0.65)
MOUTH_W = int(CANVAS * 0.35)
MOUTH_H = int(CANVAS * 0.15)

# Viseme-specific mouth shapes (relative to mouth region)
# Each defines an ellipse/rectangle for the mouth opening
_VISEME_SHAPES = {
    "A": {"type": "ellipse", "w": 0.9, "h": 0.85},   # wide open, tall
    "E": {"type": "ellipse", "w": 0.95, "h": 0.45},  # wide, short
    "I": {"type": "ellipse", "w": 0.85, "h": 0.4},   # wide, very short
    "O": {"type": "ellipse", "w": 0.45, "h": 0.7},   # round
    "U": {"type": "ellipse", "w": 0.35, "h": 0.6},   # small circle
    "M": {"type": "rect", "w": 0.7, "h": 0.08},      # thin line (closed)
    "F": {"type": "ellipse", "w": 0.5, "h": 0.35},   # upper teeth on lip
    "L": {"type": "ellipse", "w": 0.55, "h": 0.3},   # tongue behind teeth
    "REST": {"type": "rect", "w": 0.65, "h": 0.1},   # relaxed closed
}


def draw_viseme_mask(viseme: str) -> Image.Image:
    """Draw a single viseme mask as white shape on black background."""
    img = Image.new("L", (CANVAS, CANVAS), 0)  # black background
    draw = ImageDraw.Draw(img)

    shape = _VISEME_SHAPES.get(viseme, _VISEME_SHAPES["REST"])

    # Calculate bounding box centered on mouth region
    left = MOUTH_CX - int(MOUTH_W * shape["w"] / 2)
    top = MOUTH_CY - int(MOUTH_H * shape["h"] / 2)
    right = MOUTH_CX + int(MOUTH_W * shape["w"] / 2)
    bottom = MOUTH_CY + int(MOUTH_H * shape["h"] / 2)

    if shape["type"] == "ellipse":
        draw.ellipse([left, top, right, bottom], fill=255)
    elif shape["type"] == "rect":
        draw.rectangle([left, top, right, bottom], fill=255)

    # Add slight feathering for natural blend
    # Convert to RGBA, apply Gaussian blur, then back to L
    img_rgba = img.convert("RGBA")
    # Create feathered version
    from PIL import ImageFilter
    feathered = img.filter(ImageFilter.GaussianBlur(radius=3))
    # Threshold to keep shape crisp but edges soft
    feathered = feathered.point(lambda x: 255 if x > 64 else 0)
    return feathered.convert("L")


def main():
    for viseme in ["A", "E", "I", "O", "U", "M", "F", "L", "REST"]:
        mask = draw_viseme_mask(viseme)
        out_path = OUTPUT_DIR / f"viseme_{viseme}.png"
        mask.save(out_path)
        print(f"Generated {out_path}")

    print(f"\nAll 9 viseme masks written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()