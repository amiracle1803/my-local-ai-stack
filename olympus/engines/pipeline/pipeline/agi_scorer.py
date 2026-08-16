"""AGI script scorer — vendored AGI Brain V3 relationship scoring.

Sits on top of the Ollama script stages (stage0 / stage2). Where the LLM
*generates* prose, this model *scores* semantic relationships between two
texts using its dedicated heads (trained relationship classifier, not a
generator):

- ``fidelity``      -- SAME head: does generated scene prose deliver the
  blueprint beat it was written from?
- ``causal_flow``   -- CAUSE head: does scene N plausibly lead into scene N+1?
- ``consistency``   -- SAME head: does a character's scene writing stay
  consistent with their profile in the blueprint?

The checkpoint + model definition are vendored copies from the AGI Brain
training project (``agi_checkpoint_v3_fixed_best.pt``, ``agi_brain_v3.py``).
Loading is lazy and never fails a stage: if the scorer is disabled, the
checkpoint is missing, or torch/sentence-transformers are unavailable, the
scoring methods return ``None`` and the caller records no metric.

GPU rule (AGENTS.md): this scorer must not OOM Ollama/ComfyUI. ``device``
defaults to ``auto``, which only uses CUDA when at least
``min_vram_free_mb`` is free; otherwise it falls back to CPU. Scoring is
cheap (one tiny SBERT encode + a ~260M-param forward per pair), so CPU is
fine for the handful of pairs a stage scores.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import torch
import torch.nn.functional as F

from .config import AgiConfig, STACK_ROOT

logger = logging.getLogger(__name__)

# Relationship score ranges the model was trained toward (from the AGI
# project's eval gate) -- used only to normalize/normalize documentation.
SAME_RANGE = (0.7, 1.0)
CAUSE_RANGE = (0.5, 0.85)

_SBERT_ENCODER = "all-MiniLM-L6-v2"  # fallback if config empty


def scorer_enabled(config: AgiConfig) -> bool:
    """Whether AGI scoring is active. ``AGI_SCORER_ENABLED`` env var overrides
    the config so tests/CI can disable it without touching stack.toml. Honored
    values: 0/false/no/off -> off; 1/true/yes/on -> on; unset -> config."""
    env = os.environ.get("AGI_SCORER_ENABLED", "").strip().lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in ("1", "true", "yes", "on"):
        return True
    return config.enabled


def _pick_device(config: AgiConfig) -> str:
    """Resolve the configured device, honoring the GPU OOM rule."""
    if config.device != "auto":
        return config.device
    if not torch.cuda.is_available():
        return "cpu"
    free_mb = torch.cuda.mem_get_info()[0] // (1024 * 1024)
    if free_mb >= config.min_vram_free_mb:
        return "cuda"
    logger.warning(
        "agi_scorer: only %dMB VRAM free (< %dMB) -- using CPU to protect Ollama/ComfyUI",
        free_mb,
        config.min_vram_free_mb,
    )
    return "cpu"


class AGIScriptScorer:
    """Lazy-loaded wrapper around the vendored AGI Brain V3 checkpoint."""

    def __init__(self, config: AgiConfig):
        self.config = config
        self._brain: Any | None = None
        self._device: str | None = None
        self._load_error: str | None = None

    # ---- loading -------------------------------------------------------
    def _load(self) -> None:
        if self._brain is not None or self._load_error is not None:
            return
        try:
            from .agi_brain_v3 import AGIBrainV3

            device = _pick_device(self.config)
            brain = AGIBrainV3(device=device)
            if device == "cuda":
                brain = brain.cuda()
            brain.eval()

            ckpt_path = self.config.checkpoint_path
            if not ckpt_path:
                raise FileNotFoundError("AGI checkpoint path not configured")
            ckpt_path = os.path.abspath(os.path.join(STACK_ROOT, ckpt_path))
            if not os.path.exists(ckpt_path):
                raise FileNotFoundError(f"AGI checkpoint not found: {ckpt_path}")
            ckpt = torch.load(ckpt_path, map_location=device)
            state = ckpt.get("model_state", ckpt)
            model_state = brain.state_dict()
            compatible = {
                k: v for k, v in state.items()
                if k in model_state and model_state[k].shape == v.shape
            }
            skipped = len(state) - len(compatible)
            brain.load_state_dict(compatible, strict=False)

            self._brain = brain
            self._device = device
            logger.info(
                "agi_scorer loaded (%s) | iter=%s val=%.1f%% skipped=%d",
                device, ckpt.get("iter", "?"), ckpt.get("val_overall", 0.0), skipped,
            )
        except Exception as exc:  # noqa: BLE001 -- degrade, never crash a stage
            self._load_error = str(exc)
            logger.warning("agi_scorer unavailable: %s", exc)

    def available(self) -> bool:
        self._load()
        return self._brain is not None

    # ---- scoring primitives -------------------------------------------
    def _similarity(self, a_text: str, b_text: str, *, head: str) -> float | None:
        if not self.available():
            return None
        a, b = a_text.strip(), b_text.strip()
        if not a or not b:
            return None
        with torch.no_grad():
            emb_a = self._brain.encode_text([a])
            emb_b = self._brain.encode_text([b])
            out_a = self._brain.forward_projected(emb_a)
            out_b = self._brain.forward_projected(emb_b)
            if head == "causal_effect":
                sim = F.cosine_similarity(out_a["causal_effect"], emb_b, dim=-1)
            else:
                sim = F.cosine_similarity(out_a[head], out_b[head], dim=-1)
            return max(-1.0, min(1.0, sim.item()))

    # ---- public API -----------------------------------------------------
    def fidelity(self, scene_text: str, beat_text: str) -> float | None:
        """SAME-head similarity between generated scene prose and the
        blueprint beat (narrative_function + emotional_purpose + title)."""
        return self._similarity(scene_text, beat_text, head="same")

    def causal_flow(self, scene_a: str, scene_b: str) -> float | None:
        """CAUSE-head similarity: does scene A plausibly lead into scene B?"""
        return self._similarity(scene_a, scene_b, head="causal_effect")

    def consistency(self, profile_text: str, scene_text: str) -> float | None:
        """SAME-head similarity between a character's blueprint profile and
        how they are written in a scene."""
        return self._similarity(profile_text, scene_text, head="same")

    def close(self) -> None:
        """Free the model (and CUDA memory) -- call after a scoring pass."""
        self._brain = None
        self._load_error = None
        if self._device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()


# Singleton-ish accessor so stages can cheaply share one loaded model.
_scorer_cache: dict[str, AGIScriptScorer] = {}


def get_scorer(config: AgiConfig) -> AGIScriptScorer:
    key = f"{config.device}|{config.checkpoint_path}"
    scorer = _scorer_cache.get(key)
    if scorer is None:
        scorer = AGIScriptScorer(config)
        _scorer_cache[key] = scorer
    return scorer
