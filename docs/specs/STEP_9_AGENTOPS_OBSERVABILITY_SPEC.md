# Step 9 AgentOps Observability Layer Spec

## 1. Goal

Extend SentryGate from a security gateway into a privacy-first AgentOps security gateway prototype by adding persistent local observability for MCP-routed tool calls.

This step is specification-only. It defines the future implementation for local JSONL audit persistence, trace/span-style audit fields, metrics summary generation, and dashboard-ready data. It does not modify backend code yet.

## 2. Current context

SentryGate already has:

- MCP server integration.
- `SafeToolService`.
- `RiskScorer`.
- `PrivacyMasker`.
- `InMemoryAuditStore`.
- `ToolExecutionResult`.
- `AuditEvent`.
- Local demo script.
- Optional LM Studio review.

The current audit store is in memory. That is useful for tests and demos, but a future dashboard cannot reliably monitor Codex tool calls unless masked audit events are also written to a readable local data source.

## 3. Non-goals

Step 9 must not:

- Build a Streamlit dashboard.
- Modify frontend code.
- Change MCP tool names.
- Change MCP tool behavior.
- Change privacy masking logic.
- Change risk scoring behavior.
- Enable LM Studio by default.
- Store enterprise telemetry.
- Claim production-grade observability.
- Expand protection beyond MCP-routed tool calls.

This remains a local AgentOps observability prototype.

## 4. Persistent JSONL audit store

Add a persistent audit store that appends one masked audit event per line to a local JSONL file.

Expected future file:

- `backend/app/audit/jsonl_store.py`

Suggested class:

- `JsonlAuditStore`

The class should implement the same interface as `InMemoryAuditStore`:

```python
append(event)
list_events(session_id=None, limit=100)
```

### JSONL behavior

`JsonlAuditStore` should:

- Append one JSON object per tool call.
- Use UTF-8.
- Create parent directories if needed.
- Preserve enough fields for dashboard metrics.
- Store only masked or otherwise safe audit event fields.
- Never store raw secrets.
- Be safe and simple for local prototype use.

Each line should represent one completed audit event. The file should remain readable with normal local tools and should not require a database server.

### Event listing behavior

`list_events(session_id=None, limit=100)` should:

- Read events from the JSONL file.
- Return events in a predictable order suitable for recent-event display.
- Support filtering by `session_id`.
- Respect `limit`.
- Gracefully handle a missing log file by returning an empty list.
- Skip or safely handle malformed lines without crashing the whole dashboard data flow.

## 5. Configuration

The MCP server should optionally accept a persistent audit log path.

Supported configuration:

- CLI argument: `--audit-log-path`
- Environment variable: `SENTRYGATE_AUDIT_LOG_PATH`

Configuration behavior:

- If no audit log path is supplied, keep current `InMemoryAuditStore` behavior.
- If an audit log path is supplied, use `JsonlAuditStore` for `SafeToolService`.
- CLI argument should take precedence over the environment variable when both are present.

Expected future file that may change:

- `backend/app/mcp/server.py`

## 6. Trace/span-style audit fields

Extend `AuditEvent` with optional observability fields.

Expected future file that may change:

- `backend/app/audit/models.py`

New optional fields:

```python
trace_id: str | None
span_id: str | None
parent_span_id: str | None
started_at: datetime | None
ended_at: datetime | None
latency_ms: float | None
```

### Field behavior

`SafeToolService` should:

- Generate a `span_id` for each tool call.
- Use `session_id` as the default `trace_id` when `session_id` is present.
- Generate a `trace_id` when `session_id` is not present.
- Leave `parent_span_id` optional for future nested operations.
- Populate `started_at` before safe tool handling begins.
- Populate `ended_at` after the final decision/result is available.
- Record `latency_ms` as the total safe tool handling time.

Existing tests should remain compatible because the new fields are optional and default to `None`.

Expected future file that may change:

- `backend/app/tools/safe_tools.py`

## 7. Metrics summary module

Add a pure Python metrics module that computes dashboard-ready summary data from audit events.

Expected future file:

- `backend/app/audit/metrics.py`

The module should compute:

- `total_calls`
- `allowed_calls`
- `blocked_calls`
- `require_approval_calls`
- `executed_calls`
- `average_latency_ms`
- `high_risk_events`
- `masked_finding_count`
- `tool_call_counts`
- `decision_counts`
- `top_risk_reasons`

### Metrics behavior

Metrics generation should:

- Accept audit events from either `InMemoryAuditStore` or `JsonlAuditStore`.
- Avoid frontend dependencies.
- Be deterministic and easy to unit test.
- Ignore missing optional latency fields when computing `average_latency_ms`.
- Count only available masked finding metadata, not raw masked content.
- Treat decision values consistently with existing audit event semantics.

## 8. Future dashboard data readiness

Step 9 should prepare data for a future Streamlit dashboard, but must not build the dashboard yet.

The JSONL events and metrics summary should be enough for a future dashboard to show:

- Total tool calls.
- Allow, block, and require-approval distribution.
- Tool call timeline.
- Risk score distribution.
- Latency table.
- Masked findings count.
- Recent high-risk events.
- Top block reasons.

## 9. Safety requirements

Persistent observability must preserve SentryGate's privacy-first boundary.

The JSONL audit log must not include:

- Raw secrets.
- Raw file contents.
- Raw command output.
- Raw LM Studio prompts.
- Raw LM Studio model responses.
- Any data that bypasses existing privacy masking.

Existing masking behavior must still apply. The persistent store should receive the same safe event data that is suitable for audit display.

SentryGate still only protects MCP-routed tool calls. Step 9 must not imply protection for direct shell commands, direct filesystem access, browser activity, or tools outside the SentryGate MCP route.

## 10. Expected future implementation files

Future implementation may add:

- `backend/app/audit/jsonl_store.py`
- `backend/app/audit/metrics.py`
- `backend/tests/test_jsonl_audit_store.py`
- `backend/tests/test_audit_metrics.py`

Future implementation may modify:

- `backend/app/audit/models.py`
- `backend/app/tools/safe_tools.py`
- `backend/app/mcp/server.py`

No backend code is modified by this spec step.

## 11. Testing plan

Future tests should verify:

- `JsonlAuditStore` creates parent directories.
- `JsonlAuditStore` appends one JSON object per line.
- `JsonlAuditStore` lists events with `session_id` filtering.
- `JsonlAuditStore` respects `limit`.
- `JsonlAuditStore` returns an empty list when the file does not exist.
- `AuditEvent` accepts omitted trace/span/latency fields.
- `SafeToolService` records `span_id`, `trace_id`, timestamps, and `latency_ms`.
- Metrics count decisions, tools, executed calls, risk reasons, and masked findings.
- No raw secrets are written to JSONL.
- Existing tests continue to pass.

Validation commands:

```bash
cd backend
uv run pytest
uv run ruff check .
uv run mypy app
```

## 12. Acceptance criteria

- `JsonlAuditStore` appends masked events as JSONL.
- `JsonlAuditStore` can list events with session filter and limit.
- `AuditEvent` supports optional trace/span/latency fields without breaking existing tests.
- `SafeToolService` records `latency_ms` for each tool call.
- MCP server can use `JsonlAuditStore` when `--audit-log-path` is provided.
- `SENTRYGATE_AUDIT_LOG_PATH` can configure persistent logging when the CLI argument is absent.
- Metrics summary correctly counts decisions, tools, risk reasons, and masked findings.
- No raw secrets are written to JSONL.
- Existing tests still pass.
- `pytest`, `ruff`, and `mypy` pass.

## 13. Implementation order

Recommended future implementation order:

1. Add optional fields to `AuditEvent`.
2. Implement `JsonlAuditStore`.
3. Add JSONL audit store tests.
4. Populate trace/span/latency fields in `SafeToolService`.
5. Wire `--audit-log-path` and `SENTRYGATE_AUDIT_LOG_PATH` into the MCP server.
6. Add metrics summary module.
7. Add metrics tests.
8. Run full backend validation.

