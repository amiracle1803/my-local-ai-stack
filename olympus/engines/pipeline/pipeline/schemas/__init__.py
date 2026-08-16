"""Pydantic data contracts (design section 3), serialized as JSON.

M0 exports :class:`Blueprint`. M1 adds the Stage 0B (GENERATE) contracts.
The world-bible, screenplay, storyboard and timeline schemas (3.2-3.5) are
re-exported here so every consumer imports from the ``schemas`` namespace
instead of reaching into per-stage modules.
"""

from __future__ import annotations

from ..blueprint import Blueprint
from .stage0 import (
    BlueprintCharacter,
    BlueprintScene,
    IntegrationReport,
    SceneChecks,
    ScenePlan,
    SceneProse,
    StoryBlueprint,
    ThematicCore,
    ThreeActStructure,
)
from .worldbible import (
    Appearance,
    ArcThisEpisode,
    Character,
    Personality,
    Provenance,
    SpeechStyle,
    WorldBible,
    WorldBibleMeta,
)

__all__ = [
    "Blueprint",
    "StoryBlueprint",
    "BlueprintCharacter",
    "BlueprintScene",
    "ThreeActStructure",
    "ThematicCore",
    "ScenePlan",
    "SceneChecks",
    "SceneProse",
    "IntegrationReport",
    "WorldBible",
    "WorldBibleMeta",
    "Character",
    "Appearance",
    "SpeechStyle",
    "Personality",
    "ArcThisEpisode",
    "Provenance",
]
