import json
from pathlib import Path

from app.audit.jsonl_store import JsonlAuditStore
from app.audit.models import AuditEvent
from app.privacy.masker import MaskingFinding
from app.tools.safe_tools import SafeToolService


def test_jsonl_audit_store_appends_and_lists_events(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "audit.jsonl"
    store = JsonlAuditStore(log_path)
    first = _event(session_id="session-1", tool_name="read_file")
    second = _event(session_id="session-2", tool_name="run_command")

    store.append(first)
    store.append(second)

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [event.event_id for event in store.list_events()] == [
        first.event_id,
        second.event_id,
    ]


def test_jsonl_audit_store_filters_by_session_and_limit(
    tmp_path: Path,
) -> None:
    store = JsonlAuditStore(tmp_path / "audit.jsonl")
    first = _event(session_id="a", tool_name="read_file")
    second = _event(session_id="b", tool_name="write_file")
    third = _event(session_id="a", tool_name="run_command")

    for event in (first, second, third):
        store.append(event)

    assert [event.event_id for event in store.list_events(session_id="a")] == [
        first.event_id,
        third.event_id,
    ]
    assert [event.event_id for event in store.list_events(limit=2)] == [
        second.event_id,
        third.event_id,
    ]
    assert store.list_events(limit=0) == []


def test_jsonl_audit_store_missing_file_returns_empty_list(
    tmp_path: Path,
) -> None:
    store = JsonlAuditStore(tmp_path / "missing.jsonl")

    assert store.list_events() == []


def test_jsonl_audit_store_skips_malformed_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    valid = _event(session_id="session-1", tool_name="read_file")
    log_path.write_text(
        "\n".join(
            [
                "{not-json",
                json.dumps(valid.model_dump(mode="json")),
                json.dumps({"event_id": "invalid-event"}),
            ]
        ),
        encoding="utf-8",
    )

    store = JsonlAuditStore(log_path)

    assert [event.event_id for event in store.list_events()] == [valid.event_id]


def test_jsonl_audit_store_does_not_persist_raw_secrets(
    tmp_path: Path,
) -> None:
    raw_secret = "sk-test123"
    log_path = tmp_path / "audit.jsonl"
    store = JsonlAuditStore(log_path)
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)

    result = service.sentry_run_command(f"echo {raw_secret}")

    assert result.decision == "require_approval"
    serialized = log_path.read_text(encoding="utf-8")
    assert raw_secret not in serialized
    assert "[API_KEY_001]" in serialized


def test_audit_event_trace_span_fields_are_optional() -> None:
    event = _event(session_id=None, tool_name="read_file")

    assert event.trace_id is None
    assert event.span_id is None
    assert event.parent_span_id is None
    assert event.started_at is None
    assert event.ended_at is None
    assert event.latency_ms is None


def _event(
    session_id: str | None,
    tool_name: str,
    masked_findings: tuple[MaskingFinding, ...] = (),
) -> AuditEvent:
    return AuditEvent(
        session_id=session_id,
        tool_name=tool_name,
        decision="allow",
        risk_score=10,
        reasons=["safe_file_read"],
        arguments_summary="path=README.md",
        output_summary="read_file succeeded; chars=5; masked_findings=0",
        masked_findings=masked_findings,
        executed=True,
    )
