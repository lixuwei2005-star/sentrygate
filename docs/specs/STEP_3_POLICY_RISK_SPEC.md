# Step 3 Policy Risk Spec

## Goal

Define a deterministic rule-based policy and risk scoring engine for SentryGate
tool calls.

This step defines the behavior only. Backend implementation is deferred.

## Scope

This step includes only the policy and risk scoring specification.

Out of scope for Step 3:

- LLM usage.
- LM Studio integration.
- MCP integration.
- Audit database or audit persistence.
- Frontend UI.
- Tool execution.
- Approval UI or approval API.
- Backend code changes.

## Input and Output Models

### ToolCall

The risk engine should accept a tool call model with these fields:

```python
class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, object]
    session_id: str | None = None
```

Supported MVP tool names:

- `read_file`
- `write_file`
- `list_directory`
- `run_command`

Unknown tool names should default to a conservative decision because they are
not covered by policy:

- `risk_score`: `80`
- `decision`: `block`
- `reason`: `unknown_tool_not_covered_by_policy`

### RiskResult

The risk engine should return:

```python
class RiskResult(BaseModel):
    risk_score: int
    decision: Literal["allow", "block", "require_approval"]
    reasons: list[str]
```

`risk_score` must be clamped to the inclusive range `0` to `100`.

`reasons` should contain deterministic, human-readable explanations for the
score and decision.

## Decision Thresholds

The final decision is derived from the final risk score:

| Risk score | Decision |
| --- | --- |
| `0-39` | `allow` |
| `40-74` | `require_approval` |
| `75-100` | `block` |

If a hard-block rule applies, the engine should return `block` even if the
numeric score would otherwise be lower. Hard-block scores should normally be
set to `100`.

For Step 3, `require_approval` only means the risk engine returns that decision.
No approval UI, approval API, or approval workflow should be implemented yet.

## Workspace Boundary

The future implementation must prevent path traversal and workspace escape.

For file and directory tools, path arguments should be resolved against a
configured workspace root before scoring:

- Normalize the input path.
- Resolve `.` and `..` segments.
- Resolve symlinks where the platform supports it.
- Compare the resolved target path against the resolved workspace root.

Any resolved path outside the configured workspace root must be blocked.

Examples that should block:

- `../secret.txt`
- `../../.env`
- absolute paths outside the workspace root
- paths that escape through symlinks

## File Path Risk Rules

File path scoring applies to `read_file`, `write_file`, and `list_directory`.

Low-risk examples:

- `README.md`
- normal source files under `src/`
- normal documentation files under `docs/`

Sensitive paths and extensions should block or heavily score:

- `.env`
- `.env.local`
- `id_rsa`
- `id_ed25519`
- `secrets.json`
- `.aws/credentials`
- files ending in `.pem`
- files ending in `.key`
- files ending in `.p12`

Recommended MVP behavior:

- Reading normal workspace files: low score, usually `allow`.
- Listing normal workspace directories: low score, usually `allow`.
- Writing normal workspace files: medium score, usually `require_approval`.
- Accessing sensitive file paths: block with a high score.
- Any path outside the workspace root: block with score `100`.

The engine should match sensitive paths by normalized path components and file
names, not only by raw input strings.

## Command Risk Rules

Command scoring applies to `run_command`.

The future implementation should not rely only on simple substring matching.
For MVP, command parsing should be safe and deterministic:

- Use `shlex` for POSIX-style command tokenization where appropriate.
- Use simple PowerShell-aware detection for command names, flags, aliases,
  pipelines, and case-insensitive command text.
- Treat parse failures conservatively by increasing risk or requiring approval.

### Linux and macOS Risk Patterns

The following command patterns should block or heavily score:

- `rm -rf`
- `curl | bash`
- `wget | bash`
- `sudo`
- `chmod 777`
- `dd if=`
- `mkfs`

Detection should consider token structure, pipelines, command names, and
arguments. For example, `rm -rf target`, `rm -fr target`, and `rm --recursive
--force target` should be treated as the same destructive intent.

### Windows PowerShell Risk Patterns

The following PowerShell command patterns should block or heavily score:

- `Remove-Item -Recurse -Force`
- `Invoke-WebRequest | iex`
- `iwr | iex`
- `Start-Process`
- `Format-Volume`
- `Set-ExecutionPolicy Bypass`

PowerShell detection should be case-insensitive and should recognize common
aliases such as `iwr` for `Invoke-WebRequest` and `iex` for
`Invoke-Expression`.

## Rate Limit and Behavior Rules

For MVP, the engine should include a simple in-memory session behavior tracker.

The tracker should be deterministic and process-local:

- Key behavior counters by `session_id` when present.
- Use a default anonymous bucket when `session_id` is `None`.
- Track recent tool calls in short fixed windows.
- Reset state on process restart.

Required behavior rules:

- Many `read_file` calls in a short window should increase risk.
- Excessive `run_command` calls in a short window should increase risk.

Recommended MVP thresholds:

- More than 20 `read_file` calls in 60 seconds: add enough risk to make future
  reads require approval.
- More than 10 `run_command` calls in 60 seconds: add enough risk to make future
  commands require approval or block if combined with other risks.

The behavior tracker should add reasons such as:

- `many_recent_read_file_calls`
- `excessive_recent_run_command_calls`

## Files Likely to Be Implemented Later

Expected implementation files for a later step:

```text
backend/app/risk/models.py
backend/app/risk/policy.py
backend/app/risk/scorer.py
backend/tests/test_risk_scorer.py
```

These files should not be created or modified as part of Step 3 spec creation.

## Acceptance Criteria

Future implementation should satisfy:

- Unit tests cover safe `read_file`.
- Unit tests cover blocked sensitive path.
- Unit tests cover path traversal outside the workspace.
- Unit tests cover dangerous Linux/macOS commands.
- Unit tests cover dangerous PowerShell commands.
- Unit tests cover `require_approval` for medium-risk operations.
- Unit tests cover repeated `read_file` behavior risk.
- `pytest` passes.
- `ruff` passes.
- `mypy` passes.
