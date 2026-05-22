from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd

from app.audit.jsonl_store import JsonlAuditStore
from app.audit.models import AuditEvent

_DEFAULT_LOAD_LIMIT = 100_000
DEFAULT_APPROVAL_API_BASE_URL = "http://127.0.0.1:8766"
APPROVAL_API_TIMEOUT_SECONDS = 3.0
REJECTED_AUDIT_LOG_PATH_MESSAGE = (
    "Rejected path: dashboard only reads SentryGate JSONL audit logs."
)
REJECTED_APPROVAL_API_URL_MESSAGE = (
    "Rejected URL: approval API must be local "
    "http://127.0.0.1:<port> or http://localhost:<port>."
)
APPROVAL_API_UNAVAILABLE_MESSAGE = "Approval API unavailable."

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

PENDING_APPROVAL_COLUMNS: tuple[str, ...] = (
    "request_id",
    "tool_name",
    "risk_score",
    "reasons",
    "arguments_summary",
    "created_at",
    "expires_at",
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


@dataclass(frozen=True)
class ApprovalApiUrlResult:
    accepted: bool
    base_url: str
    warning: str | None = None


@dataclass(frozen=True)
class ApprovalApiResponse:
    ok: bool
    payload: object | None = None
    warning: str | None = None
    status_code: int | None = None


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


def normalize_approval_api_base_url(raw: str) -> ApprovalApiUrlResult:
    value = raw.strip() or DEFAULT_APPROVAL_API_BASE_URL
    parsed = urlparse(value)

    try:
        port = parsed.port
    except ValueError:
        port = None

    hostname = parsed.hostname
    if (
        parsed.scheme != "http"
        or hostname not in {"127.0.0.1", "localhost"}
        or port is None
        or port < 1
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params != ""
        or parsed.query != ""
        or parsed.fragment != ""
        or parsed.path not in {"", "/"}
    ):
        return ApprovalApiUrlResult(
            accepted=False,
            base_url=value,
            warning=REJECTED_APPROVAL_API_URL_MESSAGE,
        )

    return ApprovalApiUrlResult(
        accepted=True,
        base_url=f"http://{hostname}:{port}",
    )


def fetch_pending_approvals(
    base_url: str,
    http_client: httpx.Client | None = None,
) -> ApprovalApiResponse:
    return _request_approval_api(
        method="GET",
        base_url=base_url,
        path="/approvals/pending",
        http_client=http_client,
    )


def approve_pending_request(
    base_url: str,
    request_id: str,
    http_client: httpx.Client | None = None,
) -> ApprovalApiResponse:
    return _request_approval_api(
        method="POST",
        base_url=base_url,
        path=f"/approvals/{request_id}/approve",
        http_client=http_client,
    )


def reject_pending_request(
    base_url: str,
    request_id: str,
    http_client: httpx.Client | None = None,
) -> ApprovalApiResponse:
    return _request_approval_api(
        method="POST",
        base_url=base_url,
        path=f"/approvals/{request_id}/reject",
        http_client=http_client,
    )


def build_pending_approvals_dataframe(
    approvals: list[dict[str, object]],
) -> pd.DataFrame:
    rows = [
        {
            "request_id": _approval_text(approval.get("request_id")),
            "tool_name": _approval_text(approval.get("tool_name")),
            "risk_score": approval.get("risk_score"),
            "reasons": _approval_reasons_text(approval.get("reasons")),
            "arguments_summary": _approval_text(approval.get("arguments_summary")),
            "created_at": _approval_text(approval.get("created_at")),
            "expires_at": _approval_text(approval.get("expires_at")),
        }
        for approval in approvals
    ]
    if not rows:
        return pd.DataFrame(columns=list(PENDING_APPROVAL_COLUMNS))
    return pd.DataFrame(rows, columns=list(PENDING_APPROVAL_COLUMNS))


def format_approval_label(approval: dict[str, object], index: int) -> str:
    request_id = _approval_text(approval.get("request_id"))
    short_id = request_id[:8] if request_id else "unknown"
    tool_name = _approval_text(approval.get("tool_name")) or "unknown"
    risk_score = _approval_text(approval.get("risk_score")) or "-"
    return f"#{index + 1} {tool_name} | risk={risk_score} | {short_id}"


def bounded_dashboard_text(text: object, limit: int = 2_000) -> str:
    if text is None:
        return ""
    value = str(text)
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _request_approval_api(
    method: str,
    base_url: str,
    path: str,
    http_client: httpx.Client | None = None,
) -> ApprovalApiResponse:
    url_result = normalize_approval_api_base_url(base_url)
    if not url_result.accepted:
        return ApprovalApiResponse(ok=False, warning=url_result.warning)

    url = f"{url_result.base_url}{path}"
    try:
        if http_client is None:
            with httpx.Client(timeout=APPROVAL_API_TIMEOUT_SECONDS) as client:
                response = client.request(method, url)
        else:
            response = http_client.request(method, url)
    except httpx.HTTPError:
        return ApprovalApiResponse(
            ok=False,
            warning=APPROVAL_API_UNAVAILABLE_MESSAGE,
        )

    if response.status_code >= 400:
        detail = _safe_http_error_detail(response)
        return ApprovalApiResponse(
            ok=False,
            warning=f"Approval API returned HTTP {response.status_code}: {detail}",
            status_code=response.status_code,
        )

    try:
        payload = response.json()
    except ValueError:
        return ApprovalApiResponse(
            ok=False,
            warning="Approval API returned invalid JSON.",
            status_code=response.status_code,
        )

    return ApprovalApiResponse(
        ok=True,
        payload=payload,
        status_code=response.status_code,
    )


def _safe_http_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "request_failed"

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return bounded_dashboard_text(detail, limit=160)

    return "request_failed"


def _approval_reasons_text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return _approval_text(value)


def _approval_text(value: object) -> str:
    if value is None:
        return ""
    return str(value)
