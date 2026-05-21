from datetime import UTC, datetime
from typing import Literal, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, Field

ApprovalStatus: TypeAlias = Literal[
    "pending",
    "approved",
    "rejected",
    "expired",
    "executed",
]


class ApprovalRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str | None = None
    tool_name: str
    arguments_summary: str
    original_arguments: dict[str, object]
    risk_score: int = Field(ge=0, le=100)
    reasons: list[str]
    status: ApprovalStatus = "pending"
    expires_at: datetime | None = None
