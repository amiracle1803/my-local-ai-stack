"""Regression: stage3b must not crash when a storyboard panel state dict lacks
the ``issues`` key.

Seen live on clockguard: 13/26 panels had only ``{'locked_by', 'status'}``
(no ``issues``). Both the degraded-accept path (line ~805) and the flag path
(~816) append to ``state['issues']``; if the key is missing the stage died with
``KeyError: 'issues'`` mid-run. The fix uses ``setdefault`` so the key is
created on first append.

This test drives the full ``run()`` with a mocked ComfyClient + vision_judge
and verifies the run completes for both verdict shapes with issue-less states.
"""
import json
from pathlib import Path
from unittest.mock import patch

from pipeline.config import PipelineConfig
from pipeline.scores import Scores
from pipeline.stage3b_images import run

from smoke_test_stage3b import MockComfyClient, create_minimal_project

# (passed, detail) verdicts keyed by shot id. shape A exercises the
# degraded-accept path (hard identity checks pass, soft framing fails);
# shape B exercises the flag path (appearance hard-fails).
VERDICTS = {
    "sh-001-01": (True, {
        "characters_visible": 1,
        "background_matches": True,
        "composition_matches": True,
        "render_valid": True,
        "inconclusive": False,
    }),
    "sh-001-02": (False, {
        "characters_visible": 1,
        "background_matches": False,
        "composition_matches": False,
        "render_valid": True,
        "appearance_matches": True,
        "inconclusive": False,
    }),
    "sh-001-03": (False, {
        "characters_visible": 1,
        "background_matches": False,
        "composition_matches": False,
        "render_valid": True,
        "appearance_matches": False,
        "appearance_issue": "eyes",
        "inconclusive": False,
    }),
}


def _strip_issues(project_dir: Path) -> None:
    """Drop the ``issues`` key from every panel state (reproduce clockguard)."""
    sb_path = project_dir / "storyboard" / "storyboard.json"
    sb = json.loads(sb_path.read_text(encoding="utf-8"))
    for state in sb["panels"].values():
        state.pop("issues", None)
    sb_path.write_text(json.dumps(sb, indent=2), encoding="utf-8")


def _run(project_dir: Path) -> dict:
    config = PipelineConfig()
    scores = Scores(str(project_dir / "scores.db"))
    mock_comfy = MockComfyClient(config)

    def fake_vision(panel_path, shot, scene, config, appearance_facts=None, appearance_spec=None):
        return VERDICTS[shot["id"]]

    with patch("pipeline.stage3b_images.ComfyClient", return_value=mock_comfy):
        with patch("pipeline.stage3b_images.vision_judge", side_effect=fake_vision):
            return run(project_dir, config, scores, comfy=mock_comfy)


def test_stage3b_missing_issues_key_does_not_crash(tmp_path):
    project_dir = tmp_path / "smoke_project"
    create_minimal_project(project_dir)
    _strip_issues(project_dir)

    result = _run(project_dir)

    assert result is not None
    sb = json.loads((project_dir / "storyboard" / "storyboard.json").read_text(encoding="utf-8"))
    states = sb["panels"]
    # shape A: degraded-accept -> generated with the key created
    assert states["sh-001-02"]["status"] == "generated"
    assert states["sh-001-02"].get("degraded") is True
    assert states["sh-001-02"].get("issues")
    # shape B: hard appearance fail -> flagged with the key created
    assert states["sh-001-03"]["status"] == "flagged"
    assert states["sh-001-03"].get("issues")
    # shape A untouched by the missing-key bug
    assert states["sh-001-01"]["status"] == "generated"