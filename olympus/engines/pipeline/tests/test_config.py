"""Config loading + MODEL BAN LIST enforcement."""

import pytest

from pipeline.config import BannedModelError, PipelineConfig

BANNED = ["z-anime-distill-4step-fp8", "wai-illustrious-v110", "NoobAI-XL-v1.1"]


def test_loads_default_toml():
    cfg = PipelineConfig.load()
    assert cfg.models.image_primary == "krea2"
    assert cfg.models.banned == BANNED
    assert cfg.automation.auto_advance_stages is True
    assert cfg.animation.drift_axis == "vertical"
    assert cfg.animation.max_animated_seconds_per_block == 60.0


def test_resolve_image_model_primary_ok():
    cfg = PipelineConfig.load()
    assert cfg.resolve_image_model("primary") == "krea2"
    assert cfg.resolve_image_model("fallback") == "flux1-schnell-Q4_K_S.gguf"


def test_projects_dir_is_absolute():
    cfg = PipelineConfig.load()
    assert cfg.projects_dir().is_absolute()
    assert cfg.projects_dir().name == "projects"


def _write_toml(tmp_path, image_primary):
    text = f"""
[models]
llm_script = "qwen3:8b"
llm_vision = "qwen2.5vl:7b"
llm_default = "llama3.1:8b"
image_primary = "{image_primary}"
image_fallback = "flux1-schnell-Q4_K_S.gguf"
banned = ["z-anime-distill-4step-fp8", "wai-illustrious-v110", "NoobAI-XL-v1.1"]

[automation]
auto_advance_stages = true

[animation]
drift_axis = "vertical"

[paths]
projects = "projects"
"""
    p = tmp_path / "pipeline.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_banned_model_as_primary_raises(tmp_path):
    cfg = PipelineConfig.load(_write_toml(tmp_path, "wai-illustrious-v110"))
    with pytest.raises(BannedModelError):
        cfg.resolve_image_model("primary")


def test_all_banned_names_rejected(tmp_path):
    for name in BANNED:
        cfg = PipelineConfig.load(_write_toml(tmp_path, name))
        with pytest.raises(BannedModelError):
            cfg.resolve_image_model("primary")


def test_unknown_role_raises():
    cfg = PipelineConfig.load()
    with pytest.raises(ValueError):
        cfg.resolve_image_model("bogus")
