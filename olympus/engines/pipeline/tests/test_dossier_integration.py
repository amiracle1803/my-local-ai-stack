"""Dossier → downstream integration tests (world bible merge, 360-view assets,
screenplay/storyboard grounding) -- no live LLM or ComfyUI."""

from __future__ import annotations

from pathlib import Path

from pipeline.schemas.dossier import (
    CharacterDossier,
    DialogueEntry,
    Hair,
    LocationDossier,
    LocationView,
    SceneDossier,
    StoryDossier,
    StoryDossierMeta,
    load_dossier,
)
from pipeline.schemas.worldbible import (
    Appearance,
    Character,
    Location,
    WorldBible,
    WorldBibleMeta,
)
from pipeline.stage1_worldbible import merge_dossier_characters
from pipeline.stage1_world import merge_dossier_locations
from pipeline.stage2_screenplay import _dossier_context
from pipeline.stage1r_references import _location_views


def _write_dossier(project_dir: Path, dossier: StoryDossier) -> None:
    (project_dir / "intake").mkdir(parents=True, exist_ok=True)
    (project_dir / "intake" / "dossier.json").write_text(
        dossier.model_dump_json(), encoding="utf-8"
    )


def _minimal_bible() -> WorldBible:
    return WorldBible(
        story_id="s",
        characters=[
            Character(id="rei", name="Rei", appearance=Appearance(hair="violet hair")),
        ],
        locations=[Location(id="loc-misty-forest", name="Misty Forest")],
        meta=WorldBibleMeta(),
    )


# --------------------------------------------------------------------------
# increment 1 -- world bible consumes the dossier
# --------------------------------------------------------------------------


def test_merge_dossier_characters_enriches(tmp_path):
    _write_dossier(
        tmp_path,
        StoryDossier(
            characters=[
                CharacterDossier(
                    name="Rei", gender="female", race="human", age="17",
                    height="tall", key_skills=["hacking", "survival"],
                    family_background="orphan", general_background="courier",
                    friends=["Mika"],
                )
            ],
            meta=StoryDossierMeta(),
        ),
    )
    wb = _minimal_bible()
    merged = merge_dossier_characters(wb, tmp_path)
    assert merged == 1
    c = wb.characters[0]
    assert c.gender == "female" and c.race == "human" and c.age == "17"
    assert c.height == "tall"
    assert c.key_skills == ["hacking", "survival"]
    assert c.family_background == "orphan" and c.general_background == "courier"
    assert c.friends == ["Mika"]


def test_merge_dossier_characters_no_match_or_missing(tmp_path):
    wb = _minimal_bible()
    # no dossier file -> 0 merged, no error
    assert merge_dossier_characters(wb, tmp_path) == 0
    # dossier present but different name -> 0 merged
    _write_dossier(
        tmp_path, StoryDossier(characters=[CharacterDossier(name="Other")], meta=StoryDossierMeta())
    )
    assert merge_dossier_characters(wb, tmp_path) == 0


def test_merge_dossier_locations_360_views(tmp_path):
    _write_dossier(
        tmp_path,
        StoryDossier(
            locations=[
                LocationDossier(
                    id="misty_forest", name="Misty Forest", season="winter",
                    environment_features=["snow", "pine trees"],
                    views_360=[
                        LocationView(angle="north", description="dense pines"),
                        LocationView(angle="south", description="frozen stream"),
                    ],
                )
            ],
            meta=StoryDossierMeta(),
        ),
    )
    wb = _minimal_bible()
    merged = merge_dossier_locations(wb, tmp_path)
    assert merged == 1
    loc = wb.locations[0]
    assert loc.season == "winter"
    assert loc.environment_features == ["snow", "pine trees"]
    assert loc.angles == ["north", "south"]
    assert loc.views == [
        {"angle": "north", "description": "dense pines"},
        {"angle": "south", "description": "frozen stream"},
    ]


def test_load_dossier_returns_none_when_missing(tmp_path):
    assert load_dossier(tmp_path) is None


# --------------------------------------------------------------------------
# increment 2 -- 360-view asset node
# --------------------------------------------------------------------------


def test_location_views_prefers_dossier_views():
    loc = Location(
        id="x", name="X",
        views=[{"angle": "north", "description": "dense pines"}],
        angles=["north"],
    )
    assert _location_views(loc) == [("north", "dense pines")]


def test_location_views_falls_back_to_angles():
    loc = Location(id="x", name="X", angles=["top_down", "reverse_angle"])
    pairs = _location_views(loc)
    assert [p[0] for p in pairs] == ["top_down", "reverse_angle"]
    # descriptions are humanized, not empty
    assert all(p[1] for p in pairs)


def test_location_views_default_when_empty():
    loc = Location(id="x", name="X")
    assert len(_location_views(loc)) == 4


# --------------------------------------------------------------------------
# increment 3 -- screenplay/storyboard grounding
# --------------------------------------------------------------------------


def test_dossier_context_formats_scenes_and_dialogue():
    dossier = StoryDossier(
        scenes=[
            SceneDossier(number=1, location="Misty Forest", time_of_day="dusk",
                         season="winter", environment_features=["snow"]),
        ],
        dialogue=[
            DialogueEntry(scene_number=1, speaker="Rei", addressee="Mika",
                          text="Stay behind me.", body_movement="raises blade"),
        ],
    )
    scene_settings, dialogue_log = _dossier_context(dossier)
    assert "Scene 1 (Misty Forest)" in scene_settings
    assert "dusk" in scene_settings and "winter" in scene_settings and "snow" in scene_settings
    assert "Rei" in dialogue_log and "Mika" in dialogue_log
    assert "Stay behind me." in dialogue_log
    assert "raises blade" in dialogue_log


def test_dossier_context_none_placeholders():
    assert _dossier_context(StoryDossier()) == ("(none)", "(none)")
