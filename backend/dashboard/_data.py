from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.audit.jsonl_store import JsonlAuditStore
from app.audit.models import AuditEvent

_DEFAULT_LOAD_LIMIT = 100_000
REJECTED_AUDIT_LOG_PATH_MESSAGE = (
    "Rejected path: dashboard only reads SentryGate JSONL audit logs."
)

RECENT_EVENT_COLUMNS: tuple[str, ...] = (
    "timestamp",
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
    rejected: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class PathValidationResult:
    accepted: bool
    warning: str | None = None


def resolve_audit_log_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / path).resolve()


def validate_audit_log_path(path: Path) -> PathValidationResult:
    if path.suffix.lower() != ".jsonl":
        return PathValidationResult(
            accepted=False,
            warning=REJECTED_AUDIT_LOG_PATH_MESSAGE,
        )

    try:
        if path.exists() and path.is_dir():
            return PathValidationResult(
                accepted=False,
                warning=REJECTED_AUDIT_LOG_PATH_MESSAGE,
            )
    except OSError:
        return PathValidationResult(
            accepted=False,
            warning=REJECTED_AUDIT_LOG_PATH_MESSAGE,
        )

    if not any(part.lower() == ".sentrygate" for part in path.parts):
        return PathValidationResult(
            accepted=False,
            warning=REJECTED_AUDIT_LOG_PATH_MESSAGE,
        )

    return PathValidationResult(accepted=True)


def load_events(path: Path, limit: int = _DEFAULT_LOAD_LIMIT) -> LoadResult:
    validation = validate_audit_log_path(path)
    if not validation.accepted:
        return LoadResult(
            events=[],
            path=path,
            missing=False,
            empty=True,
            skipped=0,
            rejected=True,
            warning=validation.warning,
        )

    if not path.exists():
        return LoadResult(
            events=[],
            path=path,
            missing=True,
            empty=True,
            skipped=0,
            warning=validation.warning,
        )

    valid_events: list[AuditEvent] = []
    skipped = 0
    with path.open(encoding="utf-8") as audit_file:
        for line in audit_file:
            if line.strip() == "":
                continue
            event = JsonlAuditStore._event_from_line(line)
            if event is None:
                skipped += 1
                continue
            valid_events.append(event)

    events = valid_events[-limit:] if limit > 0 else []

    return LoadResult(
        events=events,
        path=path,
        missing=False,
        empty=len(events) == 0,
        skipped=skipped,
        warning=validation.warning,
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
            "timestamp": event.started_at or event.timestamp,
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
