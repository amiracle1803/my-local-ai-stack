"""Stage 0A (TRANSFORM) tests: mechanics extraction, originality design,
legal-proximity scoring gate, blueprint, and the full source->script run.
No network -- PipelineLLM is replaced by a fake implementing complete_json /
complete_text.
"""

from __future__ import annotations

import pytest

import run
from pipeline.config import PipelineConfig
from pipeline.scores import Scores
from pipeline.stage0a_transform import (
    Stage0AError,
    compute_legal_score,
    design_originality,
    extract_mechanics,
    run as run_stage0a,
)
from pipeline.schemas.stage0 import (
    MechanicsExtraction,
    TransformationMap,
)

# --------------------------------------------------------------------------
# fixtures / fake data
# --------------------------------------------------------------------------
MECHANICS = {
    "power_system_type": "cultivation",
    "power_mechanics": ["absorb qi from the earth", "breakthrough at bottlenecks"],
    "progression_model": "leveling",
    "conflict_engine": "zero-sum-competition",
    "conflict_specifics": "resources are finite, so rivals must be defeated",
    "protagonist_archetype": "reluctant-hero",
    "protagonist_behavioral_pattern": "avoids fighting until cornered",
    "emotional_hooks": ["loneliness of power"],
    "world_rules": ["qi is scarce"],
    "themes": ["sacrifice"],
    "what_makes_it_original": "combines cultivation with identity theft",
}

TMAP = {
    "world_design": {
        "name": "Ashen Reach",
        "geography": "a desert of black glass beneath a sky with two moons",
        "cultural_flavor": "mesoamerican-inspired",
        "visual_signature": "cities built on the backs of sleeping colossi",
        "what_is_scarce": "a breathable atmosphere",
    },
    "power_system_original": {
        "name": "Soul-Siphoning",
        "source_mechanic_used": "absorb qi from the earth",
        "new_skin": "steal memories from the dying instead of qi",
        "new_rules": ["memory debt", "forgotten skills"],
        "visual_manifestation": "golden thread pulled from a victim's ear",
    },
    "character_originals": [
        {
            "source_archetype": "reluctant-hero",
            "new_name": "Xilote",
            "new_personality": "a thief who steals memories he never asked for",
            "new_history": "was a grave-robber before inheriting the power",
            "new_relationship_network": "a sister who fears him, a rival who wants his secret",
        }
    ],
    "conflict_redesign": {
        "source_engine_used": "betrayal-from-within",
        "new_factions": ["The Order of Unbinding", "The Hollow Court"],
        "new_stakes": "the collective memory of the world",
        "new_inciting_event": "Xilote steals the memory of the last true king",
    },
    "original_commentary_layer": {
        "angle": "whether identity survives being remembered by others",
        "how_it_manifests": "the protagonist forgets his own past as he steals others'",
    },
}

BLUEPRINT = {
    "title": "The Last King",
    "logline": "Xilote must decide whether to return the world's memory or keep it.",
    "characters": [
        {
            "name": "Xilote",
            "role": "protagonist",
            "personality_core": "guilt-driven thief, calculating, protective",
            "episode_want": "survive the Order of Unbinding",
            "episode_fear": "forgetting his sister",
            "episode_arc_end": "accepts the burden of the world's memory",
            "new_or_recurring": "new",
            "if_recurring_existing_id": None,
        }
    ],
    "three_act_structure": {
        "act1": {
            "scenes": ["The Theft"],
            "inciting_incident": "Xilote steals the king's memory.",
            "establishes": "Memory is currency in the Ashen Reach.",
        },
        "act2": {
            "scenes": ["The Hunt"],
            "escalation": "The Order of Unbinding hunts him.",
            "midpoint_reversal": "Xilote learns the king's memory is the world's.",
            "what_breaks": "His sister is taken.",
        },
        "act3": {
            "scenes": ["The Choice"],
            "climax_decision": "Return the memory or keep his sister.",
            "cost": "He loses his own past either way.",
            "permanent_change": "The Ashen Reach remembers; Xilote forgets.",
        },
    },
    "scene_list": [
        {
            "number": 1,
            "title": "The Theft",
            "act": 1,
            "location": "The Hollow Court",
            "characters_present": ["Xilote"],
            "emotional_purpose": "urgency",
            "narrative_function": "inciting incident",
        },
        {
            "number": 2,
            "title": "The Hunt",
            "act": 2,
            "location": "The Ashen Reach",
            "characters_present": ["Xilote"],
            "emotional_purpose": "tension",
            "narrative_function": "escalation",
        },
        {
            "number": 3,
            "title": "The Choice",
            "act": 3,
            "location": "The Sleeping Colossus",
            "characters_present": ["Xilote"],
            "emotional_purpose": "sacrifice",
            "narrative_function": "climax decision",
        },
    ],
    "thematic_core": {
        "surface": "a heist in a dying world",
        "deeper": "memory is identity",
        "moral_question": "is it right to let a world forget to save one person?",
    },
}


class FakeLLM:
    """Stands in for PipelineLLM: returns canned mechanics/tmap/blueprint and
    deterministic prose for the shared scene-writer."""

    def __init__(self, mechanics=None, tmap=None, blueprint=None):
        self.mechanics = mechanics or dict(MECHANICS)
        self.tmap = tmap or dict(TMAP)
        self.blueprint = blueprint or dict(BLUEPRINT)
        self.json_calls = []
        self.text_calls = []

    def complete_json(self, prompt_file, context, schema, *, role="script", stage_hint="stage"):
        self.json_calls.append((stage_hint, prompt_file))
        if prompt_file == "s0a_mechanics.md":
            return schema.model_validate(self.mechanics)
        if prompt_file == "s0a_originality.md":
            return schema.model_validate(self.tmap)
        if prompt_file == "s0a_blueprint.md":
            return schema.model_validate(self.blueprint)
        raise AssertionError(f"unexpected JSON prompt {prompt_file!r}")

    def complete_text(self, prompt_file, context, *, role="script", stage_hint="stage"):
        self.text_calls.append(stage_hint)
        if prompt_file == "s0b_scene_prose.md":
            loc = context["location"]
            words = max(60, context["word_target"] - 20)
            text = '"We must go," said Xilote.'
            filler = " Ashen winds carried the memory of the dead across the black glass."
            while len(text.split()) < words:
                text += filler
            text += f" Silence answered in {loc}."
            return text
        if prompt_file == "s0b_critique.md":
            return '1. "the winds" - generic.'
        if prompt_file == "s0b_revise.md":
            return context["scene_text"]
        raise AssertionError(f"unexpected text prompt {prompt_file!r}")


def _make_project(tmp_path, *, mode="0a"):
    projects_dir = tmp_path / "projects"
    source = tmp_path / "source.txt"
    source.write_text(
        "A cultivator absorbs qi from the earth to grow stronger, but every "
        "breakthrough leaves the land barren. Rivals compete for the last "
        "veins of qi. " * 10,
        encoding="utf-8",
    )
    proj_dir = run.new_project("a0test", source, fps=30, projects_dir=projects_dir, mode=mode)
    return proj_dir, source


# --------------------------------------------------------------------------
# legal proximity scoring
# --------------------------------------------------------------------------
def test_legal_score_high_when_differentiated():
    mech = MechanicsExtraction.model_validate(MECHANICS)
    tmap = TransformationMap.model_validate(TMAP)
    legal = compute_legal_score(mech, tmap)
    assert legal.total >= 75
    assert legal.blocked is False


def test_legal_score_deducts_identical_conflict_engine():
    mech = MechanicsExtraction.model_validate(MECHANICS)
    tmap = TransformationMap.model_validate(TMAP)
    # Identical conflict engine with no new factions/stakes -> -20
    tmap.conflict_redesign.source_engine_used = mech.conflict_engine
    tmap.conflict_redesign.new_factions = []
    tmap.conflict_redesign.new_stakes = ""
    legal = compute_legal_score(mech, tmap)
    assert legal.total <= 80


def test_legal_score_blocks_below_50():
    mech = MechanicsExtraction.model_validate(MECHANICS)
    tmap = TransformationMap.model_validate(TMAP)
    # Hammer it down: identical conflict, copied mechanics, identical world rule.
    tmap.conflict_redesign.source_engine_used = mech.conflict_engine
    tmap.conflict_redesign.new_factions = []
    tmap.conflict_redesign.new_stakes = ""
    tmap.power_system_original.new_rules = list(mech.power_mechanics)
    tmap.world_design.geography = mech.world_rules[0]
    legal = compute_legal_score(mech, tmap)
    assert legal.blocked is True


# --------------------------------------------------------------------------
# pass-level LLM calls
# --------------------------------------------------------------------------
def test_extract_mechanics_calls_script_role():
    llm = FakeLLM()
    mech = extract_mechanics("some source text " * 500, llm)
    assert mech.power_system_type == "cultivation"
    assert llm.json_calls[0][1] == "s0a_mechanics.md"


def test_design_originality():
    llm = FakeLLM()
    tmap = design_originality(MechanicsExtraction.model_validate(MECHANICS), llm)
    assert tmap.world_design.name == "Ashen Reach"
    assert tmap.character_originals[0].new_name == "Xilote"


# --------------------------------------------------------------------------
# full run()
# --------------------------------------------------------------------------
def test_run_happy_path_writes_script_and_metric(tmp_path):
    proj_dir, source = _make_project(tmp_path)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    result = run_stage0a(proj_dir, cfg, scores, source_path=source, llm=FakeLLM())

    assert result["status"] == "done"
    assert scores.is_done("stage0")
    assert scores.has_metric("stage0", "structure_completeness")

    script_text = (proj_dir / "input" / "script.txt").read_text(encoding="utf-8")
    assert "--- [SCENE" in script_text
    assert (proj_dir / "stage0a_mechanics.json").exists()
    assert (proj_dir / "stage0a_transform_map.json").exists()
    assert (proj_dir / "stage0a_legal_score.json").exists()
    scores.close()


def test_run_requires_source_on_first_call(tmp_path):
    proj_dir, _ = _make_project(tmp_path)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    with pytest.raises(Stage0AError):
        run_stage0a(proj_dir, cfg, scores, llm=FakeLLM())
    scores.close()


def test_run_blocks_when_legal_score_below_50(tmp_path):
    proj_dir, source = _make_project(tmp_path)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    close = dict(TMAP)
    close["conflict_redesign"] = {
        "source_engine_used": "zero-sum-competition",
        "new_factions": [],
        "new_stakes": "",
        "new_inciting_event": "",
    }
    close["power_system_original"]["new_rules"] = list(MECHANICS["power_mechanics"])
    close["world_design"]["geography"] = "qi is scarce"
    with pytest.raises(Stage0AError):
        run_stage0a(proj_dir, cfg, scores, source_path=source, llm=FakeLLM(tmap=close))
    scores.close()


def test_run_awaiting_approval_then_resume(tmp_path):
    proj_dir, source = _make_project(tmp_path)
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    cfg.automation.auto_approve_transform_map = False
    llm = FakeLLM()

    result = run_stage0a(proj_dir, cfg, scores, source_path=source, llm=llm)
    assert result["status"] == "awaiting_approval"
    assert not scores.is_done("stage0")
    assert (proj_dir / "stage0a_transform_draft.json").exists()
    scores.close()

    # Resume: draft is promoted, prose generated.
    scores2 = Scores(proj_dir / "scores.sqlite")
    llm2 = FakeLLM()
    result2 = run_stage0a(proj_dir, cfg, scores2, llm=llm2)
    assert result2["status"] == "done"
    assert scores2.is_done("stage0")
    scores2.close()
