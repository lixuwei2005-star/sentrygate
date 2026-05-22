"""SentryGate AgentOps dashboard (local prototype).

Read-only Streamlit dashboard that visualizes MCP-routed tool calls from a
JSONL audit log produced by SentryGate's JsonlAuditStore.

SentryGate only observes MCP-routed tool calls. This dashboard inherits
that boundary: it never reads protected workspace files, never calls MCP
tools, and never executes commands.
"""

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from datetime import UTC, datetime  # noqa: E402

import streamlit as st  # noqa: E402

from app.audit.metrics import summarize_audit_events  # noqa: E402
from app.audit.models import AuditEvent  # noqa: E402
from dashboard._data import (  # noqa: E402
    DEFAULT_APPROVAL_API_BASE_URL,
    ApprovalApiResponse,
    LoadResult,
    approve_pending_request,
    bounded_dashboard_text,
    build_latency_series,
    build_pending_approvals_dataframe,
    build_recent_events_dataframe,
    build_risk_score_buckets,
    fetch_pending_approvals,
    format_approval_label,
    format_event_label,
    has_latency_data,
    load_events,
    reject_pending_request,
    resolve_audit_log_path,
    sort_events_newest_first,
)

DEFAULT_AUDIT_LOG_PATH = "backend/.sentrygate/audit_events.jsonl"
BOUNDARY_STATEMENT = "SentryGate only observes MCP-routed tool calls."
RECENT_EVENTS_LIMIT = 100
APPROVAL_ACTION_RESULT_KEY = "sentrygate_approval_action_result"


def _render_sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.header("SentryGate AgentOps")
        st.caption("Local dashboard prototype")
        path_input = st.text_input(
            "Audit log path",
            value=DEFAULT_AUDIT_LOG_PATH,
            help="JSONL audit log written by SentryGate's JsonlAuditStore.",
        )
        approval_api_base_url = st.text_input(
            "Approval API base URL",
            value=DEFAULT_APPROVAL_API_BASE_URL,
            help="Local approval API exposed by the SentryGate MCP server.",
        )
        st.button("Reload")
        st.divider()
        st.caption(BOUNDARY_STATEMENT)
        st.caption(
            "Read-only audit view. Approval actions only call the local "
            "approval API."
        )
    return path_input, approval_api_base_url


def _render_status_strip(result: LoadResult) -> None:
    cols = st.columns(3)
    cols[0].markdown(f"**Log path**: `{result.path}`")
    cols[1].markdown(f"**Events loaded**: {len(result.events)}")
    if not result.rejected and result.path.exists():
        mtime = datetime.fromtimestamp(
            result.path.stat().st_mtime, tz=UTC
        )
        cols[2].markdown(
            f"**Last modified**: {mtime.isoformat(timespec='seconds')}"
        )
    else:
        cols[2].markdown("**Last modified**: n/a")


def _render_summary_cards(events: list[AuditEvent]) -> None:
    summary = summarize_audit_events(events)
    row1 = st.columns(4)
    row1[0].metric("Total calls", summary.total_calls)
    row1[1].metric("Allowed", summary.allowed_calls)
    row1[2].metric("Blocked", summary.blocked_calls)
    row1[3].metric("Require approval", summary.require_approval_calls)

    row2 = st.columns(4)
    row2[0].metric("Executed", summary.executed_calls)
    row2[1].metric("Avg latency (ms)", f"{summary.average_latency_ms:.1f}")
    row2[2].metric("High-risk events", summary.high_risk_events)
    row2[3].metric("Masked findings", summary.masked_finding_count)


def _render_charts(result: LoadResult) -> None:
    summary = summarize_audit_events(result.events)

    st.subheader("Charts")
    row1 = st.columns(2)
    with row1[0]:
        st.caption("Decision distribution")
        st.bar_chart(summary.decision_counts)
    with row1[1]:
        st.caption("Tool call counts")
        if summary.tool_call_counts:
            st.bar_chart(summary.tool_call_counts)
        else:
            st.caption("(no tool calls)")

    row2 = st.columns(2)
    with row2[0]:
        st.caption("Risk score distribution")
        st.bar_chart(build_risk_score_buckets(result.events))
    with row2[1]:
        st.caption("Top risk reasons")
        reason_counts = {
            rc.reason: rc.count for rc in summary.top_risk_reasons
        }
        if reason_counts:
            st.bar_chart(reason_counts)
        else:
            st.caption("(no reasons recorded)")

    if has_latency_data(result.events):
        st.caption("Latency over recent calls (ms)")
        st.line_chart(build_latency_series(result.events))


def _render_recent_events_table(result: LoadResult) -> None:
    st.subheader("Recent events")
    frame = build_recent_events_dataframe(
        result.events, limit=RECENT_EVENTS_LIMIT
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)


def _render_event_detail(result: LoadResult) -> None:
    st.subheader("Event detail")
    sorted_events = sort_events_newest_first(result.events)[
        :RECENT_EVENTS_LIMIT
    ]
    if not sorted_events:
        st.caption("(no events to inspect)")
        return

    labels = [
        format_event_label(event, index)
        for index, event in enumerate(sorted_events)
    ]
    selected_index = st.selectbox(
        "Inspect event",
        options=list(range(len(sorted_events))),
        format_func=lambda index: labels[index],
    )
    if selected_index is None:
        return

    event = sorted_events[selected_index]
    meta_cols = st.columns(3)
    meta_cols[0].markdown(f"**trace_id**: `{event.trace_id or '-'}`")
    meta_cols[0].markdown(f"**span_id**: `{event.span_id or '-'}`")
    meta_cols[1].markdown(f"**session_id**: `{event.session_id or '-'}`")
    latency_text = (
        f"{event.latency_ms:.2f}"
        if event.latency_ms is not None
        else "-"
    )
    meta_cols[1].markdown(f"**latency_ms**: {latency_text}")
    started_text = (
        event.started_at.isoformat(timespec="seconds")
        if event.started_at is not None
        else "-"
    )
    ended_text = (
        event.ended_at.isoformat(timespec="seconds")
        if event.ended_at is not None
        else "-"
    )
    meta_cols[2].markdown(f"**started_at**: {started_text}")
    meta_cols[2].markdown(f"**ended_at**: {ended_text}")

    st.markdown("**arguments_summary** (already masked)")
    st.code(event.arguments_summary)
    st.markdown("**output_summary** (already masked)")
    st.code(event.output_summary or "")

    st.markdown("**reasons**")
    if event.reasons:
        for reason in event.reasons:
            st.markdown(f"- {reason}")
    else:
        st.caption("(none)")

    st.markdown(
        "**masked_findings** (mask placeholders only - never raw secrets)"
    )
    if event.masked_findings:
        findings_rows = [
            {"kind": finding.kind.value, "token": finding.token}
            for finding in event.masked_findings
        ]
        st.dataframe(
            findings_rows, use_container_width=True, hide_index=True
        )
    else:
        st.caption("(none)")


def _render_pending_approvals(api_base_url: str) -> None:
    st.subheader("Pending Approvals")
    st.caption(
        "Local prototype controls. The dashboard only calls the configured "
        "localhost approval API."
    )

    _render_last_approval_action_result()

    response = fetch_pending_approvals(api_base_url)
    if not response.ok:
        st.warning(response.warning or "Approval API unavailable.")
        return

    approvals = _approval_rows(response.payload)
    if not approvals:
        st.info("No pending approvals.")
        return

    st.dataframe(
        build_pending_approvals_dataframe(approvals),
        use_container_width=True,
        hide_index=True,
    )

    labels = [
        format_approval_label(approval, index)
        for index, approval in enumerate(approvals)
    ]
    selected_index = st.selectbox(
        "Review approval request",
        options=list(range(len(approvals))),
        format_func=lambda index: labels[index],
    )
    if selected_index is None:
        return

    approval = approvals[selected_index]
    request_id = str(approval.get("request_id") or "")
    if request_id == "":
        st.warning("Approval request is missing a request_id.")
        return

    detail_cols = st.columns(3)
    detail_cols[0].markdown(f"**request_id**: `{request_id}`")
    detail_cols[0].markdown(
        f"**tool_name**: `{approval.get('tool_name') or '-'}`"
    )
    detail_cols[1].markdown(
        f"**risk_score**: {approval.get('risk_score') or '-'}"
    )
    detail_cols[1].markdown(f"**status**: `{approval.get('status') or '-'}`")
    detail_cols[2].markdown(
        f"**created_at**: `{approval.get('created_at') or '-'}`"
    )
    detail_cols[2].markdown(
        f"**expires_at**: `{approval.get('expires_at') or '-'}`"
    )

    st.markdown("**arguments_summary** (display-safe)")
    st.code(bounded_dashboard_text(approval.get("arguments_summary")))

    reasons = approval.get("reasons")
    st.markdown("**reasons**")
    if isinstance(reasons, list) and reasons:
        for reason in reasons:
            st.markdown(f"- {reason}")
    else:
        st.caption("(none)")

    action_cols = st.columns(2)
    if action_cols[0].button("Approve", key=f"approve-{request_id}"):
        _store_approval_action_result(
            "approve",
            approve_pending_request(api_base_url, request_id),
        )
        st.rerun()

    if action_cols[1].button("Reject", key=f"reject-{request_id}"):
        _store_approval_action_result(
            "reject",
            reject_pending_request(api_base_url, request_id),
        )
        st.rerun()


def _store_approval_action_result(
    action: str,
    response: ApprovalApiResponse,
) -> None:
    st.session_state[APPROVAL_ACTION_RESULT_KEY] = {
        "action": action,
        "ok": response.ok,
        "warning": response.warning,
        "payload": response.payload,
    }


def _render_last_approval_action_result() -> None:
    result = st.session_state.get(APPROVAL_ACTION_RESULT_KEY)
    if not isinstance(result, dict):
        return

    action = str(result.get("action") or "approval")
    if result.get("ok") is not True:
        st.warning(str(result.get("warning") or "Approval action failed."))
        return

    payload = result.get("payload")
    if action == "approve" and isinstance(payload, dict):
        ok_value = payload.get("ok")
        decision = payload.get("decision")
        error = payload.get("error")
        output = bounded_dashboard_text(payload.get("output"), limit=600)
        st.success(f"Approve completed: ok={ok_value}; decision={decision}")
        if error:
            st.caption(f"error: {bounded_dashboard_text(error, limit=240)}")
        if output:
            st.code(output)
        return

    if action == "reject" and isinstance(payload, dict):
        status_text = payload.get("status") or "rejected"
        st.success(f"Reject completed: status={status_text}")
        return

    st.success("Approval action completed.")


def _approval_rows(payload: object | None) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        return []

    rows: list[dict[str, object]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append({str(key): value for key, value in item.items()})
    return rows


def render() -> None:
    st.set_page_config(
        page_title="SentryGate AgentOps",
        layout="wide",
    )

    path_input, approval_api_base_url = _render_sidebar()
    path = resolve_audit_log_path(path_input)
    result = load_events(path)

    st.title("SentryGate AgentOps Dashboard")
    st.caption(
        "Local AgentOps dashboard prototype for MCP-routed tool calls. "
        "Not a production monitoring system."
    )

    _render_status_strip(result)

    if result.warning is not None:
        st.warning(result.warning)

    if result.missing:
        st.warning(
            f"Audit log not found at `{result.path}`. "
            "Start the SentryGate MCP server with "
            "`--audit-log-path backend/.sentrygate/audit_events.jsonl` "
            "and call some tools to generate events."
        )
    elif result.empty and not result.rejected:
        st.info("No audit events yet.")

    if result.skipped > 0:
        st.caption(f"Skipped {result.skipped} unparseable line(s).")

    st.subheader("Summary")
    _render_summary_cards(result.events)

    _render_pending_approvals(approval_api_base_url)

    if len(result.events) == 0:
        return

    _render_charts(result)
    _render_recent_events_table(result)
    _render_event_detail(result)


render()
