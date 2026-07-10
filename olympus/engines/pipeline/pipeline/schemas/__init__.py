"""Pydantic data contracts (design section 3), serialized as JSON.

M0 exports :class:`Blueprint`. M1 adds the Stage 0B (GENERATE) contracts.
The world-bible, screenplay, storyboard and timeline schemas (3.2-3.5) arrive
in later milestones.
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
]
