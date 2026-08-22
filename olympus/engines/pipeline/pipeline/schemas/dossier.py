"""Stage 0 dossier -- rich intake extraction (``intake/dossier.json``).

The intake dossier is the *derived* story bible produced by reading the
finished ``input/script.txt``. It is strictly read-only with respect to the
script: every field here is extracted from (or, when absent, invented for) the
script, never written back into it. The ``source_hash`` in
:class:`StoryDossierMeta` fingerprints the script the dossier was extracted
from, so a later pass can detect drift the same way the story-pollution guard
does.

It sits *between* stage 0 (which produces the script) and stage 1 (which builds
the world bible). The world bible, screenplay, and storyboard stages consume
this richer, structured view of the story instead of re-scanning raw prose.

Character fields follow the user's request: appearance (clothing, eye color,
name, race, age, height, body build, gender, hair length), family background,
key skills/traits/behavior, general background, friends/family, and
relationships to other characters. Settings capture time of day, location,
season, and concrete environment features (snow, grass, trees, ...). Locations
also carry a **360 view** -- a set of camera angles that fully describe the
space for high-quality multi-angle asset generation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# 360-view default camera angles -- a full spatial coverage of any location,
# kept as a fallback when the model does not propose its own set. Matches the
# world-bible ``get_location_angles`` convention so a location always has at
# least one rendering angle for the panel/asset stages.
DEFAULT_360_ANGLES: list[str] = [
    "wide_establishing",
    "medium_shot",
    "closeup_counter",
    "over_shoulder",
    "top_down",
    "reverse_angle",
]


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------


class Hair(BaseModel):
    """Hair facts split into color / length / style for prompt composability."""

    color: str = ""
    length: str = ""  # e.g. "shoulder-length", "buzz cut", "waist-length"
    style: str = ""  # e.g. "straight", "wavy", "twin tails", "messy"


class FamilyMember(BaseModel):
    name: str = ""
    relation: str = ""  # e.g. "mother", "older brother", "adoptive father"


class Relationship(BaseModel):
    """One directed relationship edge to another character."""

    other_name: str = ""
    type: str = ""  # e.g. "friend", "rival", "mentor", "romantic interest"
    description: str = ""


class CharacterDossier(BaseModel):
    """Rich per-character intake profile."""

    name: str
    role: str = ""  # protagonist / antagonist / mentor / ally / obstacle / neutral
    gender: str = ""  # male / female / nonbinary / unknown
    race: str = ""  # species / race / ethnicity
    age: str = ""  # "17" or "mid-20s" -- free text
    height: str = ""
    body_build: str = ""
    hair: Hair = Field(default_factory=Hair)
    eyes: str = ""  # eye color
    skin: str = ""  # skin tone
    clothing: str = ""  # primary outfit description
    distinguishing_features: str = ""
    appearance_summary: str = ""  # full appearance paragraph (for prompts)

    personality_traits: list[str] = Field(default_factory=list)
    key_skills: list[str] = Field(default_factory=list)
    behavioral_patterns: list[str] = Field(default_factory=list)

    family_background: str = ""
    general_background: str = ""
    friends: list[str] = Field(default_factory=list)
    family: list[FamilyMember] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)

    wants: str = ""
    fears: str = ""
    arc_end: str = ""


# --------------------------------------------------------------------------
# Locations + 360 views
# --------------------------------------------------------------------------


class LocationView(BaseModel):
    """One camera angle in a location's 360-degree coverage."""

    angle: str = ""  # e.g. "north", "wide_establishing", "overhead", "closeup_counter"
    description: str = ""  # what this angle shows (for a stable sd_prompt)


class LocationDossier(BaseModel):
    """Rich per-location setting profile with a 360 view."""

    id: str = ""  # snake_case stable id
    name: str
    description: str = ""
    interior_exterior: str = ""  # interior / exterior / both
    time_of_day: str = ""  # primary time of day (e.g. "dusk")
    season: str = ""
    weather: str = ""
    lighting: str = ""
    environment_features: list[str] = Field(default_factory=list)  # snow, grass, trees, ...
    recurring: bool = False
    views_360: list[LocationView] = Field(default_factory=list)

    def angle_names(self) -> list[str]:
        """The set of 360-view angle labels, falling back to the default set."""
        names = [v.angle for v in self.views_360 if v.angle]
        return names or list(DEFAULT_360_ANGLES)


# --------------------------------------------------------------------------
# Scenes + dialogue
# --------------------------------------------------------------------------


class SceneDossier(BaseModel):
    """Per-scene setting facts (time of day, season, environment, lighting)."""

    number: int = 0  # authoritative value set from the scene marker, not the model
    title: str = ""
    location: str = ""
    time_of_day: str = ""
    season: str = ""
    lighting: str = ""
    environment_features: list[str] = Field(default_factory=list)
    characters_present: list[str] = Field(default_factory=list)


class DialogueEntry(BaseModel):
    """One spoken line: who says it, to whom, and what they do while saying it."""

    scene_number: int = 0  # authoritative value set from the scene marker
    speaker: str = ""
    addressee: str = ""  # to whom the line is spoken ("" = narrator / general)
    text: str = ""
    body_movement: str = ""  # gestures / blocking / expression while speaking
    tone: str = ""


# --------------------------------------------------------------------------
# Consolidated dossier
# --------------------------------------------------------------------------


class StoryDossierMeta(BaseModel):
    generated_at: str = ""
    source_hash: str = ""  # sha256 of the script the dossier was extracted from


class StoryDossier(BaseModel):
    """``intake/dossier.json`` -- the structured story bible extracted at intake."""

    title: str = ""
    logline: str = ""
    characters: list[CharacterDossier] = Field(default_factory=list)
    locations: list[LocationDossier] = Field(default_factory=list)
    scenes: list[SceneDossier] = Field(default_factory=list)
    dialogue: list[DialogueEntry] = Field(default_factory=list)
    meta: StoryDossierMeta = Field(default_factory=StoryDossierMeta)

    # Convenience lookups (mirror worldbible.WorldBible).
    def character(self, name: str) -> CharacterDossier | None:
        lowered = name.lower()
        for c in self.characters:
            if c.name.lower() == lowered:
                return c
        return None

    def location(self, loc_id: str) -> LocationDossier | None:
        for loc in self.locations:
            if loc.id == loc_id or loc.name.lower() == loc_id.lower():
                return loc
        return None

    def location_angles(self, loc_id: str) -> list[str]:
        loc = self.location(loc_id)
        return loc.angle_names() if loc else list(DEFAULT_360_ANGLES)


def load_dossier(project_dir: "Path | str") -> "StoryDossier | None":
    """Load ``intake/dossier.json`` if present, else ``None``.

    Lives here (schema module) so every downstream stage can import it without
    a circular import back into ``stage0_dossier``.
    """
    from pathlib import Path

    path = Path(project_dir) / "intake" / "dossier.json"
    if not path.exists():
        return None
    return StoryDossier.model_validate_json(path.read_text(encoding="utf-8"))
