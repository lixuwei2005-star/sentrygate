# Step 13: Approval API + Dashboard UI Spec

## Status

Spec only. No backend code, dashboard code, tests, README updates, or existing
docs are introduced in this step. This document defines the future Step 13
implementation.

## Goal

Add a local approval UI to the Streamlit AgentOps dashboard so a local operator
can approve or reject pending SentryGate approval requests.

Step 12 added the in-process Python approval API:

- `SafeToolService.approve_request(request_id)`
- `SafeToolService.reject_request(request_id)`

However, the Streamlit dashboard runs in a separate process from the MCP server.
The private execution payload for a pending approval request lives inside the
MCP server process, next to the `SafeToolService` and `InMemoryApprovalStore`.
Therefore, the dashboard cannot safely approve directly unless the MCP server
also exposes a local approval API that uses the same `SafeToolService` instance.

Required local architecture:

```text
Codex / MCP Agent
  -> SentryGate MCP Server
  -> SafeToolService + InMemoryApprovalStore
  -> optional Local Approval API on 127.0.0.1
  -> Streamlit Dashboard approval buttons
```

This remains a local prototype approval workflow. It is not a cloud approval
service, production authentication system, or multi-user authorization layer.

## Scope

The future implementation will add:

1. An optional local approval API inside the MCP server process.
2. A dashboard section for listing pending approval requests.
3. Dashboard buttons for approving and rejecting pending requests.
4. Configuration that keeps the approval API disabled by default.
5. Localhost-only binding for the approval API.

The future implementation must not:

- Expose approval through MCP tools.
- Add production authentication or RBAC.
- Store raw approval payloads on disk.
- Allow direct dashboard execution of file or command operations.

## Non-Goals

- No cloud approval service.
- No production-grade authentication.
- No multi-user RBAC.
- No durable approval database.
- No approval for `read_file` or `list_directory`.
- No approval override for `block`.
- No direct dashboard execution of file operations.
- No direct dashboard execution of shell commands.
- No MCP tools for approval.
- No persistence of private execution payloads to JSONL.

## Approval API Architecture

The approval API must run in the same process as the MCP server and must use the
same `SafeToolService` instance that created the pending approval requests.

This same-process requirement is the core design constraint for Step 13:

- `ApprovalRequest` display fields may be safely returned to the dashboard.
- The private execution payload must remain process-local.
- Approval execution must happen only through
  `SafeToolService.approve_request(request_id)`.
- Rejection must happen only through
  `SafeToolService.reject_request(request_id)`.

Expected future file:

- `backend/app/approvals/api.py`

Expected future files that may change:

- `backend/app/mcp/server.py`
- `backend/dashboard/agentops_dashboard.py`
- `backend/dashboard/_data.py`, if pure dashboard data helpers are needed
- `backend/tests/test_approval_api.py`
- `backend/tests/test_dashboard_data.py`, if dashboard data helpers change

`backend/pyproject.toml` should not need new dependencies because FastAPI,
uvicorn, and httpx already exist.

## API Configuration

The local approval API must be disabled by default.

Supported configuration:

- CLI argument: `--approval-api-port 8766`
- Environment variable: `SENTRYGATE_APPROVAL_API_PORT=8766`

Configuration behavior:

- If no approval API port is configured, do not start the approval API server.
- If both CLI and environment variable are configured, the CLI argument should
  take precedence.
- If configured, start the approval API in a background thread from the MCP
  server process.
- The approval API must bind only to `127.0.0.1`.
- Existing MCP server behavior must remain unchanged when the approval API is
  not configured.

Expected MCP server change:

- Add CLI argument `--approval-api-port`.
- Read `SENTRYGATE_APPROVAL_API_PORT`.
- When configured, start a small FastAPI approval API with uvicorn in a
  background thread using the same `SafeToolService` instance.

## API Endpoints

Suggested endpoints:

- `GET /health`
- `GET /approvals/pending`
- `POST /approvals/{request_id}/approve`
- `POST /approvals/{request_id}/reject`

### GET /health

Returns a small health response suitable for dashboard connectivity checks.

The response may include:

```json
{
  "ok": true,
  "service": "sentrygate-approval-api"
}
```

The health endpoint must not expose configuration secrets, request payloads, or
private approval execution data.

### GET /approvals/pending

Returns display-safe pending `ApprovalRequest` objects only.

Returned fields:

- `request_id`
- `created_at`
- `session_id`
- `tool_name`
- `arguments_summary`
- `original_arguments`
- `risk_score`
- `reasons`
- `status`
- `expires_at`

The endpoint must:

- Return only pending requests.
- Use the display-safe representation from the approval store.
- Never expose the private execution payload.
- Never expose raw secrets.
- Avoid reconstructing or expanding raw arguments.

### POST /approvals/{request_id}/approve

Approves and executes a pending request through the existing safe approval path.

Required behavior:

1. Call `SafeToolService.approve_request(request_id)`.
2. Let `approve_request` re-run the existing risk scoring and policy checks.
3. Return `ToolExecutionResult`-style data.
4. Never expose the raw private payload.
5. Never let the dashboard change arguments.
6. Never execute through a separate dashboard path.

Approve must preserve Step 12 safety semantics:

- `block` remains non-approvable.
- Approved requests execute only if the existing approval path still permits
  execution.
- Approval must not bypass `RiskScorer`.
- Approval must not bypass `SafeToolService`.

The response should include safe result fields such as:

- `ok`
- `decision`
- `risk_score`
- `reasons`
- `output`, already limited or summarized by existing service behavior
- `error`
- `masked_findings`
- `approval_request_id`

### POST /approvals/{request_id}/reject

Rejects a pending request without executing anything.

Required behavior:

1. Call `SafeToolService.reject_request(request_id)`.
2. Return the rejected display-safe `ApprovalRequest`.
3. Never execute the original operation.
4. Never expose the raw private payload.
5. Never expose raw secrets.

Reject must be safe for missing, expired, already rejected, already approved, or
already executed requests according to the Step 12 approval store semantics.

## Dashboard UI

Add a new Streamlit dashboard section:

```text
Pending Approvals
```

The dashboard should allow the local operator to configure:

- Approval API base URL, default `http://127.0.0.1:8766`

The dashboard must use this API as its only approval data source. It must not
read private in-memory state directly, call MCP tools, execute commands, or read
workspace files to perform approval actions.

## Pending Approvals List

The dashboard should call:

```text
GET /approvals/pending
```

The UI should show a table of pending approval requests with these columns:

- `request_id`
- `tool_name`
- `risk_score`
- `reasons`
- `arguments_summary`
- `created_at`
- `expires_at`

Display behavior:

- Show an empty state when no pending approvals exist.
- Show a non-blocking connection warning when the approval API is unreachable.
- Keep reasons readable, such as a short joined string.
- Keep long summaries bounded so the dashboard remains usable.
- Do not display raw secrets.
- Do not display any private execution payload.

The dashboard may include a manual refresh control, and it should refresh the
pending list after each approve or reject action.

## Approval Actions

Each pending request row or detail view should provide:

- Approve
- Reject

### Approve Button

When approve is clicked, the dashboard must:

1. Call `POST /approvals/{request_id}/approve`.
2. Show the returned result in a safe summary.
3. Include result fields such as `decision`, `ok`, `error`, and a bounded
   `output` summary when present.
4. Refresh the pending approval list.

The dashboard must not:

- Modify request arguments.
- Execute the requested file or command operation directly.
- Call MCP tools.
- Attempt to read files to preview the write or command result.

### Reject Button

When reject is clicked, the dashboard must:

1. Call `POST /approvals/{request_id}/reject`.
2. Show the rejected request status.
3. Refresh the pending approval list.

Reject must never execute the original operation.

## Dashboard Data Helpers

If dashboard HTTP calls are extracted into helper functions, they should live in
an existing dashboard helper module or a small new helper consistent with the
current dashboard structure.

Expected future file that may change if needed:

- `backend/dashboard/_data.py`

Helper behavior should be easy to unit-test:

- Build URLs safely from a configured base URL.
- Use httpx or an already-available HTTP client dependency.
- Return normalized data for the Streamlit UI.
- Convert connection failures into dashboard-friendly error objects.
- Avoid logging or rendering raw response bodies if they might contain
  unexpected sensitive data.

## Security Requirements

The approval API and dashboard must preserve these boundaries:

- API disabled by default.
- API enabled only by `--approval-api-port` or
  `SENTRYGATE_APPROVAL_API_PORT`.
- API binds only to `127.0.0.1`.
- No approval API server starts when no approval API port is configured.
- No raw secrets exposed.
- No private execution payload exposed.
- No raw secrets logged.
- Dashboard cannot change request arguments.
- Dashboard cannot execute commands directly.
- Dashboard cannot read workspace files directly.
- Dashboard cannot call MCP tools.
- Approval execution goes only through
  `SafeToolService.approve_request(request_id)`.
- Approval still re-runs `RiskScorer` through the existing SafeToolService
  approval path.
- `block` remains non-approvable.
- `read_file` and `list_directory` remain out of scope for approval.
- No raw approval payloads are stored on disk.
- No private execution payloads are written to JSONL.
- No production auth, RBAC, or cloud approval claims are added.

This is explicitly a local prototype approval UI.

## Testing Expectations

Add focused tests for the API and any extracted dashboard helpers.

Expected future test file:

- `backend/tests/test_approval_api.py`

Expected optional future test file:

- `backend/tests/test_dashboard_data.py`

API tests should cover:

- No API starts unless the approval API port is configured, where practical at
  the server configuration layer.
- Pending endpoint returns display-safe pending requests.
- Pending endpoint does not include private execution payloads.
- Approve endpoint calls `SafeToolService.approve_request(request_id)`.
- Approve endpoint returns `ToolExecutionResult`-style data.
- Approve endpoint can execute an approved `write_file` through the
  SafeToolService approval path.
- Approve endpoint does not allow argument mutation.
- Reject endpoint calls `SafeToolService.reject_request(request_id)`.
- Reject endpoint marks a request rejected and does not execute anything.
- Hard-blocked requests remain non-approvable.
- Raw secrets and private payloads are not exposed in API responses.

Dashboard helper tests, if helpers are extracted, should cover:

- Pending approvals fetch success.
- Approval POST success.
- Rejection POST success.
- Connection failure normalization.
- Response normalization for UI display.
- No direct command, file, or MCP execution helper behavior.

Existing tests should continue to pass.

## Local Run Behavior

Default MCP server behavior remains unchanged:

```text
uv run python -m app.mcp.server
```

With approval API enabled, the future server command may include:

```text
uv run python -m app.mcp.server --approval-api-port 8766
```

Equivalent environment variable configuration:

```text
SENTRYGATE_APPROVAL_API_PORT=8766
```

The dashboard should default its Approval API base URL input to:

```text
http://127.0.0.1:8766
```

If the approval API is not running, the dashboard should continue to render its
normal observability views and show the approvals section as unavailable rather
than crashing.

## Acceptance Criteria

- Without `--approval-api-port`, MCP server behavior is unchanged.
- Without `SENTRYGATE_APPROVAL_API_PORT`, MCP server behavior is unchanged.
- With an approval API port configured, a local approval API starts on
  `127.0.0.1`.
- `GET /approvals/pending` returns pending write/run requests.
- `GET /approvals/pending` returns only display-safe approval fields.
- `POST /approvals/{request_id}/approve` executes an approved `write_file`
  through `SafeToolService.approve_request()`.
- `POST /approvals/{request_id}/reject` marks a request rejected and does not
  execute the original operation.
- The API does not expose private payloads.
- The API does not expose raw secrets.
- The dashboard can list pending approvals.
- The dashboard approve button calls the local approval API and shows a safe
  result summary.
- The dashboard reject button calls the local approval API and shows rejected
  status.
- The dashboard remains read-only except for local approval API calls.
- The dashboard does not execute commands directly.
- The dashboard does not read workspace files directly for approval actions.
- The dashboard does not call MCP tools.
- Existing tests still pass.
- `pytest`, `ruff`, and `mypy` pass.

## Implementation Constraints

- Do not implement approval as MCP tools.
- Do not allow approval to override `block`.
- Do not persist private payloads to JSONL.
- Do not add production auth claims.
- Do not add production RBAC claims.
- Do not add a cloud approval service.
- Keep the implementation as a local prototype approval UI.
