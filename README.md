# SentryGate

SentryGate is a local MCP security gateway prototype for selected tool calls.
It demonstrates deterministic risk scoring, privacy masking, approval gating,
hard blocking, and masked audit events for operations routed through its own MCP
server.

<p align="center">
  <a href="README.zh-CN.md">
    <img src="https://img.shields.io/badge/中文文档-README.zh--CN-blue" alt="中文文档">
  </a>
</p>

## Quick Demo

Run the local demo from the `backend` directory:

```powershell
cd backend
uv run python scripts/demo_sentrygate.py
```

The demo creates a temporary workspace, uses fake secrets only, and calls
`SafeToolService` directly. It does not require Codex or a running MCP client.
It shows:

- Safe file reads with masked secrets.
- Sensitive `.env` reads blocked.
- Writes held at `require_approval`.
- Directory listings allowed inside the demo workspace.
- Normal commands held at `require_approval`.
- Dangerous command patterns blocked.
- Masked audit events printed at the end.

See [docs/demo-output.md](docs/demo-output.md) for sample output and scenario
notes.

## What I Built

I built a local MCP security gateway prototype that sits between an
MCP-compatible coding agent and selected local tools.

Current implemented pieces:

- An MCP server exposing SentryGate tools for file reads, file writes,
  directory listings, and command requests.
- `SafeToolService`, a central wrapper that performs workspace checks, risk
  decisions, execution decisions, privacy masking, and audit logging.
- Rule-based risk scoring with `allow`, `block`, and `require_approval`
  decisions.
- Privacy masking before tool output is returned.
- In-memory audit events with masked summaries.
- Optional local LM Studio semantic review for eligible medium-risk calls,
  disabled unless configured and unable to override deterministic hard blocks.

This project is designed as an internship portfolio project and local prototype,
not as a production security product.

## What It Protects

SentryGate protects tool calls routed through the SentryGate MCP server.

Protected workflows should use:

- `sentry_read_file`
- `sentry_write_file`
- `sentry_list_directory`
- `sentry_run_command`

For those SentryGate-routed calls, the configured workspace root is the
filesystem boundary. SentryGate can score requests, block sensitive operations,
hold approval-required operations without executing them, mask detected secrets
before returning output, and record masked audit events for local inspection.

## What It Does Not Protect

SentryGate does not intercept or control Codex built-in internal tools.

It also does not protect:

- Direct shell access outside SentryGate tools.
- Direct filesystem access outside SentryGate tools.
- Operations routed through other MCP servers.
- The operating system as a full sandbox.
- Container, VM, kernel, EDR, antivirus, or cloud security boundaries.
- Production approval workflows.
- Durable enterprise audit governance.
- Every possible secret format or risky command form.

Broad workspace roots create broad access boundaries. Use the narrowest
practical workspace root for protected demos or experiments.

## Current Architecture

```text
Codex / MCP Agent -> SentryGate MCP Server -> SafeToolService -> RiskScorer + PrivacyMasker + AuditStore
```

The SentryGate MCP server is a thin adapter over `SafeToolService`.
`SafeToolService` owns workspace checks, risk decisions, execution decisions,
privacy masking, and audit logging for SentryGate tools.

`RiskScorer` classifies each request as `allow`, `block`, or
`require_approval`. `PrivacyMasker` replaces detected secrets with stable mask
tokens before output is returned. `AuditStore` records masked audit events for
local inspection.

When LM Studio review is enabled, it is an optional local semantic review layer
for eligible medium-risk calls:

```text
RiskScorer -> optional LM Studio review for medium-risk calls -> conservative merge
```

Deterministic rules run first. LM Studio cannot reduce risk, cannot turn
`require_approval` into `allow`, and cannot override a deterministic hard block.

## Run Backend Checks

From the `backend` directory:

```powershell
cd backend
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

## Roadmap

Possible future work:

- Durable audit storage.
- Human approval UI or approval API.
- Richer policy configuration.
- More robust command parsing coverage.
- Frontend audit dashboard.
- More complete integration examples for MCP clients.
- Optional deployment hardening experiments.

These are roadmap ideas, not claims about the current prototype.

## Security Limitations

SentryGate is a local prototype, not a production-grade security product.

- It protects only MCP calls routed through the SentryGate MCP server.
- It does not intercept Codex built-in internal tools.
- It is not a VM, container, kernel sandbox, EDR, or antivirus tool.
- In-memory audit logs are not durable and are lost when the process exits.
- Current approval behavior returns `require_approval`; there is no human
  approval UI or delayed execution workflow yet.
- Rule-based detection can miss novel command forms or secret formats.
- Demo behavior with fake data is not proof of production-grade isolation.
