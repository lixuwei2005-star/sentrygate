# SentryGate Interview Notes

These notes are for explaining SentryGate in internship interviews. The safest
framing is: SentryGate is a local MCP security gateway prototype for selected
tool calls routed through its own MCP server.

## Project Background

Coding agents can read files, write files, list directories, and request shell
commands. Those capabilities are useful for local development, but they can also
expose secrets, change files before review, or make risky command execution hard
to inspect.

SentryGate explores a local gateway pattern for security-aware agent tooling. It
does not try to secure every possible local operation. It focuses on structured
tool calls routed through SentryGate.

## Architecture Explanation

Current flow:

```text
MCP-compatible agent -> SentryGate MCP Server -> SafeToolService -> policy, risk scoring, masking, audit
```

The MCP server exposes tools such as `sentry_read_file`, `sentry_write_file`,
`sentry_list_directory`, and `sentry_run_command`. The server is intentionally a
thin adapter.

`SafeToolService` is the central enforcement layer for SentryGate tools. It
checks the workspace boundary, asks the risk layer for a decision, executes only
allowed operations, masks output, and records masked audit events.

`RiskScorer` produces `allow`, `require_approval`, or `block`. `PrivacyMasker`
replaces common sensitive patterns with stable tokens. `AuditStore` records
local in-memory events for inspection.

When enabled, LM Studio review is an optional local semantic review layer for
eligible medium-risk calls only. It is not the source of truth for hard blocks.

## Why MCP Boundary Matters

MCP provides a structured tool boundary. SentryGate can inspect and score calls
that pass through its MCP server because the tool name and arguments are visible
before execution.

That boundary is also a limitation. SentryGate only protects calls routed
through SentryGate MCP tools. Codex built-in internal tools, direct shell access,
direct filesystem access, and other MCP servers are outside SentryGate's
enforcement boundary.

This is why the README and demo emphasize selected MCP-routed tool calls rather
than claiming SentryGate controls Codex as a whole.

## Why Rule-Based Scoring Comes Before LM Studio Review

Rule-based scoring is predictable, testable, and easier to reason about for
hard safety decisions. For example, sensitive paths such as `.env` and known
dangerous command patterns can be handled deterministically.

LM Studio review can add semantic context for eligible medium-risk calls, but it
should not be the first or only decision layer. A local model can return
malformed output, miss a risk, or reason inconsistently.

The design keeps deterministic policy first and uses optional model review only
as a conservative extra layer.

## Why LM Studio Cannot Override Hard Block

Local model output is probabilistic. It may be useful, but it should not weaken
deterministic policy.

In SentryGate:

- A deterministic `block` remains `block`.
- LM Studio cannot turn `block` into `allow`.
- LM Studio cannot turn `require_approval` into `allow`.
- LM Studio can preserve risk or increase risk through conservative merge
  behavior.

This keeps hard-block rules authoritative in the prototype.

## How Privacy Masking Works

SentryGate masks detected sensitive patterns before returning output to the
agent and before printing or storing audit summaries.

The prototype covers common patterns such as:

- API-key-like strings.
- Database URLs.
- Environment-style credentials.
- Email addresses.
- Private-key-like blocks, if matched by the current masker.

Masking uses stable tokens during a session, so repeated detected values can map
to consistent placeholders such as `[API_KEY_001]` or `[EMAIL_001]`.

This is common-pattern masking, not a guarantee that every possible secret
format will be detected.

## How Audit Logs Avoid Raw Secrets

Audit events are intended to show what SentryGate decided without storing raw
secret values.

Events can include:

- Tool name.
- Masked arguments or bounded summaries.
- Decision.
- Execution status.
- Risk score.
- Reasons.
- Masked output summary.
- Masked finding tokens.

Events should not include:

- Raw secret values.
- Raw `.env` contents.
- Raw command output containing secrets.
- Raw LM Studio prompts or responses containing sensitive content.

The current audit store is in-memory. It is useful for local demos and
development inspection, but it is not durable audit infrastructure.

## Limitations and Future Work

Current limitations:

- MCP-only boundary.
- No control over Codex built-in internal tools.
- No production-grade sandboxing.
- No enterprise governance.
- No durable audit database.
- No human approval UI or delayed execution workflow.
- Rule-based detection can miss novel risky command forms.
- Privacy masking can miss unknown secret formats.

Future work:

- Durable audit storage.
- Human approval workflow.
- Frontend audit dashboard.
- Richer policy configuration.
- More robust command parsing.
- Integration guides for different MCP clients.
- Additional tests and demo scenarios.

The strongest interview explanation is honest and practical: SentryGate
demonstrates how a local MCP gateway can apply deterministic checks, masking,
and auditability to selected agent tool calls while keeping its trust boundary
explicit.
