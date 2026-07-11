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


class WorldBibleMeta(BaseModel):
    generated_at: str = ""
    scanned_names: list[str] = Field(default_factory=list)


class WorldBible(BaseModel):
    """``worldbible/world_bible.json``. M2a populates ``characters`` only --
    the fields below are optional slots M2b (Steps 3-5) fills in: locations,
    power_system, world_rules, lore_entries, and relationships/creative-depth
    data attached per-character in a later pass."""

    story_id: str
    characters: list[Character] = Field(default_factory=list)
    world: dict | None = None  # M2b: era/tech/magic/government/daily_life/economy (design 3.2)
    locations: list[dict] = Field(default_factory=list)
    recurring_assets: list[dict] = Field(default_factory=list)  # M2b
    relationships: list[dict] = Field(default_factory=list)  # M2b: pairwise edges + evolution
    power_system: dict | None = None
    world_rules: list[str] = Field(default_factory=list)
    lore_entries: list[dict] = Field(default_factory=list)
    meta: WorldBibleMeta = Field(default_factory=WorldBibleMeta)
