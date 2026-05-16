import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.audit.models import AuditEvent
from app.privacy.masker import MaskingFinding
from app.privacy.patterns import SecretKind
from dashboard._data import (
    RECENT_EVENT_COLUMNS,
    build_latency_series,
    build_recent_events_dataframe,
    build_risk_score_buckets,
    format_event_label,
    has_latency_data,
    load_events,
    resolve_audit_log_path,
    sort_events_newest_first,
)


def test_resolve_audit_log_path_anchors_relative_paths_to_repo_root() -> None:
    resolved = resolve_audit_log_path(
        "backend/.sentrygate/audit_events.jsonl"
    )

    assert resolved.is_absolute()
    assert resolved.name == "audit_events.jsonl"
    assert "backend" in resolved.parts
    assert ".sentrygate" in resolved.parts


def test_resolve_audit_log_path_returns_absolute_path_unchanged(
    tmp_path: Path,
) -> None:
    absolute = tmp_path / "audit.jsonl"

    assert resolve_audit_log_path(str(absolute)) == absolute


def test_load_events_reports_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "absent.jsonl"

    result = load_events(missing)

    assert result.missing is True
    assert result.empty is True
    assert result.events == []
    assert result.skipped == 0
    assert result.path == missing


def test_load_events_reports_empty_file(tmp_path: Path) -> None:
    empty_path = tmp_path / "empty.jsonl"
    empty_path.write_text("", encoding="utf-8")

    result = load_events(empty_path)

    assert result.missing is False
    assert result.empty is True
    assert result.events == []
    assert result.skipped == 0


def test_load_events_returns_events_and_counts_skipped_lines(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "audit.jsonl"
    valid = _event(tool_name="read_file", decision="allow", risk_score=10)
    log_path.write_text(
        "\n".join(
            [
                "{not-json",
                json.dumps(valid.model_dump(mode="json")),
                json.dumps({"event_id": "invalid-shape"}),
            ]
        ),
        encoding="utf-8",
    )

    result = load_events(log_path)

    assert result.missing is False
    assert result.empty is False
    assert [event.event_id for event in result.events] == [valid.event_id]
    assert result.skipped == 2


def test_build_recent_events_dataframe_sorts_newest_first_and_caps_limit() -> (
    None
):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        _event(
            tool_name=f"tool_{index}",
            decision="allow",
            risk_score=10,
            started_at=base + timedelta(seconds=index),
            reasons=[f"reason_{index}", "shared"],
        )
        for index in range(3)
    ]

    frame = build_recent_events_dataframe(events, limit=2)

    assert list(frame.columns) == list(RECENT_EVENT_COLUMNS)
    assert len(frame) == 2
    assert frame.iloc[0]["tool_name"] == "tool_2"
    assert frame.iloc[1]["tool_name"] == "tool_1"
    assert frame.iloc[0]["reasons"] == "reason_2, shared"
    assert frame.iloc[0]["masked_findings"] == 0


def test_build_recent_events_dataframe_empty_returns_empty_frame() -> None:
    frame = build_recent_events_dataframe([])

    assert list(frame.columns) == list(RECENT_EVENT_COLUMNS)
    assert len(frame) == 0


def test_build_recent_events_dataframe_counts_masked_findings() -> None:
    finding = MaskingFinding(kind=SecretKind.EMAIL, token="[EMAIL_001]")
    event = _event(
        tool_name="read_file",
        decision="allow",
        risk_score=10,
        masked_findings=(finding, finding),
    )

    frame = build_recent_events_dataframe([event])

    assert frame.iloc[0]["masked_findings"] == 2


def test_build_risk_score_buckets_covers_bucket_boundaries() -> None:
    scores = [0, 19, 20, 39, 40, 59, 60, 79, 80, 100]
    events = [
        _event(tool_name="read_file", decision="allow", risk_score=score)
        for score in scores
    ]

    buckets = build_risk_score_buckets(events)

    assert buckets == {
        "0-19": 2,
        "20-39": 2,
        "40-59": 2,
        "60-79": 2,
        "80-100": 2,
    }


def test_build_risk_score_buckets_empty_input_returns_zeroed_buckets() -> (
    None
):
    assert build_risk_score_buckets([]) == {
        "0-19": 0,
        "20-39": 0,
        "40-59": 0,
        "60-79": 0,
        "80-100": 0,
    }


def test_has_latency_data_detects_presence_and_absence() -> None:
    without_latency = _event(
        tool_name="read_file", decision="allow", risk_score=10
    )
    with_latency = _event(
        tool_name="read_file",
        decision="allow",
        risk_score=10,
        latency_ms=4.5,
    )

    assert has_latency_data([without_latency]) is False
    assert has_latency_data([without_latency, with_latency]) is True
    assert has_latency_data([]) is False


def test_build_latency_series_filters_and_sorts_ascending() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        _event(
            tool_name="read_file",
            decision="allow",
            risk_score=10,
            started_at=base + timedelta(seconds=10),
            latency_ms=12.0,
        ),
        _event(
            tool_name="read_file",
            decision="allow",
            risk_score=10,
            started_at=base + timedelta(seconds=1),
            latency_ms=3.0,
        ),
        _event(
            tool_name="read_file",
            decision="allow",
            risk_score=10,
            started_at=base + timedelta(seconds=5),
            latency_ms=None,
        ),
    ]

    series = build_latency_series(events)

    assert list(series["latency_ms"]) == [3.0, 12.0]
    assert series.index.is_monotonic_increasing


def test_build_latency_series_empty_when_no_latency_present() -> None:
    event = _event(tool_name="read_file", decision="allow", risk_score=10)

    series = build_latency_series([event])

    assert len(series) == 0
    assert "latency_ms" in series.columns


def test_sort_events_newest_first_uses_started_at_with_timestamp_fallback() -> (
    None
):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with_started = _event(
        tool_name="read_file",
        decision="allow",
        risk_score=10,
        started_at=base + timedelta(hours=1),
    )
    fallback_to_timestamp = _event(
        tool_name="read_file",
        decision="allow",
        risk_score=10,
        timestamp=base + timedelta(hours=2),
    )

    ordered = sort_events_newest_first(
        [with_started, fallback_to_timestamp]
    )

    assert ordered[0].event_id == fallback_to_timestamp.event_id
    assert ordered[1].event_id == with_started.event_id


def test_format_event_label_includes_index_and_metadata() -> None:
    event = _event(
        tool_name="run_command",
        decision="require_approval",
        risk_score=55,
        span_id="span-abcdef-12345",
        started_at=datetime(2026, 5, 17, 9, 30, tzinfo=UTC),
    )

    label = format_event_label(event, index=2)

    assert label.startswith("#3 ")
    assert "run_command" in label
    assert "require_approval" in label
    assert "span-abc" in label
    assert "2026-05-17T09:30:00+00:00" in label


def _event(
    tool_name: str,
    decision: str,
    risk_score: int,
    reasons: list[str] | None = None,
    executed: bool = True,
    latency_ms: float | None = None,
    masked_findings: tuple[MaskingFinding, ...] = (),
    started_at: datetime | None = None,
    timestamp: datetime | None = None,
    span_id: str | None = None,
) -> AuditEvent:
    kwargs: dict[str, object] = {
        "session_id": "session-1",
        "tool_name": tool_name,
        "decision": decision,
        "risk_score": risk_score,
        "reasons": reasons if reasons is not None else ["safe_file_read"],
        "arguments_summary": "safe summary",
        "output_summary": "safe output summary",
        "masked_findings": masked_findings,
        "executed": executed,
        "latency_ms": latency_ms,
        "started_at": started_at,
        "span_id": span_id,
    }
    if timestamp is not None:
        kwargs["timestamp"] = timestamp
    return AuditEvent(**kwargs)  # type: ignore[arg-type]
