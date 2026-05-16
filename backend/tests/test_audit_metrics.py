from app.audit.metrics import summarize_audit_events
from app.audit.models import AuditEvent
from app.privacy.masker import MaskingFinding
from app.privacy.patterns import SecretKind


def test_summarize_audit_events_counts_core_metrics() -> None:
    summary = summarize_audit_events(
        [
            _event(
                tool_name="read_file",
                decision="allow",
                risk_score=10,
                reasons=["safe_file_read"],
                executed=True,
                latency_ms=4.0,
                masked_findings=(_finding("[EMAIL_001]"),),
            ),
            _event(
                tool_name="run_command",
                decision="require_approval",
                risk_score=50,
                reasons=["run_command_requires_approval", "common_reason"],
                executed=False,
                latency_ms=None,
            ),
            _event(
                tool_name="read_file",
                decision="block",
                risk_score=100,
                reasons=["sensitive_path", "common_reason"],
                executed=False,
                latency_ms=6.0,
                masked_findings=(
                    _finding("[EMAIL_002]"),
                    _finding("[EMAIL_003]"),
                ),
            ),
        ],
        top_risk_reason_limit=2,
    )

    assert summary.total_calls == 3
    assert summary.allowed_calls == 1
    assert summary.blocked_calls == 1
    assert summary.require_approval_calls == 1
    assert summary.executed_calls == 1
    assert summary.average_latency_ms == 5.0
    assert summary.high_risk_events == 1
    assert summary.masked_finding_count == 3
    assert summary.tool_call_counts == {"read_file": 2, "run_command": 1}
    assert summary.decision_counts == {
        "allow": 1,
        "block": 1,
        "require_approval": 1,
    }
    assert [
        reason_count.model_dump()
        for reason_count in summary.top_risk_reasons
    ] == [
        {"reason": "common_reason", "count": 2},
        {"reason": "run_command_requires_approval", "count": 1},
    ]


def test_summarize_audit_events_empty_input_uses_stable_defaults() -> None:
    summary = summarize_audit_events([])

    assert summary.total_calls == 0
    assert summary.allowed_calls == 0
    assert summary.blocked_calls == 0
    assert summary.require_approval_calls == 0
    assert summary.executed_calls == 0
    assert summary.average_latency_ms == 0.0
    assert summary.high_risk_events == 0
    assert summary.masked_finding_count == 0
    assert summary.tool_call_counts == {}
    assert summary.decision_counts == {
        "allow": 0,
        "block": 0,
        "require_approval": 0,
    }
    assert summary.top_risk_reasons == []


def _event(
    tool_name: str,
    decision: str,
    risk_score: int,
    reasons: list[str],
    executed: bool,
    latency_ms: float | None = None,
    masked_findings: tuple[MaskingFinding, ...] = (),
) -> AuditEvent:
    return AuditEvent(
        session_id="session-1",
        tool_name=tool_name,
        decision=decision,
        risk_score=risk_score,
        reasons=reasons,
        arguments_summary="safe summary",
        output_summary="safe output summary",
        masked_findings=masked_findings,
        executed=executed,
        latency_ms=latency_ms,
    )


def _finding(token: str) -> MaskingFinding:
    return MaskingFinding(kind=SecretKind.EMAIL, token=token)
