# Step 4 Safe Tools and Audit Spec

## Goal

Define safe local tool wrappers and audit logging for SentryGate.

SentryGate should wrap risky local operations, score every request before
execution, mask outputs before returning them, and record an audit event for
every tool call.

This spec creation step defines the behavior only. Backend implementation is
deferred until the future Step 4 implementation.

## Scope

This step includes:

- Safe tool wrapper behavior.
- Audit event model.
- In-memory audit storage design.
- Integration points for `RiskScorer` and `PrivacyMasker`.
- Workspace boundary and command execution safety requirements.

Out of scope for this spec creation step:

- Backend code changes.

Expected for the future Step 4 implementation:

- Backend code changes for safe tool wrappers and audit logging.
- `InMemoryAuditStore` as the first audit storage implementation.

Out of scope for the future Step 4 implementation:

- MCP server integration.
- LM Studio integration.
- Frontend UI.
- Human approval UI or approval API.

## Safe Tool API

The future implementation should expose these Python functions:

```python
def sentry_read_file(path: str, session_id: str | None = None) -> ToolExecutionResult:
    ...


def sentry_write_file(
    path: str,
    content: str,
    session_id: str | None = None,
) -> ToolExecutionResult:
    ...


def sentry_list_directory(
    path: str,
    session_id: str | None = None,
) -> ToolExecutionResult:
    ...


def sentry_run_command(
    command: str,
    session_id: str | None = None,
) -> ToolExecutionResult:
    ...
```

These wrappers are the protected local operation boundary for Step 4. They are
not MCP tools yet.

## ToolExecutionResult

Each wrapper should return:

```python
class ToolExecutionResult(BaseModel):
    ok: bool
    decision: Literal["allow", "block", "require_approval"]
    risk_score: int
    reasons: list[str]
    output: str | None = None
    error: str | None = None
    masked_findings: list[object] | tuple[object, ...]
```

Required result behavior:

- `ok` should be `True` only when the operation executed successfully.
- `ok` should be `False` for blocked calls, calls requiring approval, and
  execution errors.
- `decision` must mirror the `RiskResult.decision`.
- `risk_score` must mirror the `RiskResult.risk_score`.
- `reasons` must include the deterministic risk reasons.
- `output` must contain masked output only.
- `error` must not contain raw secrets.
- `masked_findings` must contain safe masking findings only, never raw secret
  values.

## Execution Flow

Every safe tool wrapper must follow this order:

1. Build a `ToolCall` for the requested operation.
2. Call `RiskScorer` before executing the operation.
3. If the decision is `block`, do not execute the operation.
4. If the decision is `require_approval`, do not execute by default.
5. If the decision is `allow`, execute the operation.
6. Pass any output or error text through `PrivacyMasker`.
7. Write an audit event for the tool call.
8. Return a `ToolExecutionResult`.

The audit event should be written for all outcomes:

- Allowed and executed.
- Blocked before execution.
- Requires approval and not executed.
- Allowed but failed during execution.

## Decision Behavior

### Block

If `RiskResult.decision == "block"`:

- The underlying operation must not execute.
- The result should have `ok=False`.
- The result should have `decision="block"`.
- The result should include the risk score and reasons.
- The result should include a safe, masked error such as `operation_blocked`.
- An audit event must be written with `executed=False`.

### Require Approval

If `RiskResult.decision == "require_approval"`:

- The underlying operation must not execute by default.
- The result should have `ok=False`.
- The result should have `decision="require_approval"`.
- The result should include the risk score and reasons.
- The result should include a safe, masked error such as
  `operation_requires_approval`.
- An audit event must be written with `executed=False`.

This is the complete MVP behavior. No approval UI, approval API, approval token,
or delayed execution workflow should be implemented in Step 4.

### Allow

If `RiskResult.decision == "allow"`:

- The underlying operation should execute.
- Successful execution should return `ok=True`.
- Failed execution should return `ok=False` with a masked safe error.
- Output must be masked before returning.
- An audit event must be written with `executed=True` when the operation was
  attempted.

## Workspace Boundary

All file and directory operations must stay inside the configured workspace
root.

Required behavior:

- Resolve the workspace root to an absolute canonical path.
- Resolve requested paths against the workspace root.
- Normalize `.` and `..` segments.
- Resolve symlinks where the platform supports it.
- Block any resolved target outside the resolved workspace root.

The same workspace boundary rule applies to:

- `sentry_read_file`
- `sentry_write_file`
- `sentry_list_directory`
- `sentry_run_command` working directory

Path escape attempts must not execute and must write an audit event.

Examples that must block:

- `../secret.txt`
- `../../.env`
- absolute paths outside the workspace root
- symlinks that resolve outside the workspace root

## File Tool Behavior

### sentry_read_file

Required behavior:

- Build a `ToolCall` with `tool_name="read_file"`.
- Score the call before reading.
- Do not read if the decision is `block` or `require_approval`.
- Read text content only after an `allow` decision.
- Mask file content before returning it.
- Store only masked content or summaries in audit logs.

Binary files may be rejected for MVP with a safe error such as
`binary_file_not_supported`.

### sentry_write_file

Required behavior:

- Build a `ToolCall` with `tool_name="write_file"`.
- Score the call before writing.
- Do not write if the decision is `block` or `require_approval`.
- Write only after an `allow` decision.
- Mask the input content for audit summaries before logging.
- Return a short masked success message after writing.

Default MVP policy is expected to make normal writes require approval. Since no
approval flow exists yet, normal writes should usually not execute in Step 4.

### sentry_list_directory

Required behavior:

- Build a `ToolCall` with `tool_name="list_directory"`.
- Score the call before listing.
- Do not list if the decision is `block` or `require_approval`.
- Return a deterministic directory listing after an `allow` decision.
- Mask the listing before returning it.

Directory listings should be stable for tests. Recommended MVP formatting is
one entry per line, sorted by name, with a simple type prefix:

```text
[dir] backend
[dir] docs
[file] README.md
```

### sentry_run_command

Required behavior:

- Build a `ToolCall` with `tool_name="run_command"`.
- Score the call before execution.
- Do not execute if the decision is `block` or `require_approval`.
- Execute only after an `allow` decision.
- Execute inside the configured workspace root.
- Use a timeout.
- Do not use `shell=True` for MVP.
- Mask stdout and stderr before returning.
- Store only masked output summaries in audit logs.

For MVP, normal commands should usually return `require_approval` by default and
should not execute. Dangerous commands should be blocked and should not execute.

If command execution is allowed in a future policy, implementation should parse
the command into an argument list before calling subprocess APIs. It should not
delegate interpretation to a shell.

## Privacy Masker Integration

All potentially user-controlled or operation-derived strings must pass through
`PrivacyMasker` before being returned or persisted to audit logs.

Strings that should be masked include:

- File contents returned by `sentry_read_file`.
- File content supplied to `sentry_write_file` before audit summarization.
- Directory listings.
- Command stdout.
- Command stderr.
- Error messages.
- Argument summaries.
- Output summaries.

Raw-to-token mappings must remain in memory only and must not be written to
audit logs by default.

`masked_findings` should include safe metadata about detected secrets, such as
secret type, token, and count. It must not include raw secret values.

## Audit Event Model

Every safe tool call must create one audit event:

```python
class AuditEvent(BaseModel):
    event_id: str
    timestamp: datetime
    session_id: str | None
    tool_name: str
    decision: Literal["allow", "block", "require_approval"]
    risk_score: int
    reasons: list[str]
    arguments_summary: str
    output_summary: str | None
    masked_findings: list[object] | tuple[object, ...]
    executed: bool
```

Field requirements:

- `event_id` should be unique. A UUID string is acceptable for MVP.
- `timestamp` should be timezone-aware UTC.
- `session_id` should mirror the tool call session.
- `tool_name` should be the unprefixed policy name, such as `read_file`.
- `decision`, `risk_score`, and `reasons` should mirror the risk result.
- `arguments_summary` must be masked and safe to log.
- `output_summary` must be masked and safe to log.
- `masked_findings` must not contain raw secrets.
- `executed` should be `True` only when the underlying operation was attempted.

Audit events must never include raw file contents, raw command output, raw
secrets, or raw secret mappings by default.

## Audit Storage Design

The Step 4 implementation should use `InMemoryAuditStore` first. SQLite audit
storage is deferred to a later step.

The implementation should still hide the storage backend behind a small store
interface so it can be swapped later.

Recommended interface:

```python
class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> None:
        ...

    def list_events(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        ...
```

### In-Memory Store

`InMemoryAuditStore` is the required first implementation for Step 4:

- Keep events in process memory.
- Preserve append order.
- Support filtering by `session_id`.
- Support a `limit`.
- Reset on process restart.

### SQLite Store

SQLite audit storage is deferred to a later step. When implemented later, it
should follow these constraints:

- Store audit events in a single `audit_events` table.
- Store structured fields such as `reasons` and `masked_findings` as JSON.
- Store only masked summaries.
- Do not store raw secret mappings.
- Use deterministic ordering by timestamp or insertion order.

## Arguments and Output Summaries

Audit logs should store summaries, not full raw payloads.

Recommended argument summaries:

- `read_file`: masked resolved-relative path.
- `write_file`: masked resolved-relative path plus masked content length.
- `list_directory`: masked resolved-relative path.
- `run_command`: masked command text after risk evaluation.

Recommended output summaries:

- `read_file`: masked content preview and character count.
- `write_file`: masked success or failure message.
- `list_directory`: masked listing preview and entry count.
- `run_command`: masked stdout and stderr previews plus exit code.

Summaries should be bounded in length to prevent large audit records. A
reasonable MVP limit is 2,000 characters per summary.

## Likely Future Implementation Files

Expected implementation files for a later step:

```text
backend/app/audit/models.py
backend/app/audit/store.py
backend/app/tools/models.py
backend/app/tools/safe_tools.py
backend/tests/test_safe_tools.py
```

These files should not be created or modified as part of Step 4 spec creation.

## Acceptance Criteria

Future implementation should satisfy:

- Blocked `read_file` for `.env` does not read the file and writes an audit
  event.
- `require_approval` `write_file` does not write by default and writes an audit
  event.
- Allowed `read_file` returns masked content.
- Allowed `list_directory` returns a directory listing.
- Normal `run_command` returns `require_approval` by default and does not
  execute.
- Dangerous `run_command` is blocked and does not execute.
- Audit events contain masked data only.
- Raw secrets are not written to audit logs.
- Paths outside the workspace are blocked.
- `pytest` passes.
- `ruff` passes.
- `mypy` passes.
