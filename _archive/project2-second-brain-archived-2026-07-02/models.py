"""
models.py  --  The shape of the "structured memory" the agent extracts.

These Pydantic classes are the schema Instructor validates against. Because the
model is forced to return data matching these classes, you get clean, typed
objects instead of free text you'd have to parse.

Keep these small and obvious. Add fields only when you'll actually use them.
"""

from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Task(BaseModel):
    text: str = Field(..., description="The action to do, phrased as a task.")
    status: Literal["open", "done"] = "open"
    due: Optional[str] = Field(None, description="Due date if stated, else null.")


class Decision(BaseModel):
    text: str = Field(..., description="A decision the person made.")
    reason: Optional[str] = Field(None, description="Why, if stated.")


class Insight(BaseModel):
    text: str = Field(..., description="A realization, pattern, or lesson learned.")


class NoteExtraction(BaseModel):
    """Everything pulled from a single note."""
    tasks: list[Task] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
