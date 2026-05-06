# Step 7 Portfolio Packaging Spec

## Goal

Define how to package SentryGate as a portfolio-ready internship project.

This step is documentation planning only. It should make the project easier to
demo, explain on a resume, and discuss in interviews without overstating the
security guarantees of the current prototype.

## Scope

This step includes specifications for:

- README polishing.
- Demo output documentation.
- Resume bullet points.
- Interview explanation notes.
- Security boundary explanation.
- Credible internship portfolio wording.

Out of scope for this spec creation step:

- Creating or modifying `README.md`.
- Creating or modifying demo output documentation.
- Creating or modifying resume bullet documentation.
- Creating or modifying interview notes.
- Backend code changes.
- Test changes.
- Script changes.
- MCP behavior changes.
- LM Studio behavior changes.
- Frontend work.

Out of scope for future Step 7 implementation:

- New backend features.
- New frontend.
- MCP tool behavior changes.
- LM Studio review behavior changes.
- Production-grade sandboxing claims.
- Enterprise governance claims.

## Required Future Files

Future Step 7 implementation should create:

```text
docs/demo-output.md
docs/resume-bullets.md
docs/interview-notes.md
```

Future Step 7 implementation should also polish the existing root
`README.md`.

No backend code, tests, scripts, MCP behavior, or LM Studio behavior should be
modified for Step 7 unless a later approved implementation step explicitly
changes scope.

## Core Wording Boundaries

All portfolio packaging must preserve this boundary:

```text
SentryGate only protects tool calls routed through its MCP server.
It does not intercept or control Codex built-in internal tools.
```

All docs must avoid claiming that SentryGate:

- Fully controls Codex built-in tools.
- Provides production-grade sandboxing.
- Provides enterprise-ready governance.
- Prevents real-world attacks beyond the implemented local prototype.
- Replaces operating-system, container, VM, EDR, antivirus, or cloud security
  controls.
- Guarantees complete secret detection.
- Guarantees complete command-risk detection.
- Executes approval-required operations.

Recommended credible positioning:

```text
SentryGate is a local MCP security gateway prototype that demonstrates
deterministic policy checks, privacy masking, approval gating, hard blocking,
and masked audit events for tool calls routed through its own MCP server.
```

The project may be described as portfolio-ready, internship-ready, or a local
prototype. It should not be described as production-grade, enterprise-ready, or
complete security isolation.

## README Polishing Requirements

Future Step 7 implementation should polish the root `README.md` for a hiring
manager, interviewer, or internship reviewer.

The README should be clear, concise, and demo-oriented. It should explain what
was built, what security boundary it covers, and what it intentionally does not
cover.

Required sections:

- `Quick Demo`
- `What I Built`
- `What It Protects`
- `What It Does Not Protect`
- `Current Architecture`
- `Roadmap`

### Quick Demo

The `Quick Demo` section should show how to run the local demo and what a
reviewer should expect to see.

It should reference `docs/demo-output.md` for fuller scenario descriptions.

The section should explain that the demo is local, deterministic, and uses fake
secrets only.

The section should not imply that the demo proves production-grade isolation.

### What I Built

The `What I Built` section should summarize the implemented prototype:

- A local MCP server exposing SentryGate tools.
- Safe wrappers for reading files, writing files, listing directories, and
  requesting command execution.
- Rule-based risk scoring.
- Privacy masking before returning output.
- In-memory audit events.
- Optional LM Studio semantic review for eligible medium-risk calls, if already
  implemented by the time README polishing happens.

The section should use first-person-friendly portfolio language without
overclaiming. Example tone:

```text
I built a local MCP security gateway prototype that sits between an
MCP-compatible coding agent and selected local tools.
```

### What It Protects

The `What It Protects` section must describe the implemented MCP-only boundary:

- Calls made through SentryGate MCP tools.
- Reads and directory listings inside the configured workspace root.
- Writes requested through SentryGate tools.
- Commands requested through SentryGate tools.
- Tool output returned through SentryGate after privacy masking.
- Audit records created by SentryGate for its own tool calls.

The section should mention the configured workspace root as the filesystem
boundary enforced by SentryGate tools.

### What It Does Not Protect

The `What It Does Not Protect` section must be explicit.

Required points:

- SentryGate does not intercept Codex built-in internal tools.
- SentryGate does not control direct shell access outside its MCP tools.
- SentryGate does not provide OS-level sandboxing.
- SentryGate does not provide container or VM isolation.
- SentryGate does not guarantee complete real-world attack prevention.
- SentryGate does not include production approval workflows.
- SentryGate does not provide durable enterprise audit storage in the current
  prototype.

This section should be prominent enough that readers understand the trust
boundary before interpreting the demo.

### Current Architecture

The `Current Architecture` section should include this architecture chain:

```text
Codex / MCP Agent -> SentryGate MCP Server -> SafeToolService -> RiskScorer + PrivacyMasker + AuditStore
```

If LM Studio review is included in the current code by the time Step 7 is
implemented, the architecture may show it as optional and subordinate to
deterministic rules:

```text
RiskScorer -> optional LM Studio review for medium-risk calls -> conservative merge
```

The architecture section must state that deterministic rules run before LM
Studio review and that LM Studio cannot override hard blocks.

### Roadmap

The `Roadmap` section should separate implemented behavior from future work.

Appropriate future roadmap items:

- Durable audit storage.
- Human approval UI or approval API.
- Richer policy configuration.
- Better command parsing coverage.
- Frontend audit dashboard.
- More complete integration examples.
- Optional deployment hardening experiments.

The roadmap should not imply these features already exist.

## `docs/demo-output.md` Requirements

Future Step 7 implementation should create:

```text
docs/demo-output.md
```

This document should help a reviewer understand and reproduce the local demo.
It should be suitable for linking from the README.

Required content:

- How to run the local demo.
- Sample demo output.
- Explanation of each scenario.
- Explanation that fake secrets are used.
- Explanation that the demo does not require Codex or a running MCP client if
  the existing demo script uses `SafeToolService` directly.
- Reminder that the protection boundary is limited to SentryGate-routed tool
  calls.

### How to Run the Local Demo

The document should include commands matching the actual demo script created in
earlier steps.

If the current demo script is:

```text
backend/scripts/demo_sentrygate.py
```

Then the document should show:

```powershell
cd backend
uv run python scripts/demo_sentrygate.py
```

The document should state that the demo creates a temporary workspace and uses
fake secret values.

### Sample Demo Output

The document should include representative sample output, not necessarily every
line of a live run if timestamps or temporary paths vary.

The sample output should show:

- `allow`
- `block`
- `require_approval`
- Masked secret output.
- Audit events.

Raw fake secrets should not be printed in the sample output. Use masked values
or placeholders such as:

```text
[SECRET_1]
```

### Scenario Explanations

The document must explain these scenarios:

- Safe read masks secrets.
- `.env` read blocked.
- Write requires approval.
- List directory allowed.
- Normal command requires approval.
- Dangerous command blocked.
- Audit events printed.

For each scenario, include:

- What operation is requested.
- Expected decision.
- Whether execution happens.
- What the result demonstrates.
- What security boundary or limitation applies.

#### Safe Read Masks Secrets

Explain that reading an allowed file returns content only after privacy masking.

The explanation should avoid saying secret detection is complete. It may say the
prototype detects several common patterns such as API-key-like strings, database
URLs, and environment-style credentials if those are implemented.

#### `.env` Read Blocked

Explain that sensitive file paths such as `.env` are hard-blocked by
deterministic rules.

The document should state that blocked files are not returned to the agent
through SentryGate.

#### Write Requires Approval

Explain that write operations currently return `require_approval` and do not
write content because the prototype does not yet include an approval workflow.

Do not claim that a human approval product exists.

#### List Directory Allowed

Explain that normal directory listing inside the workspace is allowed when it
does not trigger policy rules.

The explanation should clarify that listing names is different from reading
sensitive file contents.

#### Normal Command Requires Approval

Explain that normal command requests are approval-gated by default and are not
executed while no approval workflow exists.

Do not show command stdout as if the command executed unless the implementation
actually executes allowed commands.

#### Dangerous Command Blocked

Explain that obviously dangerous command strings are blocked by deterministic
rules.

The document should not say this blocks every possible dangerous command form.
Use credible language such as:

```text
This demonstrates rule-based blocking for known dangerous patterns in the
prototype.
```

#### Audit Events Printed

Explain that audit events are printed for SentryGate tool calls and should
include masked summaries, decisions, risk scores, and reasons.

The document must state that audit output should not include raw secrets.

## `docs/resume-bullets.md` Requirements

Future Step 7 implementation should create:

```text
docs/resume-bullets.md
```

This document should provide credible resume wording in Chinese and English.
It should be easy for the project owner to adapt into a resume, LinkedIn
profile, GitHub profile, or internship application.

Required versions:

- Chinese resume version.
- English resume version.
- 3-bullet concise version.
- 5-bullet detailed version.

The document should avoid overclaiming. It must mention SentryGate as a local
MCP security gateway prototype.

### Chinese Resume Version

The Chinese version should sound credible for an internship resume.

It should mention:

- 本地 MCP 安全网关原型.
- 隐私脱敏.
- 风险评分.
- 阻断和审批门控.
- 审计日志.
- 明确的 MCP 工具调用边界.

It should avoid terms that imply production readiness, such as:

- 企业级.
- 生产级.
- 完整防护.
- 全面拦截.
- 真实攻击防御保证.

### English Resume Version

The English version should mention:

- Local MCP security gateway prototype.
- Deterministic policy/risk scoring.
- Secret masking.
- Approval gating.
- Hard blocking.
- Masked audit events.
- Clear MCP-only enforcement boundary.

It should avoid terms such as:

- Production-grade.
- Enterprise-ready.
- Fully secure.
- Complete sandbox.
- Attack-proof.

### 3-Bullet Concise Version

The concise version should fit a resume project entry.

It should use three bullets that communicate:

- What was built.
- Core technical/security behavior.
- Boundary and credibility.

Example direction:

```text
- Built SentryGate, a local MCP security gateway prototype for routing selected
  coding-agent tool calls through deterministic policy checks.
```

The final implementation may refine wording, but it must keep the prototype
boundary.

### 5-Bullet Detailed Version

The detailed version should provide five bullets for a longer project
description.

It should cover:

- MCP server and safe tool wrappers.
- Risk scoring decisions.
- Privacy masking.
- Audit logging.
- Optional local LM Studio review, if implemented, with the hard-block boundary
  preserved.

If LM Studio is not implemented or is disabled by default, the wording should
say so clearly.

## `docs/interview-notes.md` Requirements

Future Step 7 implementation should create:

```text
docs/interview-notes.md
```

This document should help the project owner explain SentryGate in internship
interviews.

Required sections:

- Project background.
- Architecture explanation.
- Why MCP boundary matters.
- Why rule-based scoring comes before LM Studio review.
- Why LM Studio cannot override hard block.
- How privacy masking works.
- How audit logs avoid raw secrets.
- Limitations and future work.

### Project Background

Explain the motivation:

- Coding agents can read files, write files, and request commands.
- These capabilities are useful but risky near local source code and secrets.
- SentryGate explores a local gateway pattern for selected MCP tool calls.

The explanation should be framed as a prototype built to learn and demonstrate
security-aware agent tooling.

### Architecture Explanation

Explain the flow:

```text
MCP-compatible agent -> SentryGate MCP Server -> SafeToolService -> policy,
risk scoring, masking, audit
```

Mention that `SafeToolService` is the central enforcement layer for SentryGate
tools.

If LM Studio review is implemented, describe it as optional semantic review for
eligible medium-risk calls only.

### Why MCP Boundary Matters

Explain that MCP provides an explicit tool boundary. SentryGate can enforce
policy on tool calls that pass through its MCP server because those calls are
represented as structured requests.

The notes must also say that calls outside that route, including Codex built-in
internal tools, are outside SentryGate's control.

### Why Rule-Based Scoring Comes Before LM Studio Review

Explain that deterministic rules are predictable, testable, and suitable for
hard security decisions in the prototype.

LM Studio review can add semantic context, but it should not be the first or
only decision layer for blocking sensitive operations.

### Why LM Studio Cannot Override Hard Block

Explain that local model output is probabilistic and may be wrong or malformed.

For that reason:

- Deterministic hard blocks remain authoritative.
- LM Studio cannot reduce `block` to `allow`.
- LM Studio cannot reduce `require_approval` to `allow`.
- LM Studio may only preserve or increase risk in the conservative merge
  design.

### How Privacy Masking Works

Explain that SentryGate masks sensitive patterns before returning output to the
agent and before printing or storing audit summaries.

Examples may include:

- API-key-like strings.
- Database URLs.
- Environment-style credentials.
- Private-key-like blocks, if implemented.
- Emails, if implemented.

The notes should say the masking engine covers common patterns in the
prototype, not every possible secret format.

### How Audit Logs Avoid Raw Secrets

Explain that audit events should record:

- Tool name.
- Masked arguments or summaries.
- Decision.
- Risk score.
- Reasons.
- Masked output summary when applicable.

They should not record:

- Raw secret values.
- Raw `.env` contents.
- Raw command output containing secrets.
- Raw LM Studio prompts or responses containing sensitive content.

If the current audit store is in-memory, the notes should say it is useful for
local demos but not durable audit infrastructure.

### Limitations and Future Work

Required limitations:

- MCP-only boundary.
- No control over Codex built-in internal tools.
- No production-grade sandboxing.
- No enterprise governance.
- No durable audit database if only in-memory audit exists.
- No human approval workflow if approval-required calls remain terminal.
- Rule-based detection can miss novel risky command forms.
- Secret masking can miss unknown formats.

Appropriate future work:

- Durable audit storage.
- Human approval workflow.
- Frontend audit dashboard.
- Richer policy configuration.
- More robust command parsing.
- Integration guides for different MCP clients.
- Additional tests and demo scenarios.

## Portfolio Tone Guidelines

The packaging should sound confident but careful.

Use wording like:

- `prototype`
- `local MCP security gateway`
- `selected tool calls`
- `deterministic policy checks`
- `privacy masking`
- `approval gating`
- `hard-block rules`
- `masked audit events`
- `MCP-only protection boundary`

Avoid wording like:

- `production-grade sandbox`
- `enterprise-ready governance`
- `fully secures Codex`
- `prevents attacks`
- `complete data-loss prevention`
- `guaranteed secret protection`
- `controls all local tools`

## Acceptance Criteria

This spec creation step is complete when:

- `docs/specs/STEP_7_PORTFOLIO_PACKAGING_SPEC.md` exists.
- The spec clearly defines `docs/demo-output.md`.
- The spec clearly defines `docs/resume-bullets.md`.
- The spec clearly defines `docs/interview-notes.md`.
- The spec defines README polishing requirements.
- The spec preserves the MCP-only protection boundary.
- The spec avoids overclaiming security guarantees.
- The spec states that no new backend features are included.
- The spec states that no frontend is included.
- The spec states that no MCP behavior changes are included.
- The spec states that no LM Studio behavior changes are included.
- No backend code is modified.
- No tests are required for this spec-only step.
