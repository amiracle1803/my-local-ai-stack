"""Tests for the model-aware tiered quality gate (stage3b):

- QUALITY_PROFILES selection by model
- render_valid code-side guard
- _panel_score / _fallback_panel_accepted (booleans, not raw counts)
- simplified fallback prompt assembly

No GPU, no live VLM."""
from __future__ import annotations

from pipeline.schemas.worldbible import Appearance, Character, Location, WorldBible
from pipeline.stage3b_images import (
    QUALITY_PROFILES,
    _VisionCheck,
    _check_render_valid,
    _fallback_panel_accepted,
    _panel_score,
    _quality_profile,
)


# --------------------------------------------------------------------------
# profile selection
# --------------------------------------------------------------------------


def test_quality_profile_selection():
    # krea2 is manga-stylized, so composition/background are soft (like flux)
    assert _quality_profile("krea2-v1.0")["min_pass_rate"] == 0.50
    assert _quality_profile("krea2-anything.gguf")["min_prompt_adherence"] == 0.25
    assert _quality_profile("flux-2-klein-4b-Q4_K_M.gguf")["min_pass_rate"] == 0.50
    assert _quality_profile("flux-2-klein-4b-Q4_K_M.gguf")["min_prompt_adherence"] == 0.25
    # unknown model -> conservative fallback profile (values match, not identity:
    # _quality_profile now returns a copy so a quick-mode override can cap regens)
    fb = _quality_profile("some-other-model.gguf")
    assert fb["min_pass_rate"] == QUALITY_PROFILES["flux-2-klein"]["min_pass_rate"]
    assert fb["hard_checks"] == QUALITY_PROFILES["flux-2-klein"]["hard_checks"]
    assert fb["soft_checks"] == QUALITY_PROFILES["flux-2-klein"]["soft_checks"]


def test_quality_profile_max_regens_override():
    # quick mode caps the retry ladder regardless of model profile
    assert _quality_profile("krea2-v1.0", max_regens_override=1)["max_regens"] == 1
    assert _quality_profile("flux-2-klein-4b-Q4_K_M.gguf", max_regens_override=1)["max_regens"] == 1
    # default (no override) keeps the model's own ladder
    assert _quality_profile("krea2-v1.0")["max_regens"] == 3
    assert _quality_profile("flux-2-klein-4b-Q4_K_M.gguf")["max_regens"] == 2


def test_profiles_keep_hard_appearance_for_fallback():
    fb = QUALITY_PROFILES["flux-2-klein"]
    assert "appearance_matches" in fb["hard_checks"]
    assert "composition_matches" in fb["soft_checks"]
    assert "background_matches" in fb["soft_checks"]
    k = QUALITY_PROFILES["krea2"]
    assert "appearance_matches" in k["hard_checks"]  # identity is the hard gate
    assert "composition_matches" in k["soft_checks"]  # manga framing is soft


# --------------------------------------------------------------------------
# render_valid (code-side guard)
# --------------------------------------------------------------------------


def test_render_valid_missing_or_tiny(tmp_path):
    missing = tmp_path / "nope.png"
    assert _check_render_valid(missing) is False
    tiny = tmp_path / "tiny.png"
    tiny.write_bytes(b"\x00" * 500)
    assert _check_render_valid(tiny) is False


def test_render_valid_decodable_png(tmp_path):
    import random

    from PIL import Image

    png = tmp_path / "ok.png"
    rnd = random.Random(0)
    Image.new("RGB", (128, 128)).save(png, "PNG")
    # overwrite with noise so the PNG is >1KB (solid colors compress too small)
    Image.frombytes("RGB", (128, 128), bytes(rnd.randrange(256) for _ in range(128 * 128 * 3))).save(png, "PNG")
    assert png.stat().st_size > 1024
    assert _check_render_valid(png) is True


# --------------------------------------------------------------------------
# panel scoring / fallback acceptance (booleans, not raw counts)
# --------------------------------------------------------------------------


def test_panel_score_uses_booleans_not_counts():
    """characters_visible is an int count; the score must treat it as a
    presence bool so a 2-char panel does not outscore a 1-char panel."""
    one = _VisionCheck(render_valid=True, characters_visible=1, appearance_matches=True,
                       composition_matches=False, background_matches=False)
    two = _VisionCheck(render_valid=True, characters_visible=2, appearance_matches=True,
                       composition_matches=False, background_matches=False)
    assert _panel_score(one) == _panel_score(two)
    # full pass
    full = _VisionCheck(render_valid=True, characters_visible=1, appearance_matches=True,
                        composition_matches=True, background_matches=True)
    assert _panel_score(full) == 1.0


def test_fallback_accepts_soft_degraded():
    v = _VisionCheck(render_valid=True, characters_visible=1, appearance_matches=True,
                     composition_matches=False, background_matches=False)
    accepted, score = _fallback_panel_accepted(v)
    assert accepted is True  # identity + valid, framing soft-failed -> degraded accept
    assert score >= 0.60


def test_fallback_rejects_hard_failures():
    assert _fallback_panel_accepted(
        _VisionCheck(render_valid=False, characters_visible=1, appearance_matches=True)
    )[0] is False
    assert _fallback_panel_accepted(
        _VisionCheck(render_valid=True, characters_visible=0, appearance_matches=True)
    )[0] is False
    assert _fallback_panel_accepted(
        _VisionCheck(render_valid=True, characters_visible=1, appearance_matches=False)
    )[0] is False


# --------------------------------------------------------------------------
# simplified fallback prompt
# --------------------------------------------------------------------------


def test_assemble_sd_prompt_simple_one_subject():
    from pipeline.stage2_screenplay import assemble_sd_prompt_simple

    wb = WorldBible(
        story_id="s",
        characters=[
            Character(id="rei", name="Rei",
                      appearance=Appearance(hair="silver", eyes="cyan", skin="pale",
                                            build="slender", clothing_primary="grey cloak")),
        ],
        locations=[Location(id="loc-x", name="X", sd_prompt="snowy forest")],
    )
    shot = {"characters_in_frame": ["rei"], "camera_angle": "close-up", "composition": "over-shoulder from B"}
    scene = {"location": "loc-x", "time_of_day": "dusk"}
    p = assemble_sd_prompt_simple(shot, scene, wb)
    assert "silver" in p and "cyan" in p and "grey cloak" in p
    assert "close-up" in p           # explicit camera template wins
    assert "snowy forest" in p       # location present
    assert "over-shoulder from B" not in p  # dense multi-constraint dropped
    assert "no text" in p and "no watermark" in p


def test_assemble_sd_prompt_simple_empty_frame():
    from pipeline.stage2_screenplay import assemble_sd_prompt_simple

    wb = WorldBible(story_id="s")
    p = assemble_sd_prompt_simple({"characters_in_frame": []}, {"location": "loc-x", "time_of_day": ""}, wb)
    assert p.strip()  # non-empty (camera label + no-text tail)