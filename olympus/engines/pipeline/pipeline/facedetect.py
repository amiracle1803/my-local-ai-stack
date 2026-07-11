"""Anime-face bounding-box detector (design 3C.4).

Design 3C.4 (compositing pass, item 2) needs the "face + mouth bbox located
on the shot panel" before the Tier-3 lip-sync viseme flipbook can composite
mouth swaps onto a panel. The design names ``anime-face-detector`` (hysts) as
the reference tool, but that package pulls in mmcv/mmdet/mmpose -- a heavy,
version-picky stack that regularly breaks against current torch releases and
is not worth the maintenance cost for a bounding box.

Instead this module uses **nagadomi's ``lbpcascade_animeface``** LBP cascade
via OpenCV's ``cv2.CascadeClassifier``: one XML file, one lean dependency
(``opencv-python-headless``), no GPU, no version pinning against torch. It
returns a face bounding box per detected face; anime mouths are reliably in
the lower-third of the face box (limited animation only swaps that region),
so the mouth bbox is derived geometrically rather than detected separately --
which is exactly what design 3C.4 needs for the mouth-swap compositing pass.

Cascade file location:
``olympus/engines/pipeline/assets/lbpcascade_animeface.xml``. If missing,
download from:
https://raw.githubusercontent.com/nagadomi/lbpcascade_animeface/master/lbpcascade_animeface.xml
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CASCADE_PATH = ASSETS_DIR / "lbpcascade_animeface.xml"
CASCADE_URL = (
    "https://raw.githubusercontent.com/nagadomi/lbpcascade_animeface/"
    "master/lbpcascade_animeface.xml"
)

# Cascade tuning: anime faces are drawn less consistently than photo faces,
# so a smaller scale step and lower neighbor threshold than the OpenCV
# default (1.1 / 3) catch more real faces at the cost of a few extra
# false positives -- acceptable here since a human reviews/overrides bboxes
# in Studio UI per design 3C.4.
SCALE_FACTOR = 1.05
MIN_NEIGHBORS = 3
MIN_SIZE = (24, 24)


def _mouth_bbox(x: int, y: int, w: int, h: int) -> dict[str, int]:
    """Lower-third of the face box, centered, half the face width.

    Anime mouth animation only ever touches this region, so the mouth swap
    compositing pass (design 3C.4) can use it directly without a separate
    mouth detector.
    """
    mouth_h = h // 3
    mouth_w = w // 2
    mouth_x = x + (w - mouth_w) // 2
    mouth_y = y + h - mouth_h
    return {"x": mouth_x, "y": mouth_y, "w": mouth_w, "h": mouth_h}


def detect_faces(image_path: str | Path) -> list[dict[str, Any]]:
    """Detect anime face bounding boxes in ``image_path``.

    Returns a list of::

        {"x": int, "y": int, "w": int, "h": int,
         "mouth_bbox": {"x": int, "y": int, "w": int, "h": int}}

    one entry per detected face, in the pixel coordinates of the source
    image. Wide/establishing shots with no legible face may legitimately
    return an empty list.

    Raises:
        FileNotFoundError: if the source image or the cascade XML is
            missing. The cascade XML is not vendored in git (binary asset)
            and must be downloaded once to ``CASCADE_PATH`` -- see
            ``CASCADE_URL``.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    if not CASCADE_PATH.exists():
        raise FileNotFoundError(
            f"Anime face cascade not found at {CASCADE_PATH}. Download it with:\n"
            f"  curl -sL {CASCADE_URL} -o {CASCADE_PATH}"
        )

    classifier = cv2.CascadeClassifier(str(CASCADE_PATH))
    if classifier.empty():
        raise FileNotFoundError(
            f"Cascade file at {CASCADE_PATH} failed to load (corrupt/empty). "
            f"Re-download it with:\n  curl -sL {CASCADE_URL} -o {CASCADE_PATH}"
        )

    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not decode image: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    faces = classifier.detectMultiScale(
        gray,
        scaleFactor=SCALE_FACTOR,
        minNeighbors=MIN_NEIGHBORS,
        minSize=MIN_SIZE,
    )

    results: list[dict[str, Any]] = []
    for x, y, w, h in faces:
        x, y, w, h = int(x), int(y), int(w), int(h)
        results.append(
            {
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "mouth_bbox": _mouth_bbox(x, y, w, h),
            }
        )

    logger.info("detect_faces(%s): %d face(s)", image_path, len(results))
    return results
