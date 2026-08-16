"""Real-ESRGAN anime upscale for LTX clips (stage3c post-process).

Replaces the cheap ffmpeg ``scale=1.5,unsharp`` upscale in
``stage3c._postprocess_clip`` with a true AI upscale via the
``realesrgan-ncnn-vulkan`` binary (ncnn/Vulkan build, no torch dependency).

The 768x448 LTX render is upscaled 2x to 1536x896, which is then *larger*
than the 1280x720 delivery timeline, so stage5_assembly downscales it --
downsampling is far sharper than the old upsampling-into-the-timeline path.

Only triggered when ``[animation].ai_upscale`` is true (stack.toml) and the
binary is on disk. Falls back to a no-op (returns None) on ANY failure --
the caller keeps its existing ffmpeg path, never better, as before.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_BIN = Path.home() / ".local/bin/realesrgan-ncnn-vulkan"
_MODELS_DIR = Path.home() / ".local/share/realesrgan/models/"
_TILE = 128
_THREADS = "4:4:2"
_FRAMERATE = 16


def available() -> bool:
    """True iff the ncnn binary and the animevideo model weights are present."""
    return (
        _BIN.exists()
        and (_MODELS_DIR / "realesr-animevideov3-x2.param").exists()
        and (_MODELS_DIR / "realesr-animevideov3-x2.bin").exists()
    )


def upscale_clip(
    clip_path: Path,
    scale: int = 2,
    model: str = "realesr-animevideov3-x2",
) -> Path | None:
    """Upscale ``clip_path`` in place with Real-ESRGAN, replacing the file
    content and returning it. Returns None on any failure so callers fall
    back to their non-AI path. Frames are extracted and re-encoded with
    ffmpeg; the model renders each frame via the ncnn Vulkan binary.
    """
    if not clip_path.exists():
        return None
    with tempfile.TemporaryDirectory(prefix="esr_") as tmp:
        tmpdir = Path(tmp)
        frames_in = tmpdir / "in"
        frames_out = tmpdir / "out"
        final = tmpdir / "final.mp4"
        frames_in.mkdir()

        try:
            # 1. extract frames at source fps (16) as PNGs f00001.png ...
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(clip_path), "-vsync", "0",
                 str(frames_in / "f%05d.png")],
                capture_output=True, timeout=300, check=True,
            )
            n_frames_in = len(list(frames_in.glob("f*.png")))
            if n_frames_in == 0:
                logger.warning("ai upscale found no frames in %s", clip_path.name)
                return None

            # 2. AI upscale every frame with the validated model path (-m).
            frames_out.mkdir()
            subprocess.run(
                [str(_BIN), "-i", str(frames_in), "-o", str(frames_out),
                 "-s", str(scale), "-n", model, "-m", str(_MODELS_DIR),
                 "-t", str(_TILE), "-j", _THREADS],
                capture_output=True, timeout=1800, check=True,
            )
            subs = sorted(frames_out.glob("f*.png"))
            if not subs:
                logger.warning("ai upscale produced no frames for %s", clip_path.name)
                return None

            # 3. re-encode the upscaled PNGs back to an identical-length clip.
            subprocess.run(
                ["ffmpeg", "-y", "-framerate", str(_FRAMERATE), "-i",
                 str(frames_out / "f%05d.png"),
                 "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                 "-pix_fmt", "yuv420p", str(final)],
                capture_output=True, timeout=1800, check=True,
            )
            if not final.exists():
                logger.warning("ai upscale encode produced nothing for %s", clip_path.name)
                return None

            # 4. replace the original clip with the upscaled one. The temp
            #    dirs above live under /tmp, which can be a different
            #    filesystem than the project clips dir -- a cross-device
            #    rename raises EXDEV (Errno 18), so stage the final clip to a
            #    sibling on the SAME filesystem first, then os.replace
            #    (atomic). The original is never unlinked until the staged
            #    replacement exists, keeping the non-AI clip on any failure.
            staged = clip_path.with_name(f".{clip_path.stem}.esr{clip_path.suffix}")
            shutil.copy2(final, staged)
            os.replace(staged, clip_path)
            logger.info(
                "ai upscale %s: %d frames -> %d frames, %s",
                clip_path.name, n_frames_in, len(subs), clip_path,
            )
            return clip_path
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            logger.warning(
                "ai upscale failed for %s (keeping non-AI clip): %s",
                clip_path.name, exc,
            )
            return None
