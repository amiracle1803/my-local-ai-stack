"""image_router.pick_template: krea2-vs-fallback routing (design 5.3b)."""

import pytest

from pipeline import image_router
from pipeline.config import BannedModelError, ModelsConfig, PathsConfig, PipelineConfig


def _config(tmp_path, *, primary="krea2", banned=None):
    return PipelineConfig(
        models=ModelsConfig(
            llm_script="qwen3:8b", llm_vision="qwen2.5vl:7b", llm_default="llama3.1:8b",
            image_primary=primary, image_fallback="flux1-schnell-Q4_K_S.gguf",
            banned=banned or [],
        ),
        paths=PathsConfig(comfyui=str(tmp_path)),
    )


def _write_weights(tmp_path, size_bytes):
    weights = tmp_path / "models" / "unet" / "krea2_turbo-Q4_K_S.gguf"
    weights.parent.mkdir(parents=True, exist_ok=True)
    weights.write_bytes(b"0" * size_bytes)


def test_picks_krea2_when_weights_present_and_lab_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(image_router, "_MIN_PRIMARY_BYTES", 100)
    monkeypatch.setattr(image_router, "_krea2_lab_passed", lambda: True)
    _write_weights(tmp_path, 200)
    template, model = image_router.pick_template(_config(tmp_path), comfy=None)
    assert (template, model) == ("image_krea2.json", "krea2")


def test_falls_back_without_lab_marker(tmp_path, monkeypatch):
    """Weights on disk but no model_lab smoke pass -> fallback (design 5.3b)."""
    monkeypatch.setattr(image_router, "_MIN_PRIMARY_BYTES", 100)
    monkeypatch.setattr(image_router, "_krea2_lab_passed", lambda: False)
    _write_weights(tmp_path, 200)
    template, model = image_router.pick_template(_config(tmp_path), comfy=None)
    assert template == "image_flux_fallback.json"


def test_falls_back_when_weights_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(image_router, "_MIN_PRIMARY_BYTES", 100)
    # no weights file written at all
    template, model = image_router.pick_template(_config(tmp_path), comfy=None)
    assert (template, model) == ("image_flux_fallback.json", "flux1-schnell-Q4_K_S.gguf")


def test_falls_back_when_weights_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(image_router, "_MIN_PRIMARY_BYTES", 100)
    _write_weights(tmp_path, 50)  # smaller than the threshold: partial download
    template, model = image_router.pick_template(_config(tmp_path), comfy=None)
    assert (template, model) == ("image_flux_fallback.json", "flux1-schnell-Q4_K_S.gguf")


def test_banned_primary_propagates(tmp_path, monkeypatch):
    monkeypatch.setattr(image_router, "_MIN_PRIMARY_BYTES", 100)
    _write_weights(tmp_path, 200)
    cfg = _config(tmp_path, primary="krea2", banned=["krea2"])
    with pytest.raises(BannedModelError):
        image_router.pick_template(cfg, comfy=None)
