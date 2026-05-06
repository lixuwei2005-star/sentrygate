from typing import Literal, TypeAlias

from pydantic import BaseModel, Field

RiskDecision: TypeAlias = Literal["allow", "block", "require_approval"]


class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, object]
    session_id: str | None = None


class RiskResult(BaseModel):
    risk_score: int = Field(ge=0, le=100)
    decision: RiskDecision
    reasons: list[str]
