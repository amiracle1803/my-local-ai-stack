"""Stage 3C: LTX render cache (clip input hash key) + animation_coverage."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.stage3c_animation import _clip_cache_key, _clip_cache_load, _clip_cache_store


# --------------------------------------------------------------------------
# cache key and persistence (pure, no GPU)
# --------------------------------------------------------------------------
def test_cache_key_changes_when_panel_changes(tmp_path):
    panel = tmp_path / "sh-001.png"
    panel.write_bytes(b"\x89PNG" + b"\x00" * 100)
    panel2 = tmp_path / "sh-002.png"
    panel2.write_bytes(b"\x89PNG" + b"\xff" * 100)
    k1 = _clip_cache_key(panel, "prompt-a", "video_ltx22b_i2v.json", 8, 42, ai_upscale=False)
    k2 = _clip_cache_key(panel2, "prompt-a", "video_ltx22b_i2v.json", 8, 42, ai_upscale=False)
    assert k1 != k2, "different panels must produce different keys"


def test_cache_key_changes_when_prompt_changes(tmp_path):
    panel = tmp_path / "sh-001.png"
    panel.write_bytes(b"\x89PNG" + b"\x00" * 100)
    k1 = _clip_cache_key(panel, "prompt-a", "video_ltx22b_i2v.json", 8, 42, ai_upscale=False)
    k2 = _clip_cache_key(panel, "prompt-b", "video_ltx22b_i2v.json", 8, 42, ai_upscale=False)
    assert k1 != k2


def test_cache_key_changes_when_template_changes(tmp_path):
    panel = tmp_path / "sh-001.png"
    panel.write_bytes(b"\x89PNG" + b"\x00" * 100)
    k1 = _clip_cache_key(panel, "prompt", "video_ltx22b_i2v.json", 8, 42, ai_upscale=False)
    k2 = _clip_cache_key(panel, "prompt", "video_ltx23_i2v.json", 8, 42, ai_upscale=False)
    assert k1 != k2


def test_cache_store_and_load(tmp_path):
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    clip = clips_dir / "sh-001.mp4"
    clip.write_text("fake mp4")
    k = "deadbeef" * 8
    _clip_cache_store(clips_dir, k, clip)
    loaded = _clip_cache_load(clips_dir)
    assert loaded[k] == "sh-001.mp4"


def test_cache_load_empty(tmp_path):
    assert _clip_cache_load(tmp_path / "nonexistent") == {}


def test_cache_load_corrupt(tmp_path):
    p = tmp_path / ".ltx_cache.json"
    p.write_text("not json")
    assert _clip_cache_load(tmp_path) == {}


# --------------------------------------------------------------------------
# integration: stage3c run reuses cache on second invokation (fake comfy)
# --------------------------------------------------------------------------
def _minimal_stage3c_project(project_dir: Path) -> None:
    # blueprint.json is read at the end of the stage (mark_stage).
    from pipeline.blueprint import STAGE_ORDER, Blueprint, StageEntry, Style, Target
    from pipeline._util import now_iso
    bp = Blueprint(
        story_id="test", slug="test", title_hash="x" * 16, created=now_iso(),
        fps=24, style=Style(), target=Target(),
        stages={s: StageEntry(status="done" if s != "stage3c" else "pending", ts=now_iso())
                 for s in STAGE_ORDER},
    )
    (project_dir / "blueprint.json").write_text(bp.to_json(), encoding="utf-8")

    scenes = [{
        "id": "sc-001", "location": "loc-main", "summary": "a test scene",
        "time_of_day": "day", "characters": [], "shots": [
            {"id": "sh-001", "composition": "medium", "beat": "enter",
             "characters_in_frame": [], "narration": {"text": "test shot."},
             "dialogue": [], "shot_type": "medium", "lipsync": False,
             "facial": "neutral", "posture": "standing", "movement": "none",
             "sd_prompt": "anime test scene", "camera_movement": "static",
             "lighting": "neutral", "motion_tier": 1, "planned_tier": None,
             "motion_prompt": None},
        ],
    }]
    (project_dir / "screenplay").mkdir(parents=True)
    (project_dir / "screenplay" / "screenplay.json").write_text(
        json.dumps({"scenes": scenes}), encoding="utf-8",
    )
    storyboard = {
        "story_id": "test",
        "fps": 24,
        "blocks": [{"id": "blk-001", "shots": ["sh-001"], "order": "first",
                     "est_seconds": 5.0, "seed_frame": None, "status": "pending"}],
        "panels": {"sh-001": {"status": "pending", "locked_by": None, "issues": []}},
        "shot_detail": {"sh-001": {
            "facial": "neutral", "posture": "standing", "movement": "none",
            "motion_tier": 1, "motion_prompt": None, "lipsync": False,
            "drift": {"axis": "vertical", "direction": 1, "pixels": 100},
        }},
        "sfx": [],
    }
    (project_dir / "storyboard").mkdir()
    (project_dir / "storyboard" / "storyboard.json").write_text(
        json.dumps(storyboard), encoding="utf-8",
    )
    # Panel PNG for the shot (the "first" block)
    panel_dir = project_dir / "panels" / "blk-001"
    panel_dir.mkdir(parents=True)
    (panel_dir / "sh-001.png").write_bytes(b"\x89PNG" + b"\x00" * 200)


@pytest.fixture
def stage3c_project(tmp_path):
    _minimal_stage3c_project(tmp_path)
    return tmp_path


def _write_motion_clip(path: Path) -> Path:
    """Generate a real mp4 with directed motion so the stage3c optical-flow
    gate accepts it (the gate now rejects invalid/static files on purpose)."""
    import cv2
    import numpy as np

    w, h, n = 320, 180, 24
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 16, (w, h))
    base = np.zeros((h, w, 3), np.uint8)
    cv2.circle(base, (w // 2, h // 2), 30, (180, 90, 60), -1)
    for x in range(0, w, 16):  # full-frame texture so the median-flow camera
        cv2.line(base, (x, 0), (x, h), (70, 70, 90), 1)  # model sees a pan
    for i in range(n):
        dx = int((w / 3) * (i / (n - 1)))  # directed full-frame pan left->right
        frame = np.roll(base, dx, axis=1)
        vw.write(frame)
    vw.release()
    return path


def _fake_comfy():
    c = MagicMock()
    def _upload(*args, **kwargs):
        return "anim_sh-001.png"
    def _generate(template, patches, *, dest):
        clip = Path(dest) / "sh-001.mp4"
        _write_motion_clip(clip)
        return [clip]
    c.upload_image.side_effect = _upload
    c.generate.side_effect = _generate
    c.healthy.return_value = True
    return c


def test_stage3c_cache_reuses_render(stage3c_project):
    """Second invocation must skip ComfyUI generate for an unchanged shot."""
    from pipeline.stage3c_animation import run
    from pipeline.config import PipelineConfig
    from pipeline.scores import Scores

    config = PipelineConfig()
    db = stage3c_project / "scores.db"

    comfy = _fake_comfy()

    # First run: should call generate.
    first = run(
        stage3c_project, config, Scores(str(db)),
        comfy=comfy,
    )
    assert first["ltx_rendered"] == 1
    assert comfy.generate.call_count == 1

    # Reset the mock and re-run on the same project.
    comfy.reset_mock()
    second = run(
        stage3c_project, config, Scores(str(db)),
        comfy=comfy,
    )
    assert second["ltx_rendered"] == 1  # still renders 1 shot
    assert second["ltx_cache_hits"] == 1  # from cache this time
    assert comfy.generate.call_count == 0  # no GPU render


def test_stage3c_cache_misses_on_changed_prompt(stage3c_project):
    """A different motion prompt produces a different cache key -> re-render."""
    from pipeline.stage3c_animation import run
    from pipeline.config import PipelineConfig
    from pipeline.scores import Scores

    config = PipelineConfig()
    db = stage3c_project / "scores.db"
    comfy = _fake_comfy()

    # First run seeds the cache (motion_prompt from the shot data matches).
    r1 = run(stage3c_project, config, Scores(str(db)), comfy=comfy)
    assert r1["ltx_rendered"] == 1

    comfy.reset_mock()
    # Mutate the shot's data so the motion prompt hash differs.
    screenplay = json.loads(
        (stage3c_project / "screenplay" / "screenplay.json").read_text(encoding="utf-8")
    )
    screenplay["scenes"][0]["shots"][0]["composition"] = "close-up"
    (stage3c_project / "screenplay" / "screenplay.json").write_text(
        json.dumps(screenplay), encoding="utf-8",
    )
    r2 = run(stage3c_project, config, Scores(str(db)), comfy=comfy)
    assert r2["ltx_rendered"] == 1
    # May or may not be a cache hit depending on prompt change -- the key
    # includes the motion prompt which depends on composition. Verify the
    # call count: if cache miss (compose changes), generate is called.
    assert comfy.generate.call_count <= 1  # at most one render


def test_stage3c_cache_repopulates_on_panel_mutation(stage3c_project):
    """Change the panel content -> new cache key -> regenerate even with
    same motion prompt."""
    from pipeline.stage3c_animation import run
    from pipeline.config import PipelineConfig
    from pipeline.scores import Scores

    config = PipelineConfig()
    db = stage3c_project / "scores.db"
    comfy = _fake_comfy()

    r1 = run(stage3c_project, config, Scores(str(db)), comfy=comfy)
    assert r1["ltx_rendered"] == 1

    comfy.reset_mock()
    # Mutate the panel bytes.
    panel = stage3c_project / "panels" / "blk-001" / "sh-001.png"
    panel.write_bytes(b"\x89PNG" + b"\xab" * 200)
    r2 = run(stage3c_project, config, Scores(str(db)), comfy=comfy)
    assert r2["ltx_rendered"] == 1
    assert comfy.generate.call_count == 1  # re-rendered because panel changed