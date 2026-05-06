# SentryGate Project Spec

## 1. Project Name

SentryGate

## 2. One-line Description

SentryGate is a local security gateway for Codex-style MCP coding agents. It audits, masks, scores, blocks, or approves risky MCP tool calls before they reach the local workspace.

## 3. Problem

AI coding agents such as Codex can read files, write files, and run commands. This is powerful, but risky.

Main risks:

- Sensitive file leakage, such as `.env`, private keys, database URLs, API keys, and tokens.
- Dangerous shell command execution, such as `rm -rf`, `curl | bash`, `sudo`, or destructive disk commands.
- Bulk file reading that may indicate data exfiltration.
- Tool output containing secrets being returned directly to the LLM context.

## 4. Core Boundary

SentryGate only protects MCP tools that are exposed through SentryGate.

It cannot intercept, sandbox, or fully control Codex built-in internal tools. For protected workflows, Codex should be configured to use SentryGate MCP tools such as `sentry_read_file`, `sentry_write_file`, `sentry_list_directory`, and `sentry_run_command` instead of direct high-risk tools.

README-oriented wording for later use:

> SentryGate is a local MCP security gateway. It protects the tools it exposes, audits their behavior, and masks sensitive data before returning results to the agent. It is not a full operating-system sandbox and does not control Codex built-in internal tools.

Future architecture notes:

- Show Codex connecting to SentryGate as an MCP server.
- Show SentryGate wrapping local file and command operations.
- Show that built-in Codex tools remain outside SentryGate's enforcement boundary.
- Make the trust boundary explicit in architecture diagrams and demos.

## 5. Goal

Build a local security gateway that exposes safe MCP tools to Codex:

- `sentry_read_file`
- `sentry_write_file`
- `sentry_list_directory`
- `sentry_run_command`

Every SentryGate MCP tool call must go through:

1. Workspace boundary check
2. Policy check
3. Risk scoring
4. Optional local LM Studio review for medium-risk calls
5. Allow / block / require approval decision
6. Execution if allowed
7. Privacy masking before returning output
8. Audit logging

## 6. Non-goals for MVP

The first usable version will NOT include:

- Enterprise multi-tenant user system
- Cloud deployment
- Fine-tuned security model
- Full OS-level sandbox
- Full control over Codex built-in internal tools
- Complex role-based access control
- Human approval UI or approval API

## 7. Tech Stack

Backend:

- Python 3.11
- FastAPI
- Pydantic
- SQLite
- pytest
- uv
- httpx

MCP:

- Python MCP SDK

Local model review:

- LM Studio OpenAI-compatible API
- Small local model preferred
- Gemma 26B should not be used for real-time blocking by default

Frontend:

- React
- Tailwind CSS
- Recharts

## 8. MVP Features

### 8.1 Backend

The backend must provide:

- `GET /health`
- policy engine
- privacy masking engine
- risk scoring engine
- audit log storage
- safe tool wrappers
- optional LM Studio review client

### 8.2 MCP Server

The MCP server must expose:

- `sentry_read_file(path: str)`
- `sentry_write_file(path: str, content: str)`
- `sentry_list_directory(path: str)`
- `sentry_run_command(command: str)`

### 8.3 Privacy Masking

The system should detect and mask:

- Emails
- OpenAI-style API keys
- GitHub tokens
- JWT-like tokens
- Database URLs
- Private key blocks
- `.env`-style secrets

Privacy masking requirements:

- Use stable tokenization.
- The same secret should map to the same token during a session.
- Audit logs should store masked content by default.
- Raw secrets should not be written to logs.

### 8.4 Risk Scoring

The system should classify requests as:

- `allow`
- `block`
- `require_approval`

Risk score range:

- `0-39`: allow
- `40-74`: require approval or LM Studio review
- `75-100`: block

Risk detection must not rely only on simple substring checks for dangerous commands. It should account for shell syntax, command arguments, chaining, aliases, and platform-specific behavior where practical.

The risk engine should cover Linux/macOS shell risks and Windows PowerShell risks, including examples such as:

- `rm -rf`
- `curl | bash`
- `wget | bash`
- `sudo`
- `chmod 777`
- `dd if=`
- `Remove-Item -Recurse -Force`
- `Invoke-WebRequest | iex`
- `Start-Process`
- `Format-Volume`

### 8.5 Require Approval Behavior

For MVP, SentryGate MCP tools can return a `require_approval` decision and write an audit log entry. The tool should not execute the underlying operation while approval is required.

Actual human approval UI/API can be implemented later.

### 8.6 Blocked by Default

The system should block or heavily restrict:

- `.env`
- `.env.local`
- `id_rsa`
- `id_ed25519`
- `secrets.json`
- `.aws/credentials`
- `.pem`
- `.key`
- `rm -rf`
- `curl | bash`
- `wget | bash`
- `sudo`
- `chmod 777`
- `mkfs`
- `dd if=`
- `Remove-Item -Recurse -Force`
- `Invoke-WebRequest | iex`
- `Start-Process`
- `Format-Volume`

## 9. Security Principles

- Never allow file access outside the configured workspace root.
- Never return unmasked secrets to the agent.
- Never execute blocked commands.
- Never execute operations that require approval until an approval flow exists.
- Log every SentryGate tool call.
- Store masked content in audit logs by default.
- Prefer deterministic rules before local LLM review.
- If the local model fails, fall back to the rule-based decision.
- Do not rely on LLM judgment alone for critical blocking decisions.

## 10. Development Milestones

- Step 1: backend scaffold, health check, tests, lint, mypy
- Step 2: privacy masking engine
- Step 3: rule policy and risk scoring, no LLM
- Step 4: safe tool wrappers and audit logs
- Step 5: MCP server integration
- Step 6: LM Studio local review for medium-risk calls only
- Step 7: attack demo script and frontend audit dashboard

## 11. Development Workflow

For each milestone:

1. Write or update a spec file.
2. Ask Codex to enter plan mode.
3. Review Codex's plan.
4. Ask Codex to implement only after the plan is approved.
5. Run tests.
6. Review changed files.
7. Commit.
