# SentryGate

SentryGate is a local MCP security gateway prototype that masks secrets, scores
risk, audits tool calls, and blocks or requires approval for risky local
operations.

## What Problem It Solves

Coding agents can read files, write files, and run commands. That makes local
development workflows powerful, but it also creates sharp edges:

- Secrets from files or command output can be returned into an agent context.
- File writes can change a workspace before a human reviews the action.
- Dangerous commands can damage files or leak data.
- Tool activity can be hard to inspect after the fact.

SentryGate explores a local MCP boundary where file and command operations are
scored, masked, and audited before results are returned to an MCP-compatible
agent.

## Architecture

```text
Codex / MCP Agent -> SentryGate MCP Server -> SafeToolService -> RiskScorer + PrivacyMasker + AuditStore
```

The SentryGate MCP server exposes protected tools for file reads, file writes,
directory listings, and command requests. The MCP server is a thin adapter over
`SafeToolService`, which performs workspace checks, risk decisions, execution,
privacy masking, and audit logging.

`RiskScorer` classifies each request as `allow`, `block`, or
`require_approval`. `PrivacyMasker` replaces detected secrets with stable mask
tokens before output is returned. `AuditStore` records masked audit events for
local inspection.

## Important Boundary

SentryGate only protects tool calls routed through its MCP server.

It does not intercept Codex built-in internal tools.

SentryGate is not a full operating-system sandbox. Direct filesystem, shell, or
other internal Codex tools are outside SentryGate's enforcement boundary. For
protected workflows, configure the agent to call SentryGate tools such as
`sentry_read_file`, `sentry_write_file`, `sentry_list_directory`, and
`sentry_run_command`.

The configured workspace root is the filesystem boundary SentryGate enforces for
its own tools. Use the narrowest practical workspace root for the task.

## Current Features

- Privacy masking
- Risk scoring
- Safe tool wrappers
- In-memory audit logs
- MCP server integration

## Run Backend Checks

From the `backend` directory:

```powershell
uv run pytest
uv run ruff check .
uv run mypy app
```

## Run the MCP Server

The MCP server requires an explicit workspace root. It does not default to the
current working directory, repository root, or user home directory.

Using a CLI argument:

```powershell
cd backend
uv run python -m app.mcp.server --workspace-root C:\path\to\workspace
```

Using an environment variable:

```powershell
cd backend
$env:SENTRYGATE_WORKSPACE_ROOT = "C:\path\to\workspace"
uv run python -m app.mcp.server
```

## Codex MCP Configuration Notes

Configure Codex or another MCP-compatible agent to start the local SentryGate
MCP server from the `backend` directory. Pass an absolute workspace path with
either `--workspace-root` or `SENTRYGATE_WORKSPACE_ROOT`.

Example configuration shape:

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

Adapt this shape to your local Codex MCP configuration mechanism. SentryGate
protection applies only when the agent routes protected operations through the
SentryGate MCP tools.

## Local Demo

Run the local demo from the `backend` directory:

```powershell
uv run python scripts/demo_sentrygate.py
```

The demo creates a temporary workspace, uses `SafeToolService` directly, and
shows allow, block, and require-approval decisions without requiring Codex or a
running MCP server.

## Security Limitations

SentryGate is a local prototype, not a production-grade enterprise security
product.

- It protects only MCP calls routed through the SentryGate MCP server.
- It does not intercept Codex built-in internal tools.
- It is not a VM, container, kernel sandbox, EDR, or antivirus tool.
- In-memory audit logs are not durable and are lost when the process exits.
- Current approval behavior returns `require_approval`; there is no human
  approval UI or delayed execution workflow yet.
- Rule-based detection can miss novel command forms or secret formats.
- Broad workspace roots create broad access boundaries.
- Demo behavior with fake data is not proof of production-grade isolation.
