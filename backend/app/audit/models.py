from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.privacy.masker import MaskingFinding
from app.risk.models import RiskDecision


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str | None
    tool_name: str
    decision: RiskDecision
    risk_score: int = Field(ge=0, le=100)
    reasons: list[str]
    arguments_summary: str
    output_summary: str | None
    masked_findings: tuple[MaskingFinding, ...] = ()
    executed: bool


AuditDecision = Literal["allow", "block", "require_approval"]
