from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

JobStatus = Literal["queued", "running", "paused", "done", "failed", "stopped"]


class Job(BaseModel):
    id: str
    type: str
    title: Optional[str] = None
    status: JobStatus
    progress: float = 0.0
    error: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Any] = None


class JobCreateRequest(BaseModel):
    type: str
    title: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class JobUpdateRequest(BaseModel):
    title: Optional[str] = None
    type: Optional[str] = None


class RunRequest(BaseModel):
    goal: str
    run_mode: Literal["sync", "background"] = "background"
    risk_level: Optional[str] = None
    review_policy: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    system: Optional[str] = None
    model: Optional[str] = None  # override orchestrator's model_preference for this call only
