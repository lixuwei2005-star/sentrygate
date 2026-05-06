# Step 5.4 README and Local Demo Script Spec

## Goal

Define the project README and a deterministic local demo script for showing
SentryGate behavior.

This spec creation step defines the behavior only. Do not create or modify the
root `README.md`, backend code, tests, or scripts as part of this step.

## Scope

This step includes specifications for:

- A root `README.md` for the project.
- A local demo script at `backend/scripts/demo_sentrygate.py`.
- Expected README content, examples, and security boundary wording.
- Expected demo scenarios and output.
- Acceptance criteria for the future implementation.

Out of scope for this spec creation step:

- Creating or modifying `README.md`.
- Creating or modifying `backend/scripts/demo_sentrygate.py`.
- Backend code changes.
- MCP server behavior changes.
- Test, lint, or type-check code changes.

## README.md Requirements

The future implementation should create a root-level `README.md`.

The README should be concise, accurate, and explicit about SentryGate's
protection boundary.

### Project Name

The README must identify the project as:

```text
SentryGate
```

### One-line Description

The README should include a one-line description similar to:

```text
SentryGate is a local MCP security gateway that masks secrets, scores risk,
audits tool calls, and blocks or requires approval for risky local operations.
```

### Problem Statement

The README should explain that coding agents can read files, write files, and
run commands, which is powerful but risky.

The problem statement should cover:

- Secret leakage from files and command output.
- Accidental or unsafe file writes.
- Dangerous shell commands.
- The need for deterministic local policy before tool output reaches an agent.
- The need for auditability during protected workflows.

### Architecture Overview

The README must include this architecture chain:

```text
Codex / MCP Agent -> SentryGate MCP Server -> SafeToolService -> RiskScorer + PrivacyMasker + AuditStore
```

The overview should explain:

- Codex or another MCP-compatible agent calls the SentryGate MCP tools.
- The MCP server is a thin adapter over `SafeToolService`.
- `SafeToolService` owns workspace checks, execution decisions, masking, and
  audit logging.
- `RiskScorer` classifies each tool call as `allow`, `block`, or
  `require_approval`.
- `PrivacyMasker` masks secrets before output is returned.
- `AuditStore` records masked audit events.

### Important Boundary

The README must state this boundary clearly:

```text
SentryGate only protects tool calls routed through its MCP server.
It does not intercept Codex built-in internal tools.
```

The README should also explain:

- SentryGate is not a full operating-system sandbox.
- Direct filesystem, shell, or internal Codex tools are outside SentryGate's
  enforcement boundary.
- Protected workflows should call `sentry_read_file`, `sentry_write_file`,
  `sentry_list_directory`, and `sentry_run_command`.
- The configured workspace root is the filesystem boundary SentryGate enforces
  for its own tools.

### Current Features

The README should list current features:

- Privacy masking.
- Risk scoring.
- Safe tool wrappers.
- In-memory audit logs.
- MCP server integration.

### How to Run Backend Tests

The README should document running backend checks from the `backend` directory.

Required commands:

```powershell
cd backend
uv run pytest
uv run ruff check .
uv run mypy app
```

If the project also exposes combined check commands in the future, the README
may include them, but these direct commands should remain clear.

### How to Run the MCP Server

The README must show that the MCP server requires an explicit workspace root.

Example using a CLI argument:

```powershell
cd backend
uv run python -m app.mcp.server --workspace-root C:\path\to\workspace
```

Example using an environment variable:

```powershell
cd backend
$env:SENTRYGATE_WORKSPACE_ROOT = "C:\path\to\workspace"
uv run python -m app.mcp.server
```

The README must not imply that the MCP server defaults to the current working
directory, the repository root, or the user's home directory.

### Example Codex MCP Configuration Notes

The README should include configuration notes for connecting Codex to the local
SentryGate MCP server.

The notes should be written as guidance rather than promising one universal
configuration file format, because local Codex MCP configuration locations may
vary.

Required notes:

- Configure Codex to start the local SentryGate MCP server from the `backend`
  directory.
- Pass an explicit workspace root with either `--workspace-root` or
  `SENTRYGATE_WORKSPACE_ROOT`.
- Use an absolute workspace path.
- Route protected operations through SentryGate MCP tools.
- Keep in mind that Codex built-in internal tools remain outside SentryGate's
  boundary.

Illustrative configuration shape:

```json
{
  "mcpServers": {
    "sentrygate": {
      "command": "uv",
      "args": [
        "run",
        "python",
        "-m",
        "app.mcp.server",
        "--workspace-root",
        "C:\\path\\to\\workspace"
      ],
      "cwd": "C:\\path\\to\\sentrygate\\backend"
    }
  }
}
```

The README should label this as an example shape and tell users to adapt it to
their local Codex MCP configuration mechanism.

### Security Limitations

The README should include a security limitations section.

Required limitations:

- SentryGate protects only MCP calls routed through the SentryGate MCP server.
- SentryGate does not intercept Codex built-in internal tools.
- SentryGate is not a VM, container, kernel sandbox, EDR, or antivirus tool.
- In-memory audit logs are not durable and are lost when the process exits.
- The current approval behavior returns `require_approval`; it does not yet
  include a human approval UI or delayed execution workflow.
- Rule-based detection can miss novel command forms or secret formats.
- Users should configure the narrowest practical workspace root.
- Users should not rely on fake demo behavior as proof of production-grade
  isolation.

## Local Demo Script Requirements

The future implementation should create:

```text
backend/scripts/demo_sentrygate.py
```

The script should demonstrate SentryGate behavior by using `SafeToolService`
directly. It should not start the MCP server and should not require Codex.

The script must run from the `backend` directory with:

```powershell
uv run python scripts/demo_sentrygate.py
```

### Demo Design

The script must:

- Create a temporary demo workspace.
- Use `SafeToolService(workspace_root=temporary_workspace)`.
- Use only fake secrets.
- Never require real secrets.
- Never execute dangerous commands.
- Be deterministic and safe to run locally.
- Print clear scenario headings.
- Print each tool result in a readable structured format.
- Clearly show `allow`, `block`, and `require_approval` decisions.
- Print audit events at the end.
- Avoid printing raw secrets in tool output or audit output.

The script should use standard library temporary directory support, such as
`tempfile.TemporaryDirectory`.

### Demo Workspace

The temporary workspace should contain deterministic demo files such as:

```text
public_note.txt
.env
src/
src/app.py
```

Suggested fake content for `public_note.txt`:

```text
Demo note
Contact: demo@example.com
Fake API key: sk-demo1234567890abcdef1234567890abcdef1234567890
```

Suggested fake content for `.env`:

```text
OPENAI_API_KEY=sk-fakeenv1234567890abcdef1234567890abcdef123456
DATABASE_URL=postgres://demo:password@localhost:5432/sentrygate_demo
```

The exact fake secret values may differ, but they must be obviously fake and
must be detected by `PrivacyMasker`.

### Scenario 1: Safe read_file with Secret Masking

Call:

```python
service.sentry_read_file("public_note.txt")
```

Expected behavior:

- Decision: `allow`.
- The file is read.
- Output is masked.
- Raw fake secrets are not printed.
- Masked findings are visible in safe form.

The demo output should make clear that the secret was present in the source file
but masked in the result.

### Scenario 2: Blocked .env Read

Call:

```python
service.sentry_read_file(".env")
```

Expected behavior:

- Decision: `block`.
- `.env` content is not returned.
- Raw fake secrets are not printed.
- Output or error clearly indicates the operation was blocked.

### Scenario 3: write_file Requires Approval and Does Not Write

Call:

```python
service.sentry_write_file("generated.txt", "demo generated content")
```

Expected behavior:

- Decision: `require_approval`.
- The file is not written.
- The script verifies and prints that `generated.txt` does not exist.
- No submitted content is echoed unnecessarily.

### Scenario 4: list_directory Allowed

Call:

```python
service.sentry_list_directory(".")
```

Expected behavior:

- Decision: `allow`.
- Output includes a deterministic directory listing.
- The listing should show demo files and folders without exposing secret
  content.

### Scenario 5: Normal run_command Requires Approval and Does Not Execute

Call a normal, non-dangerous command that would be safe if executed, such as:

```python
service.sentry_run_command("echo sentrygate-demo-command")
```

Expected behavior:

- Decision: `require_approval`.
- The command is not executed.
- No command stdout from actual execution is printed.
- Output or error clearly indicates approval is required.

The demo should avoid commands whose behavior varies across platforms.

### Scenario 6: Dangerous run_command Blocked

Call a dangerous command string only as input to `SafeToolService`, never by
direct shell execution.

Suggested examples:

```python
service.sentry_run_command("rm -rf .")
```

or, on Windows-oriented demonstrations:

```python
service.sentry_run_command("Remove-Item -Recurse -Force .")
```

Expected behavior:

- Decision: `block`.
- The command is not executed.
- The output clearly shows the command was blocked.
- The script never invokes the command outside `SafeToolService`.

### Scenario 7: Audit Events Printed at the End

After all demo calls, print audit events from the in-memory audit store.

Expected behavior:

- The audit section appears at the end.
- One audit event is shown for each tool call that reached `SafeToolService`.
- Audit output includes decisions and reasons.
- Audit output does not expose raw fake secrets.
- The output remains deterministic enough for local demos and screenshots.

If the current audit store API exposes timestamps or generated IDs, the script
may print them, but the scenario ordering should remain clear.

### Output Formatting

The script should keep output readable for humans.

Recommended shape:

```text
SentryGate local demo
Workspace: <temporary path>

1. read_file masks secrets
decision: allow
ok: true
output:
...

2. .env read is blocked
decision: block
ok: false
error: operation_blocked

...

Audit events
...
```

The exact formatting may differ, but the output must clearly show:

- Which scenario is running.
- The decision for each scenario.
- Whether the operation succeeded.
- Why blocked or approval-required operations did not execute.
- That audit events were created.

### Demo Safety Requirements

- Do not read from the user's real workspace except through the temporary demo
  workspace.
- Do not use real API keys, tokens, database URLs, private keys, or credentials.
- Do not execute dangerous commands directly or indirectly.
- Do not write outside the temporary demo workspace.
- Do not depend on network access.
- Do not depend on external services.
- Do not require the MCP server to be running.
- Do not require Codex to be configured.
- Do not print raw secrets, even fake ones, in demo results or audit output.

## Expected Future Files

Future implementation should create or update:

```text
README.md
backend/scripts/demo_sentrygate.py
```

No other files should be modified unless tests or package configuration require
minimal supporting changes.

## Acceptance Criteria

Future implementation should satisfy:

- `README.md` exists at the repository root.
- README explains the project scope and protection boundary clearly.
- README includes project name `SentryGate`.
- README includes a one-line description.
- README explains the problem SentryGate solves.
- README includes the architecture overview:
  `Codex / MCP Agent -> SentryGate MCP Server -> SafeToolService -> RiskScorer + PrivacyMasker + AuditStore`.
- README clearly states that SentryGate only protects tool calls routed through
  its MCP server.
- README clearly states that SentryGate does not intercept Codex built-in
  internal tools.
- README lists current features: privacy masking, risk scoring, safe tool
  wrappers, in-memory audit logs, and MCP server integration.
- README documents backend test, lint, and type-check commands.
- README documents how to run the MCP server with an explicit workspace root.
- README includes example Codex MCP configuration notes.
- README includes security limitations.
- `backend/scripts/demo_sentrygate.py` exists.
- The demo runs with `uv run python scripts/demo_sentrygate.py` from the
  `backend` directory.
- The demo creates a temporary workspace.
- The demo uses `SafeToolService` directly.
- The demo shows a safe `read_file` with secret masking.
- The demo shows `.env` read blocked.
- The demo shows `write_file` returning `require_approval` and not writing.
- The demo shows `list_directory` allowed.
- The demo shows a normal `run_command` returning `require_approval` and not
  executing.
- The demo shows a dangerous `run_command` blocked.
- The demo prints audit events at the end.
- The demo never requires real secrets.
- The demo never executes dangerous commands.
- The demo uses fake secrets only.
- The demo output clearly shows `allow`, `block`, and `require_approval`.
- The demo output does not expose raw secrets.
- `uv run pytest` passes from `backend`.
- `uv run ruff check .` passes from `backend`.
- `uv run mypy app` passes from `backend`.
