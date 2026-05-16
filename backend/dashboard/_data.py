from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.audit.jsonl_store import JsonlAuditStore
from app.audit.models import AuditEvent

_DEFAULT_LOAD_LIMIT = 100_000

RECENT_EVENT_COLUMNS: tuple[str, ...] = (
    "started_at",
    "trace_id",
    "span_id",
    "session_id",
    "tool_name",
    "decision",
    "risk_score",
    "latency_ms",
    "reasons",
    "masked_findings",
    "executed",
)

RISK_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0-19", 0, 19),
    ("20-39", 20, 39),
    ("40-59", 40, 59),
    ("60-79", 60, 79),
    ("80-100", 80, 100),
)


@dataclass(frozen=True)
class LoadResult:
    events: list[AuditEvent]
    path: Path
    missing: bool
    empty: bool
    skipped: int


def resolve_audit_log_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / path).resolve()


def load_events(path: Path, limit: int = _DEFAULT_LOAD_LIMIT) -> LoadResult:
    if not path.exists():
        return LoadResult(
            events=[], path=path, missing=True, empty=True, skipped=0
        )

    non_empty_lines = 0
    with path.open(encoding="utf-8") as audit_file:
        for line in audit_file:
            if line.strip() != "":
                non_empty_lines += 1

    if non_empty_lines == 0:
        return LoadResult(
            events=[], path=path, missing=False, empty=True, skipped=0
        )

    events = JsonlAuditStore(path).list_events(limit=limit)

    if non_empty_lines > limit:
        # Truncation, not parse failure — don't misreport as skipped.
        skipped = 0
    else:
        skipped = max(0, non_empty_lines - len(events))

    return LoadResult(
        events=events,
        path=path,
        missing=False,
        empty=len(events) == 0,
        skipped=skipped,
    )


def _event_sort_key(event: AuditEvent) -> datetime:
    return event.started_at or event.timestamp


def sort_events_newest_first(events: list[AuditEvent]) -> list[AuditEvent]:
    return sorted(events, key=_event_sort_key, reverse=True)


def build_recent_events_dataframe(
    events: list[AuditEvent], limit: int = 100
) -> pd.DataFrame:
    sorted_events = sort_events_newest_first(events)[:limit]
    rows = [
        {
            "started_at": event.started_at or event.timestamp,
            "trace_id": event.trace_id or "",
            "span_id": event.span_id or "",
            "session_id": event.session_id or "",
            "tool_name": event.tool_name,
            "decision": event.decision,
            "risk_score": event.risk_score,
            "latency_ms": event.latency_ms,
            "reasons": ", ".join(event.reasons),
            "masked_findings": len(event.masked_findings),
            "executed": event.executed,
        }
        for event in sorted_events
    ]
    if not rows:
        return pd.DataFrame(columns=list(RECENT_EVENT_COLUMNS))
    return pd.DataFrame(rows, columns=list(RECENT_EVENT_COLUMNS))


def build_risk_score_buckets(events: list[AuditEvent]) -> dict[str, int]:
    buckets = {label: 0 for label, _, _ in RISK_BUCKETS}
    for event in events:
        for label, low, high in RISK_BUCKETS:
            if low <= event.risk_score <= high:
                buckets[label] += 1
                break
    return buckets


def has_latency_data(events: list[AuditEvent]) -> bool:
    return any(event.latency_ms is not None for event in events)


def build_latency_series(events: list[AuditEvent]) -> pd.DataFrame:
    rows = [
        {
            "started_at": event.started_at or event.timestamp,
            "latency_ms": event.latency_ms,
        }
        for event in events
        if event.latency_ms is not None
    ]
    if not rows:
        return pd.DataFrame(columns=["latency_ms"])
    frame = pd.DataFrame(rows)
    frame = frame.sort_values("started_at")
    frame = frame.set_index("started_at")
    return frame


def format_event_label(event: AuditEvent, index: int) -> str:
    when = event.started_at or event.timestamp
    short_id = (event.span_id or event.event_id)[:8]
    return (
        f"#{index + 1} {when.isoformat(timespec='seconds')} | "
        f"{event.tool_name} | {event.decision} | {short_id}"
    )
