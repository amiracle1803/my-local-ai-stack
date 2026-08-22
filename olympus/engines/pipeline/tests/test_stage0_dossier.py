"""Stage 0 dossier -- rich intake extraction tests (schema + pure helpers +
read-only invariant, no live LLM)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.schemas.dossier import (
    DEFAULT_360_ANGLES,
    CharacterDossier,
    DialogueEntry,
    Hair,
    LocationDossier,
    LocationView,
    Relationship,
    SceneDossier,
    StoryDossier,
    StoryDossierMeta,
)
from pipeline import stage0_dossier
from pipeline.blueprint import create_blueprint
from pipeline.scores import Scores


# --------------------------------------------------------------------------
# schema round-trip
# --------------------------------------------------------------------------


def _sample_dossier() -> StoryDossier:
    return StoryDossier(
        title="Test Episode",
        logline="A hero rises.",
        characters=[
            CharacterDossier(
                name="Rei",
                role="protagonist",
                gender="female",
                race="human",
                age="17",
                height="tall",
                body_build="slender",
                hair=Hair(color="crimson", length="shoulder-length", style="straight"),
                eyes="cyan",
                skin="fair",
                clothing="black jacket, white shirt",
                distinguishing_features="scar over left eye",
                personality_traits=["brave", "impulsive"],
                key_skills=["swordsmanship"],
                behavioral_patterns=["clenches fist when angry"],
                family_background="orphan",
                general_background="village sword apprentice",
                friends=["Mika"],
                family=[],
                relationships=[Relationship(other_name="Mika", type="friend", description="childhood friend")],
                wants="protect her village",
                fears="losing Mika",
                arc_end="accepts responsibility",
            )
        ],
        locations=[
            LocationDossier(
                id="misty_forest",
                name="Misty Forest",
                environment_features=["snow", "pine trees", "tall grass"],
                season="winter",
                views_360=[
                    LocationView(angle="north", description="dense pines"),
                    LocationView(angle="south", description="frozen stream"),
                ],
            )
        ],
        scenes=[SceneDossier(number=1, title="Arrival", location="Misty Forest", time_of_day="dusk")],
        dialogue=[DialogueEntry(scene_number=1, speaker="Rei", addressee="Mika", text="Stay behind me.", body_movement="raises blade")],
        meta=StoryDossierMeta(generated_at="2026-08-22T00:00:00Z", source_hash="abc123"),
    )


def test_story_dossier_roundtrip():
    d = _sample_dossier()
    raw = d.model_dump_json()
    back = StoryDossier.model_validate_json(raw)
    assert back.title == "Test Episode"
    assert back.characters[0].name == "Rei"
    assert back.characters[0].hair.color == "crimson"
    assert back.locations[0].environment_features == ["snow", "pine trees", "tall grass"]
    assert back.dialogue[0].addressee == "Mika"


def test_character_dossier_fields_complete():
    d = _sample_dossier().characters[0]
    # The user-requested fields all exist on the model.
    for attr in (
        "gender", "race", "age", "height", "body_build", "eyes", "skin",
        "clothing", "distinguishing_features", "family_background",
        "general_background", "friends", "family", "relationships",
        "key_skills", "personality_traits", "behavioral_patterns",
    ):
        assert hasattr(d, attr), attr
    assert d.hair.length and d.hair.style and d.hair.color


# --------------------------------------------------------------------------
# 360 views
# --------------------------------------------------------------------------


def test_location_360_default_angles_when_empty():
    loc = LocationDossier(name="Empty")
    assert loc.angle_names() == DEFAULT_360_ANGLES


def test_location_360_custom_angles():
    loc = _sample_dossier().locations[0]
    assert loc.angle_names() == ["north", "south"]


def test_dossier_location_angles_fallback():
    d = _sample_dossier()
    assert d.location_angles("misty_forest") == ["north", "south"]
    assert d.location_angles("nonexistent") == DEFAULT_360_ANGLES


def test_dossier_character_and_location_lookup():
    d = _sample_dossier()
    assert d.character("REI").role == "protagonist"
    assert d.character("nobody") is None
    assert d.location("Misty Forest").id == "misty_forest"


# --------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------


def test_split_scenes_with_markers():
    script = (
        "--- [SCENE 1: Arrival] ---\n\nRei walked in.\n\n"
        "--- [SCENE 2: The Gate] ---\n\nMika waited.\n"
    )
    scenes = stage0_dossier._split_scenes(script)
    assert [n for n, _, _ in scenes] == [1, 2]
    assert scenes[0][1] == "Arrival"
    assert "Rei walked in" in scenes[0][2]
    assert "Mika waited" in scenes[1][2]


def test_split_scenes_no_markers():
    script = "A single block of text with no scene markers."
    scenes = stage0_dossier._split_scenes(script)
    assert scenes == [(1, "", script)]


def test_unique_preserving_order():
    assert stage0_dossier._unique_preserving_order(["Forest", "forest", "Gate", "Forest"]) == [
        "Forest", "Gate"
    ]


def test_script_hash_is_stable():
    a = stage0_dossier._script_hash("hello")
    b = stage0_dossier._script_hash("hello")
    assert a == b and len(a) == 64
    assert a != stage0_dossier._script_hash("Hello")


# --------------------------------------------------------------------------
# read-only invariant + mocked extraction
# --------------------------------------------------------------------------


class _FakeLLM:
    """Returns canned schema objects keyed by prompt file -- no live Ollama."""

    def complete_json(self, prompt_file, context, schema, **kwargs):
        if prompt_file == "s0d_character.md":
            return CharacterDossier(
                name=context["character_name"],
                gender="female",
                hair=Hair(color="crimson", length="long", style="straight"),
            )
        if prompt_file == "s0d_scene.md":
            return SceneDossier(number=context["scene_number"], location="Misty Forest", time_of_day="dusk")
        if prompt_file == "s0d_location.md":
            return LocationDossier(
                id="misty_forest",
                name=context["location_name"],
                season="winter",
                environment_features=["snow", "pine trees"],
                views_360=[LocationView(angle="north", description="pines")],
            )
        if prompt_file == "s0d_dialogue.md":
            return stage0_dossier._DialogueLines(
                lines=[DialogueEntry(speaker="Rei", addressee="Mika", text="Hi.")]
            )
        raise AssertionError(f"unexpected prompt file: {prompt_file}")


def _make_project(tmp_path: Path) -> Path:
    script = "--- [SCENE 1: Arrival] ---\n\nRei and Mika walked into the Misty Forest.\n"
    project_dir = tmp_path / "proj"
    (project_dir / "input").mkdir(parents=True)
    (project_dir / "input" / "script.txt").write_text(script, encoding="utf-8")
    bp = create_blueprint(script, slug="proj")
    bp.write(project_dir)
    return project_dir


def test_run_writes_dossier_and_leaves_script_untouched(tmp_path, monkeypatch):
    project_dir = _make_project(tmp_path)
    script_before = (project_dir / "input" / "script.txt").read_text(encoding="utf-8")

    # Avoid the chunked LLM name scan; feed a fixed cast directly.
    monkeypatch.setattr(stage0_dossier, "scan_characters", lambda *a, **k: ["Rei", "Mika"])

    from pipeline.config import PipelineConfig
    scores = Scores(project_dir / "scores.sqlite")
    try:
        result = stage0_dossier.run(
            project_dir, PipelineConfig.load(), scores, llm=_FakeLLM()
        )
    finally:
        scores.close()

    assert result["status"] == "done"
    assert result["characters"] == 2
    assert result["locations"] == 1
    assert result["scenes"] == 1
    assert result["dialogue_lines"] == 1

    # READ-ONLY: the script is byte-identical after extraction.
    script_after = (project_dir / "input" / "script.txt").read_text(encoding="utf-8")
    assert script_after == script_before

    # Dossier written with source_hash provenance.
    d = StoryDossier.model_validate_json(
        (project_dir / "intake" / "dossier.json").read_text(encoding="utf-8")
    )
    assert d.characters[0].name == "Rei"
    assert d.locations[0].environment_features == ["snow", "pine trees"]
    assert d.dialogue[0].addressee == "Mika"
    assert d.meta.source_hash == stage0_dossier._script_hash(script_before)


def test_stage_done_and_metrics_recorded(tmp_path, monkeypatch):
    project_dir = _make_project(tmp_path)
    monkeypatch.setattr(stage0_dossier, "scan_characters", lambda *a, **k: ["Rei"])
    from pipeline.config import PipelineConfig
    scores = Scores(project_dir / "scores.sqlite")
    try:
        stage0_dossier.run(project_dir, PipelineConfig.load(), scores, llm=_FakeLLM())
        assert scores.is_done("stage0_dossier")
        metrics = scores.metrics_for("stage0_dossier")
        assert metrics["characters_found"] == 1.0
        assert metrics["views_360_avg"] == 1.0
    finally:
        scores.close()
