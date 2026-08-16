"""Stage 3B: new functionality tests (angle-specific plates, WorldBible angles, new patch keys)."""
import json
from pathlib import Path

import pytest

from pipeline.schemas.worldbible import WorldBible
from pipeline.stage3b_images import _plate_key_for_scene
from pipeline.stage2_screenplay import _ShotOut


# --------------------------------------------------------------------------
# WorldBible location angles
# --------------------------------------------------------------------------
def test_worldbible_location_angles():
    wb = WorldBible(story_id="test", locations=[
        {"id": "loc-cafe", "name": "Cafe", "angles": ["wide_establishing", "medium_shot", "closeup_counter"]},
    ])
    loc = wb.get_location("loc-cafe")
    assert loc is not None
    assert loc.angles == ["wide_establishing", "medium_shot", "closeup_counter"]
    assert wb.get_location_angles("loc-cafe") == ["wide_establishing", "medium_shot", "closeup_counter"]

    # Unknown location returns defaults
    defaults = wb.get_location_angles("loc-unknown")
    assert defaults == ["wide_establishing", "medium_shot", "closeup_counter", "over_shoulder"]


# --------------------------------------------------------------------------
# _plate_key_for_scene with camera_angle
# --------------------------------------------------------------------------
def test_plate_key_includes_camera_angle():
    scene = {"location": "loc-cafe", "time_of_day": "morning"}
    shot_wide = {"camera_angle": "wide_establishing"}
    shot_medium = {"camera_angle": "medium_shot"}
    shot_closeup = {"camera_angle": "closeup_counter"}
    shot_over = {"camera_angle": "over_shoulder"}

    key_wide = _plate_key_for_scene(scene, shot_wide)
    key_medium = _plate_key_for_scene(scene, shot_medium)
    key_closeup = _plate_key_for_scene(scene, shot_closeup)
    key_over = _plate_key_for_scene(scene, shot_over)

    assert key_wide == "loc-cafe__morning__wide_establishing"
    assert key_medium == "loc-cafe__morning__medium_shot"
    assert key_closeup == "loc-cafe__morning__closeup_counter"
    assert key_over == "loc-cafe__morning__over_shoulder"

    # All keys should be different
    keys = {key_wide, key_medium, key_closeup, key_over}
    assert len(keys) == 4


def test_plate_key_defaults_to_wide_establishing():
    scene = {"location": "loc-cafe", "time_of_day": "day"}
    # No shot provided -> defaults to wide_establishing
    key = _plate_key_for_scene(scene)
    assert key == "loc-cafe__day__wide_establishing"

    # Shot without camera_angle -> defaults to wide_establishing
    shot = {"composition": "medium"}
    key2 = _plate_key_for_scene(scene, shot)
    assert key2 == "loc-cafe__day__wide_establishing"


def test_plate_key_time_of_day_normalization():
    scene1 = {"location": "loc-cafe", "time_of_day": "DAY"}
    scene2 = {"location": "loc-cafe", "time_of_day": "Night Time"}
    scene3 = {"location": "loc-cafe", "time_of_day": ""}

    assert _plate_key_for_scene(scene1) == "loc-cafe__day__wide_establishing"
    assert _plate_key_for_scene(scene2) == "loc-cafe__night_time__wide_establishing"
    assert _plate_key_for_scene(scene3) == "loc-cafe__day__wide_establishing"


# --------------------------------------------------------------------------
# Shot schema with camera_angle
# --------------------------------------------------------------------------
def test_shotout_includes_camera_angle():
    shot = _ShotOut(
        shot_type="medium",
        composition="medium shot",
        characters_in_frame=["char-1"],
        positioning="center",
        movement="static",
        facial="neutral",
        posture="standing",
        beat="character enters",
        camera_angle="medium_shot"
    )
    assert shot.camera_angle == "medium_shot"

    # Default when not provided
    shot2 = _ShotOut(shot_type="wide")
    assert shot2.camera_angle == "wide_establishing"


# --------------------------------------------------------------------------
# Stage3b patch key generation (unit-level, no ComfyUI)
# --------------------------------------------------------------------------
def _make_config(**overrides):
    """Create a minimal PipelineConfig with animation overrides."""
    from pipeline.config import PipelineConfig
    config = PipelineConfig()
    anim = config.animation
    for k, v in overrides.items():
        setattr(anim, k, v)
    return config


def _make_shot_and_scene():
    scene = {"id": "sc-001", "location": "loc-cafe", "time_of_day": "morning"}
    shot = {
        "id": "sh-001", "sd_prompt": "anime character in cafe",
        "characters_in_frame": ["char-1"], "composition": "medium shot",
        "positioning": "center", "camera_angle": "medium_shot"
    }
    return shot, scene


def test_patch_keys_include_base_krea2(tmp_path):
    """Base krea2 patch keys are present."""
    config = _make_config()
    shot, scene = _make_shot_and_scene()

    from pipeline.stage3b_images import _plate_key_for_scene
    plate_key = _plate_key_for_scene(scene, shot)

    patches = {
        "PROMPT_POS": "test prompt",
        "PLATE_IMG": "uploaded.png",
        "SEED": 42,
        "DENOISE": config.animation.panel_denoise,
        "SAMPLER": config.animation.panel_sampler,
        "SCHEDULER": config.animation.panel_scheduler,
        "STEPS": config.animation.panel_steps,
        "CFG": config.animation.panel_cfg,
        "SHARPEN_RADIUS": config.animation.panel_sharpen_radius,
        "SHARPEN_SIGMA": config.animation.panel_sharpen_sigma,
        "SHARPEN_ALPHA": config.animation.panel_sharpen_alpha,
        "SAVE_PREFIX": f"pipeline/test/panels/{shot['id']}",
    }

    assert "PROMPT_POS" in patches
    assert "PLATE_IMG" in patches
    assert "SEED" in patches
    assert "DENOISE" in patches
    assert patches["DENOISE"] == 0.2  # from stack.toml panel_denoise


def test_patch_keys_controlnet_when_enabled(tmp_path):
    """ControlNet keys added when enabled."""
    config = _make_config(controlnet_enabled=True, controlnet_strength=0.85)
    shot, scene = _make_shot_and_scene()

    patches = {}
    if config.animation.controlnet_enabled:
        patches.update({
            "CONTROLNET_NAME": config.animation.controlnet_default_model,
            "CONTROLNET_STRENGTH": config.animation.controlnet_strength,
        })

    assert "CONTROLNET_NAME" in patches
    assert patches["CONTROLNET_NAME"] == "control_v11p_sd15_openpose.safetensors"
    assert "CONTROLNET_STRENGTH" in patches
    assert patches["CONTROLNET_STRENGTH"] == 0.85


def test_patch_keys_regional_prompts_when_enabled(tmp_path):
    """Regional prompt keys added when enabled."""
    config = _make_config(
        regional_prompt_a_enabled=True, regional_prompt_a_text="character focus, detailed face",
        regional_prompt_b_enabled=True, regional_prompt_b_text="foreground props"
    )
    shot, scene = _make_shot_and_scene()

    patches = {}
    if config.animation.regional_prompt_a_enabled:
        patches["REGIONAL_PROMPT_A_TEXT"] = config.animation.regional_prompt_a_text
    if config.animation.regional_prompt_b_enabled:
        patches["REGIONAL_PROMPT_B_TEXT"] = config.animation.regional_prompt_b_text

    assert "REGIONAL_PROMPT_A_TEXT" in patches
    assert patches["REGIONAL_PROMPT_A_TEXT"] == "character focus, detailed face"
    assert "REGIONAL_PROMPT_B_TEXT" in patches
    assert patches["REGIONAL_PROMPT_B_TEXT"] == "foreground props"


def test_patch_keys_style_lora_when_enabled(tmp_path):
    """Style LoRA keys added when enabled."""
    config = _make_config(
        style_lora_enabled=True,
        style_lora_name="watercolor.safetensors",
        style_lora_strength_model=0.8,
        style_lora_strength_clip=0.6
    )
    shot, scene = _make_shot_and_scene()

    patches = {}
    if config.animation.style_lora_enabled and config.animation.style_lora_name:
        patches.update({
            "STYLE_LORA_NAME": config.animation.style_lora_name,
            "STYLE_LORA_STR_MODEL": config.animation.style_lora_strength_model,
            "STYLE_LORA_STR_CLIP": config.animation.style_lora_strength_clip,
        })

    assert "STYLE_LORA_NAME" in patches
    assert patches["STYLE_LORA_NAME"] == "watercolor.safetensors"
    assert "STYLE_LORA_STR_MODEL" in patches
    assert patches["STYLE_LORA_STR_MODEL"] == 0.8
    assert "STYLE_LORA_STR_CLIP" in patches
    assert patches["STYLE_LORA_STR_CLIP"] == 0.6


def test_patch_keys_character_mask_when_enabled(tmp_path):
    """Character mask key added when enabled."""
    config = _make_config(character_mask_enabled=True)
    shot, scene = _make_shot_and_scene()

    patches = {}
    if config.animation.character_mask_enabled:
        patches["CHARACTER_MASK_IMG"] = ""

    assert "CHARACTER_MASK_IMG" in patches
    assert patches["CHARACTER_MASK_IMG"] == ""


def test_patch_keys_color_grade_when_enabled(tmp_path):
    """Color grading keys added when enabled (default on)."""
    config = _make_config(
        color_grade_enabled=True,
        color_temp=5500, color_saturation=1.2, color_contrast=1.1,
        color_gamma=0.9, color_lift_r=0.1, color_gain_g=1.05
    )
    shot, scene = _make_shot_and_scene()

    patches = {}
    if config.animation.color_grade_enabled:
        patches.update({
            "COLOR_TEMP": config.animation.color_temp,
            "COLOR_SATURATION": config.animation.color_saturation,
            "COLOR_CONTRAST": config.animation.color_contrast,
            "COLOR_GAMMA": config.animation.color_gamma,
            "COLOR_LIFT_R": config.animation.color_lift_r,
            "COLOR_LIFT_G": config.animation.color_lift_g,
            "COLOR_LIFT_B": config.animation.color_lift_b,
            "COLOR_GAIN_R": config.animation.color_gain_r,
            "COLOR_GAIN_G": config.animation.color_gain_g,
            "COLOR_GAIN_B": config.animation.color_gain_b,
        })

    assert "COLOR_TEMP" in patches
    assert patches["COLOR_TEMP"] == 5500
    assert patches["COLOR_SATURATION"] == 1.2
    assert patches["COLOR_CONTRAST"] == 1.1
    assert patches["COLOR_GAMMA"] == 0.9
    assert patches["COLOR_LIFT_R"] == 0.1
    assert patches["COLOR_GAIN_G"] == 1.05


def test_patch_keys_disabled_by_default(tmp_path):
    """All new features disabled by default except color_grade."""
    config = _make_config()  # all defaults
    shot, scene = _make_shot_and_scene()

    # ControlNet disabled
    assert not config.animation.controlnet_enabled
    # Regional prompts disabled
    assert not config.animation.regional_prompt_a_enabled
    assert not config.animation.regional_prompt_b_enabled
    # Style LoRA disabled
    assert not config.animation.style_lora_enabled
    # Character mask disabled
    assert not config.animation.character_mask_enabled
    # Color grade ENABLED by default
    assert config.animation.color_grade_enabled