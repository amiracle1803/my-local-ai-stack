"""Stage 0B (GENERATE) tests: brief parsing, word-count enforcement, per-scene
checks, integration validations, the awaiting_approval pause/resume path, and
the mandatory structure_completeness metric. No network -- PipelineLLM is
replaced by a small in-test fake implementing the same two methods
(complete_json / complete_text) stage0_intake.run() actually calls.
"""

from __future__ import annotations

import json

import pytest

import run
from pipeline.config import PipelineConfig
from pipeline.scores import Scores
from pipeline.stage0_intake import (
    Stage0Error,
    _enforce_word_count,
    _scene_checks,
    load_brief,
    run as run_stage0,
)

# --------------------------------------------------------------------------
# fixtures / fake data
# --------------------------------------------------------------------------
BLUEPRINT_DATA = {
    "title": "The Falling Tower",
    "logline": "Rin must reach the tower before dawn or lose her memories forever.",
    "characters": [
        {
            "name": "Rin",
            "role": "protagonist",
            "personality_core": "stubborn, guilt-driven, quick to act",
            "episode_want": "reach the tower before dawn",
            "episode_fear": "losing her memories",
            "episode_arc_end": "accepts Kael's help",
            "new_or_recurring": "new",
            "if_recurring_existing_id": None,
        },
        {
            "name": "Kael",
            "role": "ally",
            "personality_core": "cautious, loyal, dry humor",
            "episode_want": "protect Rin",
            "episode_fear": "failing her again",
            "episode_arc_end": "trusts Rin's judgment",
            "new_or_recurring": "new",
            "if_recurring_existing_id": None,
        },
    ],
    "three_act_structure": {
        "act1": {
            "scenes": ["The Warning"],
            "inciting_incident": "A courier arrives with news the tower is failing.",
            "establishes": "Rin's memories are tied to the tower.",
        },
        "act2": {
            "scenes": ["The Climb"],
            "escalation": "Storms block the mountain path.",
            "midpoint_reversal": "Rin learns Kael already knew the tower was failing.",
            "what_breaks": "Rin's trust in Kael.",
        },
        "act3": {
            "scenes": ["The Choice"],
            "climax_decision": "Save the tower or save Kael.",
            "cost": "Rin loses part of her memory regardless.",
            "permanent_change": "The tower falls; Rin remembers only fragments.",
        },
    },
    "scene_list": [
        {
            "number": 1,
            "title": "The Warning",
            "act": 1,
            "location": "Village Square",
            "characters_present": ["Rin", "Kael"],
            "emotional_purpose": "urgency",
            "narrative_function": "inciting incident",
        },
        {
            "number": 2,
            "title": "The Climb",
            "act": 2,
            "location": "Mountain Path",
            "characters_present": ["Rin", "Kael"],
            "emotional_purpose": "tension",
            "narrative_function": "escalation",
        },
        {
            "number": 3,
            "title": "The Choice",
            "act": 3,
            "location": "Tower Summit",
            "characters_present": ["Rin", "Kael"],
            "emotional_purpose": "sacrifice",
            "narrative_function": "climax decision",
        },
    ],
    "thematic_core": {
        "surface": "a race against time",
        "deeper": "memory vs. sacrifice",
        "moral_question": "is it worth forgetting yourself to save someone else?",
    },
}

_FILLER = (
    " Wind howled across the ridge as thought and memory blurred together in "
    "the cold, and every step forward cost more than the last."
)


def _scene_text(target_words: int, location: str) -> str:
    """Deterministic scene prose sized near ``target_words``, opening on
    dialogue and ending with a location-tagged, distinct closing beat."""
    text = '"We need to hurry," Rin said, glancing at Kael.'
    while len(text.split()) < max(target_words - 20, 30):
        text += _FILLER
    text += f" Silence answered instead in {location}, and nothing stayed the same."
    return text


class FakeLLM:
    """Stands in for PipelineLLM: same public surface, no HTTP."""

    def __init__(self, scene_word_targets: dict[int, int] | None = None):
        self.scene_word_targets = scene_word_targets or {1: 300, 2: 300, 3: 390}
        self.json_calls: list[str] = []
        self.text_calls: list[str] = []

    def complete_json(self, prompt_file, context, schema, *, role="script", stage_hint="stage"):
        self.json_calls.append(stage_hint)
        return schema.model_validate(BLUEPRINT_DATA)

    def complete_text(self, prompt_file, context, *, role="script", stage_hint="stage"):
        self.text_calls.append(stage_hint)
        if prompt_file == "s0b_scene_prose.md":
            n = context["scene_number"]
            return _scene_text(self.scene_word_targets[n], context["location"])
        if prompt_file == "s0b_critique.md":
            return '1. "the ridge" - generic scenery filler.'
        if prompt_file == "s0b_revise.md":
            guidance = context.get("guidance", "")
            if "too long" in guidance:
                words = context["scene_text"].split()
                return " ".join(words[: len(words) // 3])
            if "too short" in guidance:
                return context["scene_text"] + (" extra descriptive word") * 300
            # normal critique-based revise: pass the draft through unchanged.
            return context["scene_text"]
        raise AssertionError(f"unexpected prompt file {prompt_file!r}")


def _make_project(tmp_path, *, word_target=900):
    projects_dir = tmp_path / "projects"
    brief_file = tmp_path / "brief.md"
    brief_file.write_text(
        f"---\nword_target: {word_target}\n---\n"
        "A fantasy episode about Rin and Kael racing to save a failing tower "
        "before dawn.\n",
        encoding="utf-8",
    )
    proj_dir = run.new_project("m1test", brief_file, fps=30, projects_dir=projects_dir)
    return proj_dir, brief_file


# --------------------------------------------------------------------------
# load_brief
# --------------------------------------------------------------------------
def test_load_brief_parses_frontmatter_and_body(tmp_path):
    p = tmp_path / "brief.md"
    p.write_text(
        "---\nword_target: 600\nstyle_exemplars:\n  - \"Example passage one.\"\n---\n"
        "Genre: fantasy. Tone: hopeful.\n",
        encoding="utf-8",
    )
    brief = load_brief(p)
    assert brief.word_target == 600
    assert brief.style_exemplars == ["Example passage one."]
    assert "Genre: fantasy" in brief.text


def test_load_brief_missing_word_target_raises(tmp_path):
    p = tmp_path / "brief.md"
    p.write_text("---\nfoo: bar\n---\nSome brief text.\n", encoding="utf-8")
    with pytest.raises(Stage0Error):
        load_brief(p)


def test_load_brief_empty_body_raises(tmp_path):
    p = tmp_path / "brief.md"
    p.write_text("---\nword_target: 500\n---\n\n", encoding="utf-8")
    with pytest.raises(Stage0Error):
        load_brief(p)


def test_load_brief_non_integer_word_target_raises(tmp_path):
    p = tmp_path / "brief.md"
    p.write_text("---\nword_target: not-a-number\n---\nSome text.\n", encoding="utf-8")
    with pytest.raises(Stage0Error):
        load_brief(p)


# --------------------------------------------------------------------------
# per-scene automated checks
# --------------------------------------------------------------------------
def test_scene_checks_all_pass():
    opening = (
        '"We have to go now," Rin shouted, already running for the gate. '
        "Kael followed close behind, boots skidding across the wet cobblestones "
        "of the crowded market square as merchants scattered from their path "
        "and startled birds burst upward from the rooftops in a sudden panicked "
        "wave, the whole square erupting into shouting and scrambling confusion."
    )
    ending = (
        "By the time silence finally settled over the tower's broken summit, "
        "nothing between them remained the same: Rin no longer trusted the plan "
        "she had clung to since dawn, and Kael, kneeling beside the shattered "
        "stone archway, understood for the first time exactly what surrender "
        "would eventually cost them both in the seasons still to come."
    )
    checks = _scene_checks(f"{opening} {ending}")
    assert checks.opens_on_action_or_dialogue is True
    assert checks.has_dialogue is True
    assert checks.ends_differently is True
    assert checks.flags == []


def test_scene_checks_flags_static_description_opener():
    text = (
        "The village square was quiet and the morning mist hung low over the "
        "empty market stalls, drifting slowly between the shuttered windows "
        "as the world outside stayed exactly as it always was."
    )
    checks = _scene_checks(text)
    assert checks.opens_on_action_or_dialogue is False
    assert "opens_on_action_or_dialogue" in checks.flags


def test_scene_checks_flags_missing_dialogue():
    text = (
        "Rin ran through the square, ducking past the stalls. She reached "
        "the gate and did not stop, and by the time she crossed into the "
        "tower grounds the sun had already begun to rise over the ridge."
    )
    checks = _scene_checks(text)
    assert checks.has_dialogue is False
    assert "has_dialogue" in checks.flags


def test_scene_checks_flags_static_ending():
    # First and last 50 words share almost all vocabulary -> "didn't change".
    repeated = "the quiet village square stayed calm and still all night long "
    text = '"Nothing is happening," Rin said. ' + repeated * 12
    checks = _scene_checks(text)
    assert checks.ends_differently is False
    assert "ends_differently" in checks.flags


# --------------------------------------------------------------------------
# word-count enforcement
# --------------------------------------------------------------------------
def _ctx():
    return {"scene_text": "placeholder", "scene_title": "t", "location": "loc"}


def test_enforce_word_count_condenses_when_too_long():
    text = " ".join(["word"] * 200)
    llm = FakeLLM()
    out_text, applied = _enforce_word_count(text, 100, {**_ctx(), "scene_text": text}, llm, 1)
    assert applied == "condensed"
    assert len(out_text.split()) < 200
    assert llm.text_calls == ["stage0_scene1_condense"]


def test_enforce_word_count_expands_when_too_short():
    text = " ".join(["word"] * 30)
    llm = FakeLLM()
    out_text, applied = _enforce_word_count(text, 100, {**_ctx(), "scene_text": text}, llm, 2)
    assert applied == "expanded"
    assert len(out_text.split()) > 30
    assert llm.text_calls == ["stage0_scene2_expand"]


def test_enforce_word_count_leaves_within_band_untouched():
    text = " ".join(["word"] * 95)
    llm = FakeLLM()
    out_text, applied = _enforce_word_count(text, 100, {**_ctx(), "scene_text": text}, llm, 3)
    assert applied is None
    assert out_text == text
    assert llm.text_calls == []  # no extra LLM call made


def test_enforce_word_count_zero_target_noop():
    llm = FakeLLM()
    out_text, applied = _enforce_word_count("anything here", 0, _ctx(), llm, 1)
    assert applied is None
    assert out_text == "anything here"


# --------------------------------------------------------------------------
# full stage0_intake.run() -- blueprint round-trip, integration, metric
# --------------------------------------------------------------------------
def test_run_happy_path_records_metric_and_writes_script(tmp_path):
    proj_dir, brief_file = _make_project(tmp_path, word_target=900)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    llm = FakeLLM()

    result = run_stage0(proj_dir, cfg, scores, brief_path=brief_file, llm=llm)

    assert result["status"] == "done"
    assert scores.is_done("stage0")
    assert scores.has_metric("stage0", "structure_completeness")
    sc = scores.metrics_for("stage0")["structure_completeness"]
    assert 0.0 <= sc <= 1.0

    script_text = (proj_dir / "input" / "script.txt").read_text(encoding="utf-8")
    assert "--- [SCENE 1: The Warning] ---" in script_text
    assert "--- [SCENE 2: The Climb] ---" in script_text
    assert "--- [SCENE 3: The Choice] ---" in script_text

    integration = json.loads((proj_dir / "stage0_integration.json").read_text(encoding="utf-8"))
    assert integration["missing_character_names"] == []
    assert integration["missing_location_names"] == []
    # the climax scene (390-word target vs ~990 total) exceeds the 30% cap.
    assert 3 in integration["oversized_scenes"]

    from pipeline.blueprint import Blueprint, compute_title_hash

    bp = Blueprint.load(proj_dir)
    assert bp.stages["stage0"].status == "done"
    assert bp.title_hash == compute_title_hash(script_text)

    assert (proj_dir / "stage0_blueprint.json").exists()
    assert (proj_dir / "stage0_scenes.json").exists()
    scores.close()


def test_run_missing_character_is_reported(tmp_path):
    proj_dir, brief_file = _make_project(tmp_path, word_target=900)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()

    class DropsKaelLLM(FakeLLM):
        def complete_text(self, prompt_file, context, *, role="script", stage_hint="stage"):
            text = super().complete_text(prompt_file, context, role=role, stage_hint=stage_hint)
            if prompt_file == "s0b_scene_prose.md":
                text = text.replace("Kael", "").replace("kael", "")
            return text

    result = run_stage0(proj_dir, cfg, scores, brief_path=brief_file, llm=DropsKaelLLM())
    assert result["status"] == "done"
    integration = json.loads((proj_dir / "stage0_integration.json").read_text(encoding="utf-8"))
    assert "Kael" in integration["missing_character_names"]
    scores.close()


def test_awaiting_approval_pauses_then_resumes(tmp_path):
    proj_dir, brief_file = _make_project(tmp_path, word_target=900)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    cfg.automation.auto_approve_blueprint = False
    llm = FakeLLM()

    result = run_stage0(proj_dir, cfg, scores, brief_path=brief_file, llm=llm)
    assert result["status"] == "awaiting_approval"
    assert (proj_dir / "blueprint_draft.json").exists()
    assert not (proj_dir / "stage0_blueprint.json").exists()
    assert not scores.is_done("stage0")
    assert llm.json_calls == ["stage0_blueprint"]
    assert llm.text_calls == []  # Pass 2 must not have started

    from pipeline.blueprint import Blueprint

    bp = Blueprint.load(proj_dir)
    assert bp.stages["stage0"].status == "awaiting_approval"

    # Resume: draft is picked up and promoted even though auto_approve is
    # still false -- rerunning stage0 means the draft has been reviewed.
    llm2 = FakeLLM()
    result2 = run_stage0(proj_dir, cfg, scores, llm=llm2)
    assert result2["status"] == "done"
    assert llm2.json_calls == []  # Pass 1 was not re-run
    assert scores.is_done("stage0")
    scores.close()


def test_run_requires_brief_on_first_call(tmp_path):
    projects_dir = tmp_path / "projects"
    script = tmp_path / "seed.txt"
    script.write_text("placeholder seed text. " * 20, encoding="utf-8")
    proj_dir = run.new_project("nobreif", script, fps=24, projects_dir=projects_dir)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    with pytest.raises(Stage0Error):
        run_stage0(proj_dir, cfg, scores, llm=FakeLLM())
    scores.close()


# --------------------------------------------------------------------------
# run.py CLI integration (--brief wiring)
# --------------------------------------------------------------------------
def test_run_stage_cli_wires_brief_through(tmp_path, monkeypatch):
    proj_dir, brief_file = _make_project(tmp_path, word_target=900)

    fake = FakeLLM()
    monkeypatch.setattr(
        "pipeline.stage0_intake.PipelineLLM",
        lambda *a, **k: fake,
    )

    result = run.run_stage(
        "m1test", "stage0", projects_dir=proj_dir.parent, brief_path=brief_file
    )
    assert result["status"] == "done"
