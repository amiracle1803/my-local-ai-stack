import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


def _new_id() -> str:
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=_new_id)
    conversation_id: Optional[str] = None
    room_id: Optional[str] = None
    from_agent: str
    to_agent: str
    role: Literal["request", "response", "event"] = "request"
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    job_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
