"""AGI script scorer tests: env-flag logic, the scoring helper's metric
recording with a fake scorer (no torch / no checkpoint needed), and the
stage0 integration wiring. The real checkpoint is never loaded here."""

from __future__ import annotations

import json

import pytest

import run
from pipeline.agi_scorer import scorer_enabled
from pipeline.config import AgiConfig, PipelineConfig
from pipeline.scores import Scores
from pipeline.stage0_intake import run as run_stage0
from pipeline.stage0_intake import _script_quality_scores


# --------------------------------------------------------------------------
# scorer_enabled env override
# --------------------------------------------------------------------------
def test_scorer_enabled_defaults_to_config(monkeypatch):
    monkeypatch.delenv("AGI_SCORER_ENABLED", raising=False)
    on = AgiConfig(enabled=True)
    off = AgiConfig(enabled=False)
    assert scorer_enabled(on) is True
    assert scorer_enabled(off) is False


def test_scorer_enabled_env_override(monkeypatch):
    monkeypatch.setenv("AGI_SCORER_ENABLED", "0")
    assert scorer_enabled(AgiConfig(enabled=True)) is False
    monkeypatch.setenv("AGI_SCORER_ENABLED", "1")
    assert scorer_enabled(AgiConfig(enabled=False)) is True


# --------------------------------------------------------------------------
# _script_quality_scores with a fake scorer
# --------------------------------------------------------------------------
class FakeScorer:
    """No torch, no checkpoint -- scripted per-pair scores."""

    def __init__(self, values=None):
        self.values = values or {
            ("fidelity", "1"): 0.82,
            ("fidelity", "2"): 0.91,
            ("fidelity", "3"): 0.76,
            ("causal", "1-2"): 0.71,
            ("causal", "2-3"): 0.68,
            ("consistency", "Rin"): 0.88,
            ("consistency", "Kael"): 0.79,
        }
        self._closed = False

    def available(self) -> bool:
        return True

    def fidelity(self, scene_text, beat_text) -> float | None:
        for k in ("1", "2", "3"):
            if f"Scene {k}" in beat_text:
                return self.values[("fidelity", k)]
        return None

    def causal_flow(self, a_text, b_text) -> float | None:
        for k in ("1-2", "2-3"):
            if f"--- [SCENE {k.split('-')[0]}:" in a_text and f"--- [SCENE {k.split('-')[1]}:" in b_text:
                return self.values[("causal", k)]
        return None

    def consistency(self, profile_text, scene_text) -> float | None:
        for name in ("Rin", "Kael"):
            if name in profile_text:
                return self.values[("consistency", name)]
        return None

    def close(self) -> None:
        self._closed = True


def _sample_scene_records():
    from pipeline.stage0_intake import SceneProse, _scene_checks

    texts = {
        1: "--- [SCENE 1: The Warning] ---\nRin warns Kael the tower is failing.",
        2: "--- [SCENE 2: The Climb] ---\nStorms block the path to the summit.",
        3: "--- [SCENE 3: The Choice] ---\nRin decides to save Kael over the tower.",
    }
    out = []
    for n, t in texts.items():
        out.append(
            SceneProse(
                number=n, title=f"S{n}", text=t, word_count=len(t.split()),
                word_target=100, checks=_scene_checks(t), enforcement_applied=None,
            )
        )
    return out


def test_script_quality_scores_records_metrics(tmp_path):
    from pipeline.schemas.stage0 import StoryBlueprint

    blueprint = StoryBlueprint.model_validate_json(
        json.dumps(
            {
                "title": "T", "logline": "L",
                "characters": [
                    {"name": "Rin", "role": "protagonist",
                     "personality_core": "stubborn", "episode_want": "reach the tower",
                     "episode_fear": "losing her memories", "episode_arc_end": "accepts help",
                     "new_or_recurring": "new", "if_recurring_existing_id": None},
                    {"name": "Kael", "role": "ally",
                     "personality_core": "cautious", "episode_want": "protect Rin",
                     "episode_fear": "failing her", "episode_arc_end": "trusts Rin",
                     "new_or_recurring": "new", "if_recurring_existing_id": None},
                ],
                "three_act_structure": {
                    "act1": {"scenes": ["The Warning"], "inciting_incident": "I",
                             "establishes": "E"},
                    "act2": {"scenes": ["The Climb"], "escalation": "S",
                             "midpoint_reversal": "M", "what_breaks": "W"},
                    "act3": {"scenes": ["The Choice"], "climax_decision": "C",
                             "cost": "Co", "permanent_change": "P"},
                },
                "scene_list": [
                    {"number": 1, "title": "The Warning", "act": 1, "location": "Village Square",
                     "characters_present": ["Rin", "Kael"], "emotional_purpose": "urgency",
                     "narrative_function": "inciting incident"},
                    {"number": 2, "title": "The Climb", "act": 2, "location": "Mountain Path",
                     "characters_present": ["Rin", "Kael"], "emotional_purpose": "tension",
                     "narrative_function": "escalation"},
                    {"number": 3, "title": "The Choice", "act": 3, "location": "Tower Summit",
                     "characters_present": ["Rin", "Kael"], "emotional_purpose": "sacrifice",
                     "narrative_function": "climax decision"},
                ],
                "thematic_core": {"surface": "s", "deeper": "d", "moral_question": "m"},
            }
        )
    )
    scores = Scores(tmp_path / "scores.sqlite")
    metrics = _script_quality_scores(
        FakeScorer(), blueprint, _sample_scene_records(), scores
    )

    assert metrics["agi_fidelity"] == pytest.approx(0.83, abs=0.01)  # (0.82+0.91+0.76)/3
    assert metrics["agi_causal_flow"] == pytest.approx(0.695, abs=0.01)
    # Only Rin appears in the sample scene texts, so the mean is just Rin's.
    assert metrics["agi_consistency"] == pytest.approx(0.88, abs=0.01)

    # Per-unit fidelity rows also recorded.
    assert scores.metrics_for("stage0").get("agi_fidelity") == pytest.approx(
        metrics["agi_fidelity"], abs=0.0001
    )
    scores.close()


def test_script_quality_scores_none_when_unavailable(tmp_path):
    from pipeline.schemas.stage0 import StoryBlueprint

    class Offline:
        def available(self) -> bool:
            return False

    blueprint = StoryBlueprint.model_validate_json(
        json.dumps(
            {
                "title": "T", "logline": "L",
                "characters": [
                    {"name": "Rin", "role": "protagonist",
                     "personality_core": "x", "episode_want": "y",
                     "episode_fear": "z", "episode_arc_end": "w",
                     "new_or_recurring": "new", "if_recurring_existing_id": None},
                ],
                "three_act_structure": {
                    "act1": {"scenes": ["s"], "inciting_incident": "i", "establishes": "e"},
                    "act2": {"scenes": ["s"], "escalation": "s", "midpoint_reversal": "m",
                             "what_breaks": "w"},
                    "act3": {"scenes": ["s"], "climax_decision": "c", "cost": "c",
                             "permanent_change": "p"},
                },
                "scene_list": [
                    {"number": 1, "title": "T1", "act": 1, "location": "L",
                     "characters_present": ["Rin"], "emotional_purpose": "e",
                     "narrative_function": "n"},
                ],
                "thematic_core": {"surface": "s", "deeper": "d", "moral_question": "m"},
            }
        )
    )
    scores = Scores(tmp_path / "scores.sqlite")
    assert _script_quality_scores(Offline(), blueprint, _sample_scene_records(), scores) == {}
    scores.close()


def test_script_quality_scores_skips_when_scorer_none(tmp_path):
    from pipeline.schemas.stage0 import StoryBlueprint

    blueprint = StoryBlueprint.model_validate_json(
        json.dumps(
            {
                "title": "T", "logline": "L", "characters": [],
                "three_act_structure": {
                    "act1": {"scenes": ["s"], "inciting_incident": "i", "establishes": "e"},
                    "act2": {"scenes": ["s"], "escalation": "s", "midpoint_reversal": "m",
                             "what_breaks": "w"},
                    "act3": {"scenes": ["s"], "climax_decision": "c", "cost": "c",
                             "permanent_change": "p"},
                },
                "scene_list": [],
                "thematic_core": {"surface": "s", "deeper": "d", "moral_question": "m"},
            }
        )
    )
    scores = Scores(tmp_path / "scores.sqlite")
    assert _script_quality_scores(None, blueprint, [], scores) == {}
    scores.close()


# --------------------------------------------------------------------------
# stage0 integration: scorer injected, metrics recorded, model closed
# --------------------------------------------------------------------------
def _make_project(tmp_path, *, word_target=600):
    projects_dir = tmp_path / "projects"
    brief_file = tmp_path / "brief.md"
    brief_file.write_text(
        f"---\nword_target: {word_target}\n---\n"
        "A fantasy episode about Rin and Kael racing to save a failing tower.\n",
        encoding="utf-8",
    )
    return run.new_project("agistage0", brief_file, fps=30, projects_dir=projects_dir), brief_file


def _fake_llm():
    from test_stage0 import FakeLLM

    return FakeLLM(scene_word_targets={1: 200, 2: 200, 3: 200})


def test_run_stage0_with_fake_scorer_records_agi_metrics(tmp_path):
    from pipeline.schemas.stage0 import StoryBlueprint

    proj_dir, brief_file = _make_project(tmp_path)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    fake = FakeScorer()

    result = run_stage0(proj_dir, cfg, scores, brief_path=brief_file, llm=_fake_llm(), scorer=fake)

    assert result["status"] == "done"
    assert "agi" in result and result["agi"]
    assert fake._closed is True  # scorer released after the pass

    # The optional metrics do NOT appear in missing_metrics (not mandatory).
    assert scores.missing_metrics("stage0") == []
    metrics = scores.metrics_for("stage0")
    assert "agi_fidelity" in metrics
    assert "agi_consistency" in metrics
    scores.close()


def test_run_stage0_no_scorer_still_succeeds(tmp_path):
    proj_dir, brief_file = _make_project(tmp_path)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()

    result = run_stage0(proj_dir, cfg, scores, brief_path=brief_file, llm=_fake_llm(), scorer=None)

    assert result["status"] == "done"
    assert scores.missing_metrics("stage0") == []
    assert "agi" in result and result["agi"] == {}
    scores.close()


def test_run_stage0_auto_disabled_by_env(tmp_path, monkeypatch):
    """With AGI_SCORER_ENABLED=0 (conftest default), stage0 does not try to
    load torch/the checkpoint when no scorer is passed."""
    proj_dir, brief_file = _make_project(tmp_path)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    assert cfg.agi.enabled is True  # config says on, env override must win

    monkeypatch.setenv("AGI_SCORER_ENABLED", "0")
    result = run_stage0(proj_dir, cfg, scores, brief_path=brief_file, llm=_fake_llm())
    assert result["status"] == "done"
    assert result["agi"] == {}
    scores.close()
