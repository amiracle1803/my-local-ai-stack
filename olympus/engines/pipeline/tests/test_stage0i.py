"""Stage 0I (IMPORT) tests: panel inventory (natural sort / blank / splash),
per-panel vision, identity resolution, screenplay synthesis, and the full
run. No network -- PipelineLLM is replaced by a fake; panels are tiny
placeholder bytes (inventory only checks size/name, not image validity).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import run
from pipeline.config import PipelineConfig
from pipeline.scores import Scores
from pipeline.stage0i_import import (
    Stage0IError,
    analyze_panel,
    inventory_panels,
    natural_sort,
    resolve_identity,
    run as run_stage0i,
    synthesize_screenplay,
)

# A tiny non-empty payload (well above the 5KB blank threshold is not required
# for tests that only exercise names/sorting; blank-flag tests use tiny bytes).
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _make_panels(tmp_path, names, *, tiny=False):
    d = tmp_path / "panels"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        data = b"\x00" if tiny else _FAKE_PNG
        (d / n).write_bytes(data)
    return d


# --------------------------------------------------------------------------
# natural sort
# --------------------------------------------------------------------------
def test_natural_sort_orders_numbers():
    names = ["panel_10.png", "panel_2.png", "panel_1.png", "panel_001.png"]
    paths = [Path(n) for n in names]
    ordered = natural_sort(paths)
    got = [p.name for p in ordered]
    # panel_1, panel_001, panel_2, panel_10 (natural, digit-aware)
    assert got[0] == "panel_1.png"
    assert got[1] == "panel_001.png"
    assert got[2] == "panel_2.png"
    assert got[3] == "panel_10.png"


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------
def test_inventory_orders_and_flags_blank(tmp_path):
    d = _make_panels(tmp_path, ["panel_1.png", "panel_2.png"], tiny=True)
    items = inventory_panels(d)
    assert [i.path for i in items] == ["panel_1.png", "panel_2.png"]
    assert all(i.flagged_blank for i in items)  # tiny bytes -> <5KB


def test_inventory_classifies_full_page_by_size(tmp_path):
    # One large panel (median * 4) -> full_page_splash. All above the 5KB
    # blank threshold so classification is not overridden by the blank flag.
    d = tmp_path / "panels"
    d.mkdir(parents=True, exist_ok=True)
    big = b"\x00" * 6000
    small = b"\x00" * 6000
    (d / "small_1.png").write_bytes(small)
    (d / "small_2.png").write_bytes(small)
    (d / "big_splash.png").write_bytes(big * 40)
    items = inventory_panels(d)
    by_name = {i.path: i for i in items}
    assert by_name["big_splash.png"].classification == "full_page_splash"
    assert by_name["small_1.png"].classification == "panel"
    assert not by_name["big_splash.png"].flagged_blank


def test_inventory_ignores_non_images(tmp_path):
    d = _make_panels(tmp_path, ["panel_1.png", "notes.txt"])
    items = inventory_panels(d)
    assert len(items) == 1


# --------------------------------------------------------------------------
# pass-level (fake LLM)
# --------------------------------------------------------------------------
PANEL_ANALYSIS = {
    "panel_id": "panel_1",
    "characters": [
        {
            "hair": "red bob", "eyes": "green", "skin": "pale",
            "build": "slim", "clothing": "blue tunic",
            "position_in_frame": "center", "specific_expression": "worried",
        }
    ],
    "action": "starts running -> reaches the gate",
    "dialogue": [{"speaker": "girl in blue", "text": "We have to hurry!", "bubble_type": "speech"}],
    "mood": "tense",
    "setting": {"interior_exterior": "exterior", "description": "village gate", "time_of_day": "morning"},
    "shot_type": "wide",
    "panel_notes": "",
    "tier": "full",
    "needs_manual_review": False,
}

IDENTITY = {
    "characters": [
        {
            "provisional_id": "red_haired_girl", "canonical_appearance": "red bob, green eyes, blue tunic",
            "appears_in_panels": ["panel_1"], "speaks_in_panels": ["panel_1"],
            "confidence": 0.9, "uncertainty_notes": "",
        }
    ],
    "uncertain_groupings": [],
}

SYNTHESIS = {
    "scenes": [
        {
            "scene_id": "sc-001", "location": "loc-gate", "summary": "the girl flees",
            "time_of_day": "morning",
            "shots": [
                {
                    "shot_id": "sh-001-01", "scene_id": "sc-001", "shot_type": "wide",
                    "description": "runs to the gate", "narration": "She had nowhere left to go.",
                    "dialogue": [{"character_id": "red_haired_girl", "text": "We have to hurry!"}],
                    "sd_prompt": "red bob, green eyes, blue tunic, village gate, wide, anime 2d illustration",
                    "source_panel": "panel_1",
                }
            ],
        }
    ]
}


class FakeLLM:
    def __init__(self):
        self.json_calls = []

    def complete_json(self, prompt_file, context, schema, *, role="script", stage_hint="stage", images=None):
        self.json_calls.append((stage_hint, prompt_file, role, bool(images)))
        if prompt_file == "s0i_panel_vision.md":
            a = dict(PANEL_ANALYSIS)
            a["panel_id"] = context["panel_id"]
            return schema.model_validate(a)
        if prompt_file == "s0i_identity.md":
            return schema.model_validate(IDENTITY)
        if prompt_file == "s0i_synthesis.md":
            return schema.model_validate(SYNTHESIS)
        raise AssertionError(f"unexpected JSON prompt {prompt_file!r}")

    def complete_text(self, prompt_file, context, *, role="script", stage_hint="stage", images=None):
        raise AssertionError("0I should not call complete_text")


def test_analyze_panel_uses_vision_role_with_image(tmp_path):
    d = _make_panels(tmp_path, ["panel_1.png"])
    item = inventory_panels(d)[0]
    llm = FakeLLM()
    a = analyze_panel(item, d, llm)
    assert a.panel_id == "panel_1"
    assert a.characters[0]["hair"] == "red bob"
    # vision role + image attached
    assert llm.json_calls[0][1] == "s0i_panel_vision.md"
    assert llm.json_calls[0][2] == "vision"
    assert llm.json_calls[0][3] is True


def test_analyze_panel_failure_becomes_minimal_review(tmp_path):
    d = _make_panels(tmp_path, ["panel_1.png"])
    item = inventory_panels(d)[0]

    class BoomLLM(FakeLLM):
        def complete_json(self, *a, **k):
            raise RuntimeError("vision down")

    a = analyze_panel(item, d, BoomLLM())
    assert a.tier == "minimal"
    assert a.needs_manual_review is True


def test_resolve_identity_clusters():
    from pipeline.schemas.stage0 import PanelAnalysis

    analyses = [PanelAnalysis.model_validate(PANEL_ANALYSIS)]
    llm = FakeLLM()
    chars, uncertain = resolve_identity(analyses, llm)
    assert chars[0].provisional_id == "red_haired_girl"
    assert uncertain == []


def test_synthesize_screenplay():
    from pipeline.schemas.stage0 import IdentityCluster, PanelAnalysis

    analyses = [PanelAnalysis.model_validate(PANEL_ANALYSIS)]
    chars = [IdentityCluster.model_validate(IDENTITY["characters"][0])]
    llm = FakeLLM()
    scenes = synthesize_screenplay(analyses, chars, llm)
    assert scenes[0]["shots"][0]["source_panel"] == "panel_1"


# --------------------------------------------------------------------------
# full run()
# --------------------------------------------------------------------------
def _make_project(tmp_path, *, names=None, as_zip=False):
    names = names or ["panel_1.png", "panel_2.png"]
    projects_dir = tmp_path / "projects"
    seed = tmp_path / "seed.txt"
    seed.write_text("placeholder seed " * 10, encoding="utf-8")

    if as_zip:
        zpath = tmp_path / "panels.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            for n in names:
                zf.writestr(n, _FAKE_PNG)
        upload = zpath
    else:
        upload = _make_panels(tmp_path, names)
    proj_dir = run.new_project(
        "i0test", seed, fps=24, projects_dir=projects_dir, mode="0i", panel_upload=upload
    )
    return proj_dir, upload


def test_run_happy_path_writes_screenplay_and_script(tmp_path):
    proj_dir, upload = _make_project(tmp_path)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    result = run_stage0i(proj_dir, cfg, scores, upload=upload, llm=FakeLLM())

    assert result["status"] == "done"
    assert scores.is_done("stage0")
    assert result["panels"] == 2
    assert result["scenes"] == 1

    sp = json.loads((proj_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8"))
    assert sp["scenes"][0]["shots"][0]["source_panel"] == "panel_1"
    script_text = (proj_dir / "input" / "script.txt").read_text(encoding="utf-8")
    assert "--- [SCENE" in script_text
    assert (proj_dir / "stage0i_inventory.json").exists()
    assert (proj_dir / "stage0i_identity.json").exists()
    assert (proj_dir / "stage0i_fair_use.json").exists()
    scores.close()


def test_run_accepts_zip_upload(tmp_path):
    proj_dir, upload = _make_project(tmp_path, as_zip=True)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    result = run_stage0i(proj_dir, cfg, scores, upload=upload, llm=FakeLLM())
    assert result["status"] == "done"
    assert result["panels"] == 2
    scores.close()


def test_run_requires_panels(tmp_path):
    projects_dir = tmp_path / "projects"
    seed = tmp_path / "seed.txt"
    seed.write_text("seed " * 10, encoding="utf-8")
    proj_dir = run.new_project("i0empty", seed, projects_dir=projects_dir, mode="0i")
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    with pytest.raises(Stage0IError):
        run_stage0i(proj_dir, cfg, scores, llm=FakeLLM())
    scores.close()
