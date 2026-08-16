"""Pydantic models mirroring harness/schemas/*.json (00-overview.md §7, handoff.md §3/§5/§7)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- enums ---------------------------------------------------------------

class TaskState(str, Enum):
    INTAKE = "INTAKE"
    PLANNING = "PLANNING"
    EXECUTION = "EXECUTION"
    VERIFICATION = "VERIFICATION"
    DELIVERY = "DELIVERY"
    FAILED = "FAILED"


class SideEffect(str, Enum):
    READ = "read"
    WRITE_SCOPED = "write-scoped"
    WRITE_SHARED = "write-shared"
    EXTERNAL = "external"
    IRREVERSIBLE = "irreversible"


Tier = Literal["T0", "T1", "T2", "T3", "F"]
Domain = Literal["coding", "research", "writing", "analysis", "media", "ops", "workflow", "memory"]
Difficulty = Literal["trivial", "easy", "standard", "hard", "frontier"]
Risk = Literal["low", "medium", "high"]
MemoryType = Literal["episodic", "semantic", "procedural", "error"]


# --- task record ---------------------------------------------------------

class Classification(_Strict):
    domain: Domain
    difficulty: Difficulty
    risk: Risk
    offline_ok: bool
    structure: Optional[Literal["freeform", "schema"]] = None
    context_need: Optional[Literal["small", "medium", "large"]] = None


class Route(_Strict):
    tier: Tier
    model: str
    fallbacks: list[str] = Field(default_factory=list)


class Budget(_Strict):
    max_loops: int = Field(ge=1)
    max_tokens: int = Field(ge=1)
    max_wall_minutes: int = Field(ge=1)


class Verification(_Strict):
    required_score: float = Field(ge=0, le=1)
    verifier: str
    status: Literal["pending", "pass", "fail"] = "pending"


class Task(_Strict):
    id: str
    goal: str = Field(min_length=1)
    state: TaskState
    class_: Classification = Field(alias="class")
    route: Route
    budget: Budget
    plan_ref: Optional[str] = None
    verification: Verification
    replans: int = Field(default=0, ge=0)
    parent: Optional[str] = None
    children: list[str] = Field(default_factory=list)
    created: datetime
    updated: Optional[datetime] = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def to_json_dict(self) -> dict:
        # exclude_none: optional fields (structure/context_need/plan_ref/...) are omitted
        # when absent rather than emitted as null, matching the JSON Schemas.
        return self.model_dump(by_alias=True, mode="json", exclude_none=True)


# --- handoff payload -----------------------------------------------------

class ArtifactRef(_Strict):
    path: str
    sha256: str
    why: Optional[str] = None


class HandoffInputs(_Strict):
    plan_ref: Optional[str] = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    evidence_bundle: Optional[str] = None
    error_memory: list[str] = Field(default_factory=list)


class HandoffConstraints(_Strict):
    side_effects: list[SideEffect]
    offline_ok: bool
    language: Optional[str] = None


class HandoffBudget(_Strict):
    max_tokens: int = Field(ge=1)
    max_wall_minutes: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)


class HandoffRoute(_Strict):
    tier: Tier
    model: str


class Handoff(_Strict):
    handoff_id: str
    task_id: str
    step: int = Field(ge=0)
    state: TaskState
    from_: str = Field(alias="from")
    to: str
    objective: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    inputs: HandoffInputs
    constraints: HandoffConstraints
    budget: HandoffBudget
    route: HandoffRoute
    return_schema: str

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def to_json_dict(self) -> dict:
        return self.model_dump(by_alias=True, mode="json", exclude_none=True)


# --- report --------------------------------------------------------------

class ReportArtifact(_Strict):
    path: str
    sha256: str
    kind: str


class ReportEvidence(_Strict):
    claim: str
    ref: str
    kind: str


class AcceptanceSelfCheck(_Strict):
    criterion: int = Field(ge=0)
    met: bool
    evidence_idx: Optional[int] = Field(default=None, ge=0)


class SuggestedMemory(_Strict):
    type: MemoryType
    note: str


class Usage(_Strict):
    tokens: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    wall_seconds: float = Field(ge=0)


class Report(_Strict):
    handoff_id: str
    status: Literal["done", "partial", "blocked", "failed"]
    summary: str = Field(min_length=1)
    artifacts: list[ReportArtifact] = Field(default_factory=list)
    evidence: list[ReportEvidence] = Field(default_factory=list)
    acceptance_self_check: list[AcceptanceSelfCheck] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    concerns: list[str] = Field(default_factory=list)
    suggested_memory: list[SuggestedMemory] = Field(default_factory=list)
    usage: Usage


# --- scorecard -----------------------------------------------------------

class ScoreGate(_Strict):
    threshold: float = Field(ge=0, le=1)
    passed: bool


class Scorecard(_Strict):
    handoff_id: str
    loop: int = Field(ge=0)
    rubric: str
    scores: dict[str, float]
    weighted_total: float = Field(ge=0, le=1)
    gate: ScoreGate


# --- verdict -------------------------------------------------------------

class VerdictCheck(_Strict):
    name: str
    kind: Literal["test", "schema", "lint", "probe", "model-judgment"]
    passed: bool
    detail: Optional[str] = None


class Verdict(_Strict):
    handoff_id: str
    verifier: str
    passed: bool
    checks: list[VerdictCheck] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    created: datetime
