# Step 12: Human-in-the-loop Approval Workflow Spec

## Status

Spec only. No backend code, dashboard code, tests, README updates, or existing
docs are introduced in this step. This document defines the future Step 12
implementation.

## Goal

Turn `require_approval` from a terminal decision into a safe local
pending-approval workflow for selected mutating operations.

Current behavior:

- `block`: never executes.
- `require_approval`: never executes and returns `operation_requires_approval`.
- `allow`: executes immediately.

Future behavior:

- `block`: still never executes.
- `allow`: still executes immediately.
- `require_approval`: creates a pending approval request and does not execute
  yet.
- A local operator can later approve or reject the pending request.
- An approved request executes only if it is still safe under policy.

This is a local prototype workflow. It is not production-grade authentication,
authorization, RBAC, or a cloud approval service.

## Scope

The future implementation will add:

- An `ApprovalRequest` model.
- An in-memory approval store.
- A safe approval execution flow.
- A Python API for approving and rejecting requests.
- Audit events for approval lifecycle transitions.
- Result metadata that exposes the created approval request ID.

Optional dashboard integration may happen later, but it is out of scope for
Step 12.

## Non-Goals

- No approval UI in Step 12.
- No production authentication system.
- No multi-user RBAC.
- No cloud approval service.
- No changes to MCP tool names.
- No approval override for `block`.
- No approvals for `read_file` or `list_directory` in the MVP.
- No storage backend beyond the first in-memory store.

## Supported Tools for Approval MVP

Approval is supported only for:

- `sentry_write_file`
- `sentry_run_command`

Approval must not be added for:

- `sentry_read_file`
- `sentry_list_directory`

Rationale:

- Sensitive reads should stay blocked at policy level when they touch protected
  paths.
- Directory listing is already a lower-risk operation.
- File writes and command execution are the main mutating operations with the
  highest local blast radius.

## ApprovalRequest Model

Add an approval request model with these fields:

```python
class ApprovalRequest(BaseModel):
    request_id: str
    created_at: datetime
    session_id: str | None
    tool_name: str
    arguments_summary: str
    original_arguments: dict[str, object]
    risk_score: int
    reasons: list[str]
    status: Literal["pending", "approved", "rejected", "expired", "executed"]
    expires_at: datetime | None
```

Field requirements:

- `request_id` must be unique and unguessable enough for a local prototype,
  such as a UUID string.
- `created_at` records when the pending request was created.
- `session_id` preserves the originating session when available.
- `tool_name` stores the reviewed tool name and must not be mutable during
  approval.
- `arguments_summary` is safe, masked, and suitable for display or audit logs.
- `original_arguments` stores only a masked or safe representation where
  possible. It must not intentionally store raw secrets.
- `risk_score` and `reasons` record the risk result observed when the request
  was created.
- `status` starts as `pending` and changes through explicit approval workflow
  transitions.
- `expires_at` should either be populated by the implementation or the request
  must otherwise be clearly scoped. Expiry behavior must be tested if the field
  is enforced.

The public `ApprovalRequest` fields returned from `get` and `list_pending`
must be safe to display. If exact later execution requires raw argument data
that cannot be safely represented, the in-memory implementation may keep a
private, process-local execution payload keyed by `request_id`. That payload
must never be exposed through audit logs, CLI output, dashboard data, or the
display-facing approval request representation.

The implementation must retain enough reviewed argument data to execute the
same request later without allowing arbitrary argument substitution. It must not
put raw secrets into logs, CLI output, or dashboard-facing summaries.

## ApprovalStore

Start with `InMemoryApprovalStore`.

Required methods:

```python
class InMemoryApprovalStore:
    def create(self, request: ApprovalRequest) -> ApprovalRequest:
        ...

    def get(self, request_id: str) -> ApprovalRequest | None:
        ...

    def list_pending(
        self,
        session_id: str | None = None,
    ) -> list[ApprovalRequest]:
        ...

    def approve(self, request_id: str) -> ApprovalRequest:
        ...

    def reject(self, request_id: str) -> ApprovalRequest:
        ...
```

Store behavior:

- `create` stores a pending request and returns the stored request.
- `get` returns a request by ID or `None`.
- `list_pending` returns only requests with `status == "pending"`.
- `list_pending(session_id=...)` filters pending requests to that session.
- `approve` moves a pending request to `approved` and returns it.
- `reject` moves a pending request to `rejected` and returns it.
- Approving or rejecting a missing, expired, executed, rejected, or already
  approved request must fail safely.
- The in-memory store may reset on process restart. That limitation must be
  documented in user-facing implementation notes.

## ToolExecutionResult Changes

When a safe tool call creates an approval request, return:

```python
class ToolExecutionResult(BaseModel):
    ok: bool
    decision: Literal["allow", "block", "require_approval"]
    risk_score: int
    reasons: list[str]
    output: str | None = None
    error: str | None = None
    masked_findings: list[object] | tuple[object, ...]
    approval_request_id: str | None = None
```

Required behavior for `require_approval`:

- `decision == "require_approval"`
- `ok is False`
- `error == "operation_requires_approval"`
- `approval_request_id` contains the new request ID when a request was created.
- `approval_request_id is None` when no request was created.

Hard-blocked operations must not create approval requests and must return
`approval_request_id=None`.

## Creation Flow

When `sentry_write_file` or `sentry_run_command` receives a
`require_approval` decision:

1. Do not execute the operation.
2. Build a masked `arguments_summary`.
3. Build an `ApprovalRequest` for the exact reviewed tool and arguments.
4. Store the request in `InMemoryApprovalStore`.
5. Write an audit event for approval request creation.
6. Return `ToolExecutionResult` with `approval_request_id` populated.

When any operation receives a `block` decision:

1. Do not execute the operation.
2. Do not create an approval request.
3. Write the normal blocked audit event with `executed=False`.
4. Return a blocked `ToolExecutionResult`.

## Approval API

Recommended MVP: implement a Python API first.

Future methods:

```python
class SafeToolService:
    def approve_request(self, request_id: str) -> ToolExecutionResult:
        ...

    def reject_request(self, request_id: str) -> ApprovalRequest:
        ...
```

CLI helpers may be added later:

```text
python -m app.approvals.cli list
python -m app.approvals.cli approve <request_id>
python -m app.approvals.cli reject <request_id>
```

Dashboard buttons are explicitly deferred, likely to Step 13 or later.

## Safe Approval Execution Flow

Approval must not blindly execute the original operation. Approving a request
only authorizes the implementation to re-check and then attempt the exact
reviewed operation.

When `approve_request(request_id)` is called:

1. Load the approval request.
2. Ensure it exists and is still pending or explicitly approved by the store
   transition.
3. Ensure it has not expired.
4. Mark the request approved using the store.
5. Write an audit event for the approval decision.
6. Rebuild the `ToolCall` from the reviewed tool name and exact approved
   arguments.
7. Run `RiskScorer` again.
8. Re-validate the workspace boundary.
9. If the new decision is `block`, do not execute.
10. If the new decision is `require_approval` and the request ID matches the
    approved request, allow execution for this exact request only.
11. Execute only the same tool and arguments that were reviewed.
12. Mask output or errors before returning.
13. Write an audit event with `executed=True` only if execution was actually
    attempted.
14. Mark the request `executed` only after the operation has been attempted.

If re-scoring changes the decision to `block`, the result must be safe:

- The operation does not execute.
- The approval request must not be treated as executed.
- The returned result uses `decision="block"` and `ok=False`.
- An audit event records that approved execution was denied by current policy.

If re-scoring still returns `require_approval`, execution is allowed only when:

- The request has been approved through the approval store.
- The request ID is the same request being executed.
- The tool name and arguments match the reviewed request exactly.
- Workspace boundary validation still passes.

Approval must not create a general bypass for future calls with similar
arguments.

## Rejection Flow

When `reject_request(request_id)` is called:

1. Load the approval request.
2. Ensure it exists and can still be rejected.
3. Mark it rejected using the store.
4. Write an audit event for the rejection decision.
5. Do not execute anything.
6. Return the rejected `ApprovalRequest`.

Rejected requests must not be executable later.

## Security Boundaries

The future implementation must preserve these invariants:

- `block` must never be approvable.
- Hard-blocked operations must not create approval requests.
- Approval requests must expire or be clearly scoped.
- Approval must not weaken path traversal checks.
- Approval must not expose raw secrets in logs.
- Approval must not allow arbitrary modified arguments.
- Approving a request must execute the same tool and arguments that were
  reviewed.
- Approval is local prototype control only, not production auth.
- Approval must not change MCP tool names or public tool semantics beyond the
  additional `approval_request_id` field.
- Approval must not allow reads of sensitive paths by converting them into
  approvable operations.
- Approval must not allow `list_directory` to become a control path for
  execution.

## Audit and Observability

Audit events should record:

- Approval request created.
- Approval approved.
- Approval rejected.
- Approved operation executed.
- Approved operation denied by re-scoring or boundary validation.

Audit requirements:

- Raw secrets must not be logged.
- `arguments_summary` must be masked.
- Stored output summaries must be masked.
- Audit events must clearly distinguish approval lifecycle events from normal
  tool execution events.
- `executed=True` must appear only when the underlying operation was actually
  attempted.
- Approval decision events should include the `request_id`, `tool_name`,
  `session_id`, decision status, risk score, and safe reasons.

## Expected Future Files

Future implementation may add or modify:

- `backend/app/approvals/models.py`
- `backend/app/approvals/store.py`
- `backend/tests/test_approval_workflow.py`
- `backend/app/tools/models.py`
- `backend/app/tools/safe_tools.py`

Optional later files, not required for Step 12 MVP:

- `backend/app/approvals/cli.py`
- Dashboard files for approval buttons or pending-request display.

No dashboard approval UI should be implemented as part of this Step 12 spec.

## Acceptance Criteria

- `write_file` requiring approval creates a pending request and does not write.
- `run_command` requiring approval creates a pending request and does not run.
- Rejecting a request prevents execution.
- Approving a request executes the originally approved `write_file`.
- Approving a request executes the originally approved `run_command` only if it
  remains safe under current policy.
- Approving a request re-runs `RiskScorer` before execution.
- Approving a request re-validates workspace boundaries before execution.
- Hard-blocked operations do not create approval requests.
- Modified arguments cannot be smuggled into approval.
- `approval_request_id` appears in `ToolExecutionResult` for supported
  `require_approval` calls.
- `approval_request_id` is absent or `None` for blocked calls and unsupported
  approval tools.
- Raw secrets are not stored in approval logs, approval audit events,
  execution audit events, CLI output, or dashboard-facing request summaries.
- Existing tests still pass.
- `pytest`, `ruff`, and `mypy` pass after implementation.

## Important Constraints

- Do not implement approval UI in Step 12.
- Do not change MCP tool names.
- Do not allow approval to override `block`.
- Do not claim production-grade authentication or authorization.
- Keep this as a local prototype workflow.
- Keep implementation changes focused on the approval workflow and its tests.
