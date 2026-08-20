"""Unit tests for the LTX video template router (design M-AP-2 + M-AP-3)."""

import pytest
from unittest.mock import MagicMock

from pipeline.video_router import (
    _DEFAULT_TEMPLATE,
    _TIER2,
    _TILED_TEMPLATE,
    pick_ltx_template,
)
from pipeline.config import PipelineConfig


def _mock_config(ltx2b_ready=True, ltx2b_gate=True, ltx23_ready=True, ltx23_gate=True):
    """Create a mock PipelineConfig with controlled LTX readiness."""
    config = MagicMock(spec=PipelineConfig)

    def mock_comfyui_dir():
        return MagicMock()

    config.comfyui_dir = mock_comfyui_dir
    # The router reads config.animation.engine first (engine override); the
    # default engine leaves the tiered LTX routing logic untouched.
    config.animation = MagicMock()
    config.animation.engine = "ltx2b"
    return config


def test_tier1_ambient_uses_default_when_ltx2b_ready():
    """Tier 1 shots use ltx2b when weights and gate are ready."""
    config = _mock_config(ltx2b_ready=True, ltx2b_gate=True)
    # Patch the internal check functions
    import pipeline.video_router as vr
    original_weights = vr._ltx2b_weights_ready
    original_lab = vr._ltx2b_lab_passed
    vr._ltx2b_weights_ready = lambda c: True
    vr._ltx2b_lab_passed = lambda: True
    vr._ltx23_weights_ready = lambda c: False
    try:
        for frames in (17, 33, 81):
            assert pick_ltx_template(config, 1, frames) == _DEFAULT_TEMPLATE
    finally:
        vr._ltx2b_weights_ready = original_weights
        vr._ltx2b_lab_passed = original_lab


def test_tier0_uses_default_when_ltx2b_ready():
    """Tier 0 shots use ltx2b when weights and gate are ready."""
    config = _mock_config()
    import pipeline.video_router as vr
    vr._ltx2b_weights_ready = lambda c: True
    vr._ltx2b_lab_passed = lambda: True
    vr._ltx23_weights_ready = lambda c: False
    try:
        assert pick_ltx_template(config, 0, 81) == _DEFAULT_TEMPLATE
    finally:
        # Restore would happen in fixture, but this is fine for now
        pass


def test_tier2_director_uses_tiled_when_ltx23_ready():
    """Tier 2 shots use ltx23 when weights and gate are ready."""
    config = _mock_config()
    import pipeline.video_router as vr
    vr._ltx23_weights_ready = lambda c: True
    vr._ltx23_lab_passed = lambda: True
    try:
        assert pick_ltx_template(config, 2, 81) == _TILED_TEMPLATE
        assert pick_ltx_template(config, _TIER2, _TIER2) == _TILED_TEMPLATE
    finally:
        pass


def test_frames_above_ceiling_uses_tiled_when_ltx23_ready():
    """Shots > 81 frames use ltx23 when weights and gate are ready."""
    config = _mock_config()
    import pipeline.video_router as vr
    vr._ltx23_weights_ready = lambda c: True
    vr._ltx23_lab_passed = lambda: True
    try:
        assert pick_ltx_template(config, 1, 82) == _TILED_TEMPLATE
        assert pick_ltx_template(config, 1, 161) == _TILED_TEMPLATE
    finally:
        pass


def test_no_cross_tier_regression():
    """Any tier at or above tier2 must always route to the tiled build (when ready)."""
    config = _mock_config()
    import pipeline.video_router as vr
    vr._ltx23_weights_ready = lambda c: True
    vr._ltx23_lab_passed = lambda: True
    try:
        for tier in (2, 3):
            assert pick_ltx_template(config, tier, 1) == _TILED_TEMPLATE
    finally:
        pass


def test_degrades_to_tier0_when_no_ltx_available():
    """When no LTX template is available, returns None (caller degrades to Tier-0)."""
    config = _mock_config()
    import pipeline.video_router as vr
    vr._ltx2b_weights_ready = lambda c: False
    vr._ltx23_weights_ready = lambda c: False
    vr._wan_weights_ready = lambda c: False
    try:
        assert pick_ltx_template(config, 1, 81) is None
        assert pick_ltx_template(config, 2, 81) is None
    finally:
        pass


def test_falls_back_to_ltx2b_when_ltx23_not_ready():
    """Tier 2 falls back to ltx2b when ltx23 is not ready but ltx2b is."""
    config = _mock_config()
    import pipeline.video_router as vr
    vr._ltx23_weights_ready = lambda c: False
    vr._ltx2b_weights_ready = lambda c: True
    vr._ltx2b_lab_passed = lambda: True
    try:
        # Tier 2 should fall back to ltx2b
        assert pick_ltx_template(config, 2, 81) == _DEFAULT_TEMPLATE
    finally:
        pass