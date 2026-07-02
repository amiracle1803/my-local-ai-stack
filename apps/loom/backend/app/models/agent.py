from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

AgentLayer = Literal["control", "knowledge", "action", "platform"]


class AgentDefinition(BaseModel):
    id: str
    display_name: str
    layer: AgentLayer
    description: str
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    model_preference: List[str] = Field(default_factory=list)
    memory_scopes: List[str] = Field(default_factory=list)
    policies: List[str] = Field(default_factory=list)
    system_prompt: Optional[str] = None


class AgentCreateRequest(BaseModel):
    id: str
    display_name: str
    layer: AgentLayer
    description: str
    tools: List[str] = Field(default_factory=list)
    model_preference: List[str] = Field(default_factory=list)
    memory_scopes: List[str] = Field(default_factory=list)
    policies: List[str] = Field(default_factory=list)
    system_prompt: Optional[str] = None

    @field_validator("id")
    @classmethod
    def normalize_id(cls, v: str) -> str:
        v = v.strip().lower().replace(" ", "_").replace("-", "_")
        if not v or not all(c.isalnum() or c == "_" for c in v):
            raise ValueError("id must be a non-empty slug of letters/digits/underscores")
        return v
