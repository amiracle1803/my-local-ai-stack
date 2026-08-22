"""Stage 0 (INTAKE) data contracts (design 3.9 / original spec STAGE 0).

Three modes, all producing ``input/script.txt`` (and for 0I, a screenplay):

- **0B GENERATE** (``stage0_intake``) -- original-from-brief. ``StoryBlueprint``
  is the *exact* Pass 1 output schema from
  ``aether-studio-original-spec-stages0-2.md``; the rest support Pass 2/3
  bookkeeping (word targets, per-scene automated checks, integration report).
- **0A TRANSFORM** (``stage0a_transform``) -- source->original 4-pass with a
  legal-proximity gate. ``MechanicsExtraction`` + ``TransformationMap`` are
  the Pass 1/2 schemas; ``LegalScore`` is the computed proximity gate.
- **0I IMPORT** (``stage0i_import``) -- existing panels->story 4-pass with a
  vision pass. ``PanelInventoryItem`` / ``PanelAnalysis`` / ``IdentityCluster``
  / ``ImportedShot`` support Pass 1/2/3/4.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal

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


# --------------------------------------------------------------------------
# Stage 0A -- TRANSFORM (source -> original)
# --------------------------------------------------------------------------


class MechanicsExtraction(BaseModel):
    """Stage 0A Pass 1 -- structural mechanics only, never plot or characters."""

    power_system_type: str = ""
    power_mechanics: list[str] = Field(default_factory=list)
    progression_model: str = ""
    conflict_engine: Literal[
        "zero-sum-competition", "betrayal-from-within", "external-invasion",
        "internal-corruption", "knowledge-vs-power", "identity-dissolution",
        "",
    ] = ""
    conflict_specifics: str = ""
    protagonist_archetype: Literal[
        "reluctant-hero", "amoral-genius", "underdog-overcomer", "broken-redeemer",
        "outsider-observer", "chosen-by-circumstance", "",
    ] = ""
    protagonist_behavioral_pattern: str = ""
    emotional_hooks: list[str] = Field(default_factory=list)
    world_rules: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    what_makes_it_original: str = ""


class WorldDesign(BaseModel):
    name: str = ""
    geography: str = ""
    cultural_flavor: str = ""
    visual_signature: str = ""
    what_is_scarce: str = ""


class PowerSystemOriginal(BaseModel):
    name: str = ""
    source_mechanic_used: str = ""
    new_skin: str = ""
    new_rules: list[str] = Field(default_factory=list)
    visual_manifestation: str = ""


class CharacterOriginal(BaseModel):
    source_archetype: str = ""
    new_name: str = ""
    new_personality: str = ""
    new_history: str = ""
    new_relationship_network: str = ""


class ConflictRedesign(BaseModel):
    source_engine_used: str = ""
    new_factions: list[str] = Field(default_factory=list)
    new_stakes: str = ""
    new_inciting_event: str = ""


class CommentaryLayer(BaseModel):
    angle: str = ""
    how_it_manifests: str = ""


class TransformationMap(BaseModel):
    """Stage 0A Pass 2 -- original equivalents for every source mechanic."""

    world_design: WorldDesign = Field(default_factory=WorldDesign)
    power_system_original: PowerSystemOriginal = Field(default_factory=PowerSystemOriginal)
    character_originals: list[CharacterOriginal] = Field(default_factory=list)
    conflict_redesign: ConflictRedesign = Field(default_factory=ConflictRedesign)
    original_commentary_layer: CommentaryLayer = Field(default_factory=CommentaryLayer)


class LegalScore(BaseModel):
    """Stage 0A Pass 2 post-check -- proximity of the transformation to the
    source. Starts at 100 and deducts per overlapping element. Below 75 is a
    warning (user may proceed); below 50 blocks Pass 3 without modification."""

    total: float = 100.0
    warnings: list[str] = Field(default_factory=list)
    blocked: bool = False

    def recompute(self, mech: MechanicsExtraction, tmap: TransformationMap) -> None:
        score = 100.0
        warnings: list[str] = []

        archetypes = {c.source_archetype for c in tmap.character_originals if c.source_archetype}
        for a in sorted(archetypes):
            if a and a.lower() not in tmap.world_design.name.lower():
                # a character kept the source archetype name with no differentiator
                pass
        # Spec: -10 per archetype that maps 1-to-1 with no differentiation. A
        # source_archetype that is reused verbatim and whose new personality is
        # empty or identical to the mechanic's pattern counts as un-differentiated.
        for c in tmap.character_originals:
            if c.source_archetype and c.source_archetype.lower() == mech.protagonist_archetype.lower():
                if not c.new_personality or c.new_personality.lower() in (
                    mech.protagonist_behavioral_pattern.lower(), c.source_archetype.lower(),
                ):
                    score -= 10
                    warnings.append(
                        f"archetype '{c.source_archetype}' reused with no differentiation"
                    )

        # Conflict engine match: -20 if identical with no new factions/stakes.
        if tmap.conflict_redesign.source_engine_used.lower() == mech.conflict_engine.lower():
            if not tmap.conflict_redesign.new_factions and not tmap.conflict_redesign.new_stakes:
                score -= 20
                warnings.append("conflict engine identical with no new factions/stakes")

        # Power mechanic match: -15 per mechanic copied without modification.
        new_rules_text = " ".join(tmap.power_system_original.new_rules).lower()
        for m in mech.power_mechanics:
            if m and m.lower() in new_rules_text:
                score -= 15
                warnings.append(f"power mechanic '{m}' copied without modification")

        # World rule match: -10 per rule that is identical.
        for r in mech.world_rules:
            if r and r.lower() in tmap.world_design.geography.lower():
                score -= 10
                warnings.append(f"world rule '{r}' identical")

        self.total = round(max(0.0, score), 1)
        self.warnings = warnings
        self.blocked = self.total < 50.0


# --------------------------------------------------------------------------
# Stage 0I -- IMPORT (existing panels -> story)
# --------------------------------------------------------------------------


class PanelInventoryItem(BaseModel):
    """Stage 0I Pass 1 -- pure filesystem record (no LLM)."""

    path: str = ""
    size_bytes: int = 0
    flagged_blank: bool = False
    classification: Literal["panel", "full_page_splash", "cover", "unknown"] = "panel"
    order: int = 0


class PanelAnalysis(BaseModel):
    """Stage 0I Pass 2 -- per-panel vision output."""

    panel_id: str = ""
    characters: list[dict] = Field(default_factory=list)  # {hair,eyes,skin,build,clothing,position,expression}
    action: str = ""  # start state -> end state
    dialogue: list[dict] = Field(default_factory=list)  # {speaker, text, bubble_type}
    mood: str = ""
    setting: dict = Field(default_factory=dict)  # {interior_exterior, description, time_of_day}
    shot_type: str = "medium"
    panel_notes: str = ""
    tier: Literal["full", "partial", "minimal"] = "full"
    needs_manual_review: bool = False


class IdentityCluster(BaseModel):
    """Stage 0I Pass 3 -- resolved unique individual."""

    provisional_id: str = ""
    canonical_appearance: str = ""
    appears_in_panels: list[str] = Field(default_factory=list)
    speaks_in_panels: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    uncertainty_notes: str = ""


class ImportedShot(BaseModel):
    """Stage 0I Pass 4 -- one shot synthesized per panel."""

    shot_id: str = ""
    scene_id: str = ""
    shot_type: str = "medium"
    description: str = ""
    narration: str = ""
    dialogue: list[dict] = Field(default_factory=list)  # {character_id, text}
    sd_prompt: str = ""
    source_panel: str = ""
