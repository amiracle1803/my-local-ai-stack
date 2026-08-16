"""V-JEPA2 perceptual similarity for the vision/consistency layer.

facebook/vjepa2-vitl-fpc64-256 is a self-supervised ViT feature extractor
(no chat/instruction interface). We use its pooled patch embeddings for what
it is actually good at -- deterministic perceptual similarity between images:

- background gate: does a shot panel share its scene's master plate location?
  (cosine similarity of the mean-pooled patch embeddings, replacing the VLM's
  hand-wavy "does the background match?" answer for the hard gate)
- cross-shot character/ref consistency (stage_vlm_review later).

The model is loaded lazily and released after each batch so it never sits in
VRAM alongside Ollama or ComfyUI generation (AGENTS.md GPU scheduling rules).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MODEL_ID = "facebook/vjepa2-vitl-fpc64-256"


class JEPA2:
    """Lazy, per-batch V-JEPA2 embedder. Use as a context manager; the model
    is freed (and VRAM released) on exit so it coexists with the pipeline's
    GPU-scheduling rules."""

    def __init__(self) -> None:
        self._model = None
        self._processor = None

    def _load(self) -> None:
        import torch  # heavy import kept lazy so non-GPU paths don't pull it

        from transformers import VJEPA2Model, VJEPA2VideoProcessor

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._processor = VJEPA2VideoProcessor.from_pretrained(_MODEL_ID)
        self._model = VJEPA2Model.from_pretrained(_MODEL_ID).to(self._device).eval()
        self._torch = torch

    def embed(self, path: str | Path) -> list[float]:
        """Return a normalized (1024,) mean-pooled embedding for one image."""
        from PIL import Image

        if self._model is None:
            self._load()
        img = Image.open(path).convert("RGB")
        feat = self._processor(videos=[img], return_tensors="pt")
        feat = {
            k: v.to(self._device) if hasattr(v, "to") else v for k, v in feat.items()
        }
        with self._torch.no_grad():
            out = self._model(**feat)
        emb = out.last_hidden_state.mean(dim=1)[0]  # (1024,)
        emb = emb / emb.norm(p=2, dim=0).clamp_min(1e-8)
        return emb.tolist()

    def __enter__(self) -> "JEPA2":
        return self

    def __exit__(self, *exc) -> None:
        if self._model is not None:
            del self._model
            self._model = None
            self._processor = None
            self._torch.cuda.empty_cache()
            self._torch = None
            logger.info("vjepa2 model freed")


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two (1024,) normalized embeddings."""
    return sum(x * y for x, y in zip(a, b))
