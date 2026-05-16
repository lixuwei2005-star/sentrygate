# STEP 10 — Streamlit AgentOps Dashboard (Local Prototype)

## Status
Spec only. No backend code, no dashboard files, and no dependency changes are introduced
in this step. This document defines what the future implementation must do.

## Goal
Build a **local Streamlit dashboard prototype** that gives SentryGate an
AgentOps-style observability view over MCP-routed tool calls by reading the JSONL
audit log that SentryGate already produces.

> SentryGate only observes MCP-routed tool calls. The dashboard inherits this
> boundary: it visualizes what the MCP layer recorded, nothing else.

This is explicitly a **local prototype**, not a production monitoring system.

---

## Context (what already exists)

SentryGate currently provides everything the dashboard needs as input:

- MCP server integration (Step 5)
- `SafeToolService` orchestrating the policy / risk / privacy pipeline
- `RiskScorer` producing structured risk scores and reasons
- `PrivacyMasker` producing `masked_findings`
- `InMemoryAuditStore` and `JsonlAuditStore` (Step 9)
- `AuditEvent` with `trace_id`, `span_id`, `session_id`, `started_at`,
  `ended_at`, `latency_ms`
- `metrics summary` module (Step 9)
- Optional LM Studio review (Step 6)
- Local demo script (Step 5.4 / README)

The dashboard's only data source is the JSONL audit log file written by
`JsonlAuditStore`.

---

## Scope for the future implementation

In a later step, the implementer will:

1. Add a local Streamlit dashboard.
2. Read audit events from a JSONL audit log file.
3. Reuse the existing `JsonlAuditStore` and `metrics summary` code instead of
   re-implementing parsing or aggregation.
4. Show AgentOps-style observability for MCP-routed tool calls.
5. **Not** change MCP tool behavior.
6. **Not** change risk scoring.
7. **Not** change privacy masking.
8. **Not** change LM Studio behavior.
9. **Not** build a React frontend. Streamlit only.

---

## Expected future files

- `backend/dashboard/agentops_dashboard.py` — Streamlit entrypoint.
- `backend/tests/test_dashboard_data.py` — optional, if pure-data helpers are
  extracted out of the Streamlit script and are worth unit-testing.
- `backend/pyproject.toml` — may be updated to add `streamlit` as an optional /
  dev dependency. The runtime MCP server must remain runnable without Streamlit
  installed.

No other files should be modified by this step.

---

## Dashboard features

### 1. Audit log path input
- Provide a text input for the JSONL audit log path.
- Default to `backend/.sentrygate/audit_events.jsonl`.
- Resolve the path relative to the repository root so it works regardless of
  where Streamlit is launched from inside `backend/`.
- If the file does not exist: show a non-blocking warning explaining how to
  generate one (point to the demo workflow below) and render an empty state
  rather than crashing.
- If the file exists but is empty: render an empty state ("No audit events
  yet").
- If individual lines fail to parse: skip them, count them, and surface the
  count as a small warning. Never raise.

### 2. Summary cards
Render the following metrics at the top using Streamlit `st.metric` cards:

- `total_calls`
- `allowed_calls`
- `blocked_calls`
- `require_approval_calls`
- `executed_calls`
- `average_latency_ms`
- `high_risk_events`
- `masked_finding_count`

All values must come from the existing `metrics summary` module so the
dashboard and the CLI/MCP layers stay consistent.

### 3. Charts
- **Decision distribution** — bar chart of `decision` counts
  (`allow` / `block` / `require_approval`).
- **Tool call counts** — bar chart of calls per `tool_name`.
- **Risk score distribution** — histogram of `risk_score`.
- **Latency over recent calls** — line chart of `latency_ms` ordered by
  `started_at`, shown only when at least one event has `latency_ms` populated.
- **Top risk reasons** — bar chart of the most frequent entries in the
  `reasons` arrays across events.

Charts should use Streamlit's built-in chart primitives (`st.bar_chart`,
`st.line_chart`) or a lightweight dataframe-based approach. No heavy
visualization dependency should be introduced.

### 4. Recent events table
A paginated / capped table (e.g. last 100 events, newest first) with columns:

- `timestamp` (prefer `started_at`)
- `trace_id`
- `span_id`
- `session_id`
- `tool_name`
- `decision`
- `risk_score`
- `latency_ms`
- `reasons` (joined short form)
- `masked_findings` count
- `executed` (bool)

The table must only display fields that already exist on `AuditEvent`.

### 5. Event detail view
Selecting a row (e.g. via an "Inspect" selectbox keyed by `trace_id` /
`span_id`) reveals:

- `arguments_summary`
- `output_summary`
- `reasons`
- `masked_findings`
- `trace_id`, `span_id`, `session_id`, `started_at`, `ended_at`,
  `latency_ms`

The detail view must render the **already-masked** `arguments_summary` and
`output_summary` exactly as stored. It must not attempt to unmask, decode, or
reconstruct original values.

### 6. Safety requirements
The dashboard:

- MUST NOT display raw secrets. It only renders what `PrivacyMasker` already
  masked into the audit event.
- MUST only read fields defined on `AuditEvent` from the JSONL file.
- MUST NOT read files from the protected workspace directly.
- MUST NOT execute shell commands or subprocesses.
- MUST NOT call MCP tools.
- MUST be read-only — no writes back to the audit log, no edits, no deletes.
- MUST preserve the MCP-only boundary statement somewhere visible in the UI
  (e.g. footer or sidebar): *"SentryGate only observes MCP-routed tool calls."*

### 7. Local run command
The dashboard is launched from `backend/` with:

```
uv run streamlit run dashboard/agentops_dashboard.py
```

No additional CLI flags should be required for the default path.

### 8. Demo workflow
To generate data for the dashboard:

1. Start the SentryGate MCP server with:
   ```
   --audit-log-path backend/.sentrygate/audit_events.jsonl
   ```
2. Use Codex (or any MCP-capable client) to call SentryGate's MCP tools so
   the audit log accumulates events.
3. In a separate terminal, launch the Streamlit dashboard with the command
   from section 7.
4. View summary cards, charts, recent events, and event detail.

### 9. Acceptance criteria
- Dashboard reads JSONL audit events from the configured path.
- Dashboard handles a missing log file gracefully (warning + empty state, no
  crash).
- Dashboard shows the summary metrics listed in section 2.
- Dashboard shows charts for decisions, tools, risks, and reasons (plus
  latency when available).
- Dashboard shows a recent events table with the fields listed in section 4.
- Dashboard does not display raw secrets — only masked/summarized fields from
  `AuditEvent`.
- Dashboard is read-only.
- Existing backend tests still pass.
- `ruff` and `mypy` pass on any new dashboard code where applicable.

---

## Important constraints

- Do **not** overclaim production-grade monitoring. This is a local AgentOps
  dashboard prototype for SentryGate.
- Preserve the project boundary: *SentryGate only observes MCP-routed tool
  calls.* The dashboard does not widen this scope.
- Do **not** modify backend runtime behavior as part of this spec step. Spec
  only.
