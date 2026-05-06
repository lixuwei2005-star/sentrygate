# Step 5 MCP Server Integration Spec

## Goal

Define how SentryGate exposes `SafeToolService` as an MCP server for Codex.

The MCP server is the protected tool boundary for Codex workflows that choose
to route file and command operations through SentryGate. Every MCP tool call
must delegate to `SafeToolService`, return structured results, and preserve the
workspace, risk, masking, and audit behavior defined in earlier steps.

This spec creation step defines the behavior only. Backend implementation is
deferred until the future Step 5 implementation.

## Scope

This step includes:

- MCP server design.
- MCP tool definitions.
- Mapping MCP tool calls to `SafeToolService` methods.
- Workspace configuration requirements.
- MCP error handling.
- Local Codex configuration notes for future README content.

Out of scope for this spec creation step:

- Backend code changes.
- LM Studio integration.
- Frontend UI.
- SQLite audit storage.
- Human approval UI or approval API.

Out of scope for the future Step 5 implementation:

- LM Studio review.
- Frontend integration.
- SQLite audit persistence.
- Approval UI, approval API, approval tokens, or delayed execution workflows.

## Boundary Statement

SentryGate only protects tool calls routed through its MCP server.

It does not intercept, sandbox, or control Codex built-in internal tools. If
Codex uses direct filesystem, shell, or other internal tools, those operations
are outside SentryGate's enforcement boundary.

README-oriented wording for later use:

> SentryGate protects the MCP tools it exposes. Configure Codex to use
> SentryGate tools for protected workflows. SentryGate does not intercept Codex
> built-in internal tools or provide a full operating-system sandbox.

## MCP Server Design

The future implementation should expose an MCP server that registers exactly
these tools:

- `sentry_read_file(path: str)`
- `sentry_write_file(path: str, content: str)`
- `sentry_list_directory(path: str)`
- `sentry_run_command(command: str)`

The server should be implemented as a thin adapter over `SafeToolService`.

Required design:

- Require an explicit workspace root at startup.
- Never default the workspace root to `Path.cwd()`.
- Resolve and validate the explicit workspace root before registering tools.
- Create one `SafeToolService(workspace_root=...)` instance during startup.
- Delegate every MCP tool call to that `SafeToolService` instance.
- Return `ToolExecutionResult`-style structured data for every tool response.
- Keep audit logs in memory for this step, as defined by Step 4.
- Return masked content and masked errors only.
- Never return raw secrets, raw secret mappings, or unmasked audit details.

The MCP server should not duplicate policy, risk scoring, masking, workspace
boundary logic, command execution logic, or audit logging. Those behaviors
belong in `SafeToolService` and its dependencies.

Implementation should follow the installed MCP Python SDK version. If SDK APIs
differ from examples, preserve the same external behavior:

- Same tool names.
- Same input arguments.
- Same `ToolExecutionResult`-style responses.
- Direct delegation to `SafeToolService`.
- No duplicated risk, masking, audit, or execution logic.

## Workspace Configuration

The MCP server must require an explicit workspace root.

Supported configuration sources:

- CLI argument, such as `--workspace-root`.
- Environment variable `SENTRYGATE_WORKSPACE_ROOT`.

Recommended precedence:

1. CLI argument.
2. `SENTRYGATE_WORKSPACE_ROOT`.

If no workspace root is supplied, the server must fail fast with a clear error.

Required missing-root behavior:

- Do not start the MCP server.
- Do not register MCP tools.
- Do not create `SafeToolService`.
- Emit a clear startup error such as
  `SENTRYGATE_WORKSPACE_ROOT or --workspace-root is required`.
- Exit with a non-zero status for CLI startup.

The server must not use any implicit fallback such as:

- `Path.cwd()`
- The repository root.
- The user's home directory.
- The directory containing `server.py`.

The resolved workspace root should be passed directly to:

```python
SafeToolService(workspace_root=resolved_workspace_root)
```

`SafeToolService` remains responsible for enforcing per-call path boundaries.

## MCP Tool Definitions

### sentry_read_file

Signature:

```python
def sentry_read_file(path: str) -> dict:
    ...
```

Required behavior:

- Validate only MCP-level argument shape before delegation.
- Delegate to `SafeToolService.sentry_read_file(path=path)`.
- Return the resulting `ToolExecutionResult` as structured MCP content.
- Safe files should return masked content when allowed.
- Blocked files such as `.env` should return a structured `block` result.
- Raw file content must not be returned if it contains secrets.

### sentry_write_file

Signature:

```python
def sentry_write_file(path: str, content: str) -> dict:
    ...
```

Required behavior:

- Validate only MCP-level argument shape before delegation.
- Delegate to
  `SafeToolService.sentry_write_file(path=path, content=content)`.
- Return the resulting `ToolExecutionResult` as structured MCP content.
- By default, normal writes are expected to return `require_approval`.
- A `require_approval` result must not write the file.
- Raw submitted content must not be returned or logged.

### sentry_list_directory

Signature:

```python
def sentry_list_directory(path: str) -> dict:
    ...
```

Required behavior:

- Validate only MCP-level argument shape before delegation.
- Delegate to `SafeToolService.sentry_list_directory(path=path)`.
- Return the resulting `ToolExecutionResult` as structured MCP content.
- Allowed directory listings should be deterministic.
- Recommended listing format remains one sorted entry per line:

```text
[dir] backend
[dir] docs
[file] README.md
```

### sentry_run_command

Signature:

```python
def sentry_run_command(command: str) -> dict:
    ...
```

Required behavior:

- Validate only MCP-level argument shape before delegation.
- Delegate to `SafeToolService.sentry_run_command(command=command)`.
- Return the resulting `ToolExecutionResult` as structured MCP content.
- Normal commands are expected to return `require_approval` by default.
- No command should execute unless `SafeToolService` returns `allow`.
- Dangerous commands should return `block`.
- Command stdout, stderr, and errors must be masked before returning.

## Mapping to SafeToolService

The MCP layer should be a direct adapter:

```text
MCP sentry_read_file(path)
  -> SafeToolService.sentry_read_file(path=path)

MCP sentry_write_file(path, content)
  -> SafeToolService.sentry_write_file(path=path, content=content)

MCP sentry_list_directory(path)
  -> SafeToolService.sentry_list_directory(path=path)

MCP sentry_run_command(command)
  -> SafeToolService.sentry_run_command(command=command)
```

The MCP layer must not bypass `SafeToolService` for any operation.

The MCP layer must not:

- Read files directly.
- Write files directly.
- List directories directly.
- Execute commands directly.
- Reimplement risk scoring.
- Reimplement privacy masking.
- Reimplement audit logging.
- Convert `require_approval` into execution.

No command or file mutation should happen from MCP unless
`SafeToolService` has returned an `allow` decision and performed the operation
itself.

## MCP Response Shape

MCP responses should return `ToolExecutionResult`-style structured data.

Recommended response dictionary:

```python
{
    "ok": bool,
    "decision": "allow" | "block" | "require_approval",
    "risk_score": int,
    "reasons": list[str],
    "output": str | None,
    "error": str | None,
    "masked_findings": list[object],
}
```

Required response behavior:

- Preserve the `ToolExecutionResult` fields returned by `SafeToolService`.
- Preserve `decision` exactly.
- Preserve `risk_score` and deterministic `reasons`.
- Return `output` only after masking.
- Return `error` only after masking.
- Return `masked_findings` without raw secret values.
- Never include raw secret mappings.
- Never include additional debug fields containing raw paths, raw command
  output, raw content, environment variables, or tracebacks.

`block` results must be clear to Codex:

```python
{
    "ok": False,
    "decision": "block",
    "error": "operation_blocked",
    ...
}
```

`require_approval` results must be clear to Codex:

```python
{
    "ok": False,
    "decision": "require_approval",
    "error": "operation_requires_approval",
    ...
}
```

Since Step 5 has no approval UI or API, `require_approval` is terminal for the
MCP call and must not cause execution.

## Error Handling

Startup errors:

- Missing workspace root should fail fast with a clear message.
- Invalid or inaccessible workspace root should fail fast with a clear message.
- Startup errors should not expose environment variables or secrets.

Tool argument errors:

- Missing required arguments should return a structured MCP validation error.
- Invalid argument types should return a structured MCP validation error.
- Validation errors should not call `SafeToolService`.

Service errors:

- Expected policy outcomes should be returned as normal structured results,
  not transport-level failures.
- `block` is a successful MCP response carrying `decision="block"`.
- `require_approval` is a successful MCP response carrying
  `decision="require_approval"`.
- Unexpected exceptions should return a safe masked error.
- Unexpected exceptions should not include raw tracebacks in MCP responses.

Audit behavior:

- Audit logs remain in memory for Step 5.
- All calls that reach `SafeToolService` should be audited by
  `SafeToolService`.
- MCP validation failures that do not reach `SafeToolService` do not need audit
  events in Step 5.

## Local Codex Configuration Notes

These notes are for a future README section only. Do not create the README as
part of this spec step.

Codex should be configured to start the local SentryGate MCP server with an
explicit workspace root. The workspace root can be supplied by environment
variable:

```text
SENTRYGATE_WORKSPACE_ROOT=/absolute/path/to/workspace
```

Or by CLI argument:

```text
--workspace-root /absolute/path/to/workspace
```

Future README content should make clear that:

- Codex must call `sentry_read_file`, `sentry_write_file`,
  `sentry_list_directory`, and `sentry_run_command` to receive SentryGate
  protection.
- Built-in Codex tools remain outside SentryGate's control.
- The configured workspace root is the only filesystem boundary SentryGate
  protects.
- The MCP server should be launched locally for the target workspace.
- The MCP server should not be configured with a broad root such as the user's
  home directory unless the user intentionally wants that broad boundary.

## Security Requirements

- The MCP server must require an explicit workspace root.
- The MCP server must not default to `Path.cwd()`.
- Every MCP tool call must delegate to `SafeToolService`.
- Raw secrets must not be returned through MCP responses.
- Raw secret mappings must not be returned through MCP responses.
- Blocked operations must not execute.
- Operations requiring approval must not execute.
- No command should execute unless `SafeToolService` returns `allow`.
- File writes should not occur unless `SafeToolService` returns `allow`.
- Directory and file reads should not occur unless `SafeToolService` returns
  `allow`.
- Audit logs remain in memory for this step.

## Likely Future Implementation Files

Expected implementation files for a later step:

```text
backend/app/mcp/server.py
backend/tests/test_mcp_server.py
```

These files should not be created or modified as part of Step 5 spec creation.

## Acceptance Criteria

Future implementation should satisfy:

- MCP server refuses to start without an explicit workspace root.
- MCP server does not default to `Path.cwd()`.
- MCP server creates `SafeToolService(workspace_root=...)`.
- `sentry_read_file` via MCP returns masked content for a safe file.
- `sentry_read_file` for `.env` via MCP returns `block`.
- `sentry_write_file` via MCP returns `require_approval` by default.
- `sentry_write_file` does not write when approval is required.
- `sentry_list_directory` via MCP returns a deterministic listing.
- `sentry_run_command` for a normal command returns `require_approval` by
  default and does not execute.
- Dangerous `sentry_run_command` calls return `block` and do not execute.
- MCP results contain no raw secrets.
- MCP validation failures are clear and safe.
- Audit logs remain in memory.
- `pytest` passes.
- `ruff` passes.
- `mypy` passes.
