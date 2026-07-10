"""Stage 0B (GENERATE) data contracts (design 3.9 / original spec STAGE 0 ->
Stage 0B). ``StoryBlueprint`` is the *exact* Pass 1 output schema from
``aether-studio-original-spec-stages0-2.md``; the rest support Pass 2/3
bookkeeping (word targets, per-scene automated checks, integration report).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Pass 1 -- Story Blueprint (original spec, verbatim field set)
# --------------------------------------------------------------------------


class BlueprintCharacter(BaseModel):
    name: str
    role: str  # protagonist/antagonist/mentor/ally/obstacle/neutral
    personality_core: str
    episode_want: str
    episode_fear: str
    episode_arc_end: str
    new_or_recurring: str = "new"  # new | recurring
    if_recurring_existing_id: str | None = None


class Act1(BaseModel):
    scenes: list[str]
    inciting_incident: str
    establishes: str


class Act2(BaseModel):
    scenes: list[str]
    escalation: str
    midpoint_reversal: str
    what_breaks: str


class Act3(BaseModel):
    scenes: list[str]
    climax_decision: str
    cost: str
    permanent_change: str


class ThreeActStructure(BaseModel):
    act1: Act1
    act2: Act2
    act3: Act3


class BlueprintScene(BaseModel):
    number: int
    title: str
    act: int
    location: str
    characters_present: list[str] = Field(default_factory=list)
    emotional_purpose: str
    narrative_function: str


class ThematicCore(BaseModel):
    surface: str
    deeper: str
    moral_question: str


class StoryBlueprint(BaseModel):
    """Stage 0B Pass 1 output. Commits the structure before any prose exists."""

    title: str
    logline: str
    characters: list[BlueprintCharacter] = Field(default_factory=list)
    three_act_structure: ThreeActStructure
    scene_list: list[BlueprintScene] = Field(default_factory=list)
    thematic_core: ThematicCore


# --------------------------------------------------------------------------
# Pass 2 -- per-scene prose bookkeeping
# --------------------------------------------------------------------------


class SceneChecks(BaseModel):
    """Automated (no-LLM) per-scene quality checks (original spec Pass 2)."""

    opens_on_action_or_dialogue: bool
    has_dialogue: bool
    ends_differently: bool
    flags: list[str] = Field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return self.opens_on_action_or_dialogue and self.has_dialogue and self.ends_differently


class ScenePlan(BaseModel):
    """A blueprint scene resolved with its Pass 2 word target."""

    number: int
    title: str
    act: int
    location: str
    characters_present: list[str]
    emotional_purpose: str
    narrative_function: str
    word_target: int
    scene_role: str = "standard"  # climax | transitional | standard


class SceneProse(BaseModel):
    """Final per-scene prose record after draft -> critique -> revise and
    word-count enforcement."""

    number: int
    title: str
    text: str
    word_count: int
    word_target: int
    checks: SceneChecks
    enforcement_applied: str | None = None  # "condensed" | "expanded" | None


# --------------------------------------------------------------------------
# Pass 3 -- integration (no LLM)
# --------------------------------------------------------------------------


class IntegrationReport(BaseModel):
    """Automated Pass 3 validations (original spec)."""

    total_word_count: int
    target_word_count: int
    word_count_pct: float  # total / target, as a fraction (1.0 == on target)
    missing_character_names: list[str] = Field(default_factory=list)
    missing_location_names: list[str] = Field(default_factory=list)
    oversized_scenes: list[int] = Field(default_factory=list)  # scene numbers > 30% of total

    @property
    def all_names_found(self) -> bool:
        return not self.missing_character_names and not self.missing_location_names

    @property
    def no_oversized_scenes(self) -> bool:
        return not self.oversized_scenes
