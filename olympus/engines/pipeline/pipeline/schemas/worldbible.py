"""Stage 1 (WORLD BIBLE) data contracts, part 1 of 2 (M2a): character scan +
per-character profile extraction (original spec STAGE 1, Steps 1-2). ``Character``
is the exact Step 2 output schema; ``WorldBible`` carries characters plus
optional slots that M2b (world/lore extraction, contradiction detection,
creative expansion -- Steps 3-5) will fill in.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Appearance(BaseModel):
    """Exact, thumbnail-recognizable appearance facts (original spec Step 2)."""

    hair: str = ""
    eyes: str = ""
    skin: str = ""
    build: str = ""
    clothing_primary: str = ""
    distinguishing_feature: str = ""


class SpeechStyle(BaseModel):
    category: str = ""
    avg_words_per_line: str = ""  # bucket, e.g. "short" | "medium" | "long"
    vocabulary_register: str = ""
    distinctive_patterns: str = ""


class Personality(BaseModel):
    traits: list[str] = Field(default_factory=list)  # 5 behavioral-pattern traits
    core_drive: str = ""
    core_fear: str = ""


class ArcThisEpisode(BaseModel):
    starts: str = ""
    ends: str = ""


class Provenance(BaseModel):
    """Which full-script chunk (Step 1's 8000/400 chunking) evidenced this
    character -- lets a later pass trace a profile field back to source text."""

    chunk_index: int


class FamilyMember(BaseModel):
    """One relative: name + relation (merged from the stage0 dossier)."""

    name: str = ""
    relation: str = ""  # e.g. "mother", "older brother", "adoptive father"


class CharacterRelationship(BaseModel):
    """One directed relationship edge to another character (from the dossier)."""

    other_name: str = ""
    type: str = ""  # e.g. "friend", "rival", "mentor", "romantic interest"
    description: str = ""


class Character(BaseModel):
    """Original spec Step 2 output schema (verbatim key fields)."""

    id: str  # stable snake_case
    name: str
    aliases: list[str] = Field(default_factory=list)
    appearance: Appearance = Field(default_factory=Appearance)
    appearance_invented: bool = False  # true if any appearance field was invented (not in script)
    sd_prompt: str = ""  # 40-60 words, appearance only, no camera/scene/lighting
    voice_id_suggestion: str = ""
    speech_style: SpeechStyle = Field(default_factory=SpeechStyle)
    personality: Personality = Field(default_factory=Personality)
    role: str = ""
    arc_this_episode: ArcThisEpisode = Field(default_factory=ArcThisEpisode)
    first_episode: str = ""
    provenance: list[Provenance] = Field(default_factory=list)

    # Rich intake fields (merged from the stage0 dossier when present).
    gender: str = ""  # male / female / nonbinary / unknown
    race: str = ""  # species / race / ethnicity
    age: str = ""
    height: str = ""
    key_skills: list[str] = Field(default_factory=list)
    family_background: str = ""
    general_background: str = ""
    friends: list[str] = Field(default_factory=list)
    family: list[FamilyMember] = Field(default_factory=list)
    relationships: list[CharacterRelationship] = Field(default_factory=list)
    views: list[dict] = Field(default_factory=list)  # character pose/expression views [{angle, description}]

    def appearance_spec(self) -> str:
        """A compact canonical appearance spec for on-model QC.

        Consumed by the stage3b panel vision gate and the stage_vlm_review clip
        gate to check generated output against the character's source-of-truth
        look (hair, eyes, skin, build, outfit, distinguishing feature, plus the
        dossier-rich gender/race/height). Falls back to ``sd_prompt`` when the
        structured fields are empty.
        """
        a = self.appearance
        facts: list[str] = []
        for label, value in (
            ("hair", a.hair),
            ("eyes", a.eyes),
            ("skin", a.skin),
            ("build", a.build),
            ("outfit", a.clothing_primary),
            ("distinguishing", a.distinguishing_feature),
            ("gender", self.gender),
            ("race", self.race),
            ("height", self.height),
        ):
            if value and value.strip():
                facts.append(f"{label}={value.strip()}")
        if facts:
            return f"{self.name}: " + ", ".join(facts)
        return self.sd_prompt or f"{self.name}: (no canonical appearance)"

    def appearance_facts(self) -> dict[str, str]:
        """The structured canonical appearance facts (hair/eyes/skin/outfit) for
        code-side comparison in the extract-then-compare on-model gate."""
        a = self.appearance
        return {
            "hair": a.hair,
            "eyes": a.eyes,
            "skin": a.skin,
            "outfit": a.clothing_primary,
        }


class WorldBibleMeta(BaseModel):
    generated_at: str = ""
    scanned_names: list[str] = Field(default_factory=list)


from pydantic import BaseModel, Field
from typing import Literal


class LocationConnection(BaseModel):
    """Describes how this location connects to another location."""
    target_location_id: str
    connection_type: Literal["adjacent", "connected_by_path", "distant", "contained_within", "overlooks", "underground_link"]
    distance_description: str = ""  # e.g., "5 minutes walk", "half day's journey"
    travel_difficulty: Literal["easy", "moderate", "difficult", "impassable"] = "easy"
    notes: str = ""  # e.g., "mountain pass", "river crossing", "hidden tunnel"


class Location(BaseModel):
    """Structured location with spatial relationships to other locations."""
    id: str
    name: str
    description: str = ""
    recurring: bool = False
    evidence: str = ""
    sd_prompt: str = ""
    angles: list[str] = Field(default_factory=list)
    connections: list[LocationConnection] = Field(default_factory=list)  # Spatial relationships to other locations

    # Rich intake fields (merged from the stage0 dossier 360 views when present).
    season: str = ""
    environment_features: list[str] = Field(default_factory=list)
    views: list[dict] = Field(default_factory=list)  # 360 views [{angle, description}]


class WorldBible(BaseModel):
    """``worldbible/world_bible.json``. M2a populates ``characters`` only --
    the fields below are optional slots M2b (Steps 3-5) fills in: locations,
    power_system, world_rules, lore_entries, and relationships/creative-depth
    data attached per-character in a later pass."""
    
    story_id: str
    characters: list[Character] = Field(default_factory=list)
    world: dict | None = None  # M2b: era/tech/magic/government/daily_life/economy (design 3.2)
    locations: list[Location] = Field(default_factory=list)  # Now uses structured Location model
    recurring_assets: list[dict] = Field(default_factory=list)  # M2b
    relationships: list[dict] = Field(default_factory=list)  # M2b: pairwise edges + evolution
    power_system: dict | None = None
    world_rules: list[str] = Field(default_factory=list)
    lore_entries: list[dict] = Field(default_factory=list)
    meta: WorldBibleMeta = Field(default_factory=WorldBibleMeta)

    # Convenience: get a location by id with its angles (for stage3b plate keying)
    def get_location(self, loc_id: str) -> Location | None:
        for loc in self.locations:
            if loc.id == loc_id:
                return loc
        return None

    def get_location_angles(self, loc_id: str) -> list[str]:
        loc = self.get_location(loc_id)
        if loc:
            return loc.angles or [
                "wide_establishing", "medium_shot", "closeup_counter", "over_shoulder"
            ]
        return ["wide_establishing", "medium_shot", "closeup_counter", "over_shoulder"]

    def get_location_connections(self, loc_id: str) -> list[LocationConnection]:
        """Get all spatial connections for a location."""
        loc = self.get_location(loc_id)
        if loc:
            return loc.connections
        return []
