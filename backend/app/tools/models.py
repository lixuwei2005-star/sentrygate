from pydantic import BaseModel, Field

from app.privacy.masker import MaskingFinding
from app.risk.models import RiskDecision


class ToolExecutionResult(BaseModel):
    ok: bool
    decision: RiskDecision
    risk_score: int = Field(ge=0, le=100)
    reasons: list[str]
    output: str | None = None
    error: str | None = None
    masked_findings: tuple[MaskingFinding, ...] = ()
    approval_request_id: str | None = None
