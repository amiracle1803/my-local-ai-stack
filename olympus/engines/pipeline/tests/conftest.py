"""pytest bootstrap: put the pipeline engine root on sys.path so `pipeline`
and `run` import regardless of where pytest is invoked from."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

# Keep the vendored AGI script scorer out of unit tests: it loads torch +
# a 1.3GB checkpoint and is exercised by explicit tests instead. Stage0
# honors this env override via agi_scorer.scorer_enabled().
os.environ.setdefault("AGI_SCORER_ENABLED", "0")


@pytest.fixture
def tmp_comfyui_dir(tmp_path):
    """Provide a temporary ComfyUI directory structure for tests that need it.
    Creates output/, temp/, input/ subdirs and returns the root Path."""
    comfyui = tmp_path / "comfyui"
    (comfyui / "output").mkdir(parents=True)
    (comfyui / "temp").mkdir(parents=True)
    (comfyui / "input").mkdir(parents=True)
    return comfyui


@pytest.fixture
def test_config(tmp_comfyui_dir):
    """PipelineConfig with ComfyUI dir redirected to a temp location."""
    from pipeline.config import PipelineConfig, PathsConfig

    cfg = PipelineConfig.load()
    # Override just the comfyui path
    cfg.paths = PathsConfig(comfyui=str(tmp_comfyui_dir))
    return cfg
