from collections import Counter
from collections.abc import Iterable

from pydantic import BaseModel

from app.audit.models import AuditEvent
from app.risk.policy import REQUIRE_APPROVAL_MAX_SCORE


class RiskReasonCount(BaseModel):
    reason: str
    count: int


class AuditMetricsSummary(BaseModel):
    total_calls: int
    allowed_calls: int
    blocked_calls: int
    require_approval_calls: int
    executed_calls: int
    average_latency_ms: float
    high_risk_events: int
    masked_finding_count: int
    tool_call_counts: dict[str, int]
    decision_counts: dict[str, int]
    top_risk_reasons: list[RiskReasonCount]


def summarize_audit_events(
    events: Iterable[AuditEvent],
    top_risk_reason_limit: int = 5,
) -> AuditMetricsSummary:
    event_list = list(events)
    decision_counts = Counter(event.decision for event in event_list)
    tool_call_counts = Counter(event.tool_name for event in event_list)
    reason_counts = Counter(
        reason for event in event_list for reason in event.reasons
    )
    latencies = [
        event.latency_ms
        for event in event_list
        if event.latency_ms is not None
    ]

    stable_decision_counts = {
        "allow": decision_counts["allow"],
        "block": decision_counts["block"],
        "require_approval": decision_counts["require_approval"],
    }

    return AuditMetricsSummary(
        total_calls=len(event_list),
        allowed_calls=stable_decision_counts["allow"],
        blocked_calls=stable_decision_counts["block"],
        require_approval_calls=stable_decision_counts["require_approval"],
        executed_calls=sum(1 for event in event_list if event.executed),
        average_latency_ms=(
            sum(latencies) / len(latencies) if latencies else 0.0
        ),
        # high_risk_events counts events with risk_score > REQUIRE_APPROVAL_MAX_SCORE,
        # i.e. block-tier events (75-100) in the 0-39 allow / 40-74 require_approval /
        # 75-100 block model.
        high_risk_events=sum(
            1
            for event in event_list
            if event.risk_score > REQUIRE_APPROVAL_MAX_SCORE
        ),
        masked_finding_count=sum(
            len(event.masked_findings) for event in event_list
        ),
        tool_call_counts=dict(sorted(tool_call_counts.items())),
        decision_counts=stable_decision_counts,
        top_risk_reasons=[
            RiskReasonCount(reason=reason, count=count)
            for reason, count in sorted(
                reason_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:top_risk_reason_limit]
        ],
    )
