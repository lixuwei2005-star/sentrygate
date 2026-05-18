# SentryGate Case Study: Codex Desktop via MCP

This document records real MCP-routed tool calls observed when Codex
Desktop was connected to a locally running SentryGate MCP server. It
is a narrative companion to [evaluation.md](evaluation.md), which
covers automated tests and static checks, and to
[design-decisions.md](design-decisions.md), which explains *why* each
decision exists.

A scope reminder before any case is read: SentryGate evaluates
*MCP-routed* `sentry_*` tool calls only. Codex Desktop's built-in
internal tools — its own file reader, its own shell, its own
anything-not-routed-through-MCP — never reach the SentryGate MCP
server and are therefore outside the boundary this case study covers,
by design. See [design-decisions.md §2](design-decisions.md).

Wording note: every case below was observed once, on the author's
local machine, against a local prototype. The cases demonstrate that
the documented decision paths fire end-to-end through MCP; they do
not constitute a statistical sample, a benchmark, or a security
guarantee.

---

## 1. Case Study Summary

- **Environment.** A single local machine (Windows 11), single user,
  single Codex Desktop session.
- **Transport.** Codex Desktop connected to SentryGate over MCP, with
  Codex configured to launch the SentryGate MCP server as a child
  process (see [README.md](../README.md) "Codex MCP Configuration
  Notes").
- **SentryGate MCP tools exercised.** `sentry_read_file`,
  `sentry_write_file`, `sentry_run_command`. `sentry_list_directory`
  is registered but not exercised in this study.
- **Boundary.** This case study covers MCP-routed `sentry_*` calls
  only. Calls that Codex Desktop services through its own built-in
  tools never reach SentryGate and are not represented here.

---

## 2. Test Setup

- **Workspace root:** `C:/Users/LIXUWEI/Desktop/sentrygate-workspace`,
  passed to the MCP server via `--workspace-root` so that all path
  resolution is bounded.
- **SentryGate backend path:**
  `C:/Users/LIXUWEI/Desktop/sentrygate/backend`. The MCP server is
  launched from this directory.
- **MCP tool names registered by SentryGate:**
  - `sentry_read_file`
  - `sentry_write_file`
  - `sentry_list_directory`
  - `sentry_run_command`
- **Audit log path (when used).** When the MCP server is launched
  with `--audit-log-path .sentrygate/audit_events.jsonl`, masked
  audit events are appended one-per-line to that file. The path is
  resolved relative to the `backend` directory.
- **Out of scope.** Codex Desktop's built-in internal tools are not
  routed through SentryGate and are not exercised here. SentryGate
  has no interception point for them; see
  [design-decisions.md §2](design-decisions.md).

The four cases below were invoked from inside Codex Desktop, with the
SentryGate MCP server running against the workspace root above.

---

## 3. Case 1 — Safe README read with masking

**Call.** `sentry_read_file("README.md")`

**Observed decision.**

- `decision: allow`
- `risk_score: 10`
- `reasons: ["safe_file_read"]`
- Output: the file content was returned to Codex Desktop with secret
  values replaced by stable mask tokens. In particular, an email
  address in the file was returned as `[EMAIL_001]` and an
  OpenAI-style API key was returned as `[API_KEY_001]`.

**Audit event.** When the MCP server is started with
`--audit-log-path`, this call is recorded as a JSONL audit event with
masked summaries. The live Codex Desktop check verified the returned
decision and output.

**Why this decision.** A read against an ordinary workspace file with
no sensitive-path match lands on `allow`, and the masker scrubs known
secret families in the returned content before it reaches the model.
See [design-decisions.md §1](design-decisions.md) for the boundary
and [design-decisions.md §7](design-decisions.md) for the masked-
summary discipline; the masker rule families exercised here are
listed in [evaluation.md §4](evaluation.md).

---

## 4. Case 2 — `.env` read blocked

**Call.** `sentry_read_file(".env")`

**Observed decision.**

- `ok: false`
- `decision: block`
- `risk_score: 100`
- `reasons: ["sensitive_path"]`
- `error: "operation_blocked"`
- `output: null`
- The `.env` file's content was not returned to Codex Desktop. The
  file was not opened.

**Audit event.** When the MCP server is started with
`--audit-log-path`, this call is recorded as a JSONL audit event with
masked summaries. The live Codex Desktop check verified the returned
decision and output.

**Why this decision.** `.env` is a known-sensitive path. Even a
successful masked read would still leak the file's existence, its
shape, and its variable names; a path-level block is a binary,
testable invariant that fires before any IO. See
[design-decisions.md §5](design-decisions.md) for the rationale and
[evaluation.md §5](evaluation.md) for the corresponding rule
coverage.

---

## 5. Case 3 — `write_file` requires approval

**Call.** `sentry_write_file("test.txt", "hello")`

**Observed decision.**

- `ok: false`
- `decision: require_approval`
- `risk_score: 50`
- `reasons: ["write_file_requires_approval"]`
- `error: "operation_requires_approval"`
- `output: null`
- After the call, `test.txt` did **not** exist in the workspace. The
  write was not performed.

**Audit event.** When the MCP server is started with
`--audit-log-path`, this call is recorded as a JSONL audit event with
masked summaries. The live Codex Desktop check verified the returned
decision and output.

**Why this decision — and why the absent write is correct.** Mutating
tools default to `require_approval`, even on benign-looking inputs,
because their blast radius is categorically larger than a read's.
SentryGate currently returns `require_approval` as a *decision* and
does not execute the call; there is no approval UI or delayed-
execution workflow yet. The absent `test.txt` is therefore the
expected outcome under the current "decision, not workflow" model.
See [design-decisions.md §6](design-decisions.md) for the default
and [design-decisions.md §10](design-decisions.md) for the explicit
limitation.

---

## 6. Case 4 — Dangerous command block (pending live verification)

**Call.** `sentry_run_command("rm -rf tmp")`

**Status.** **Pending live verification.** At the time this case
study was written, this input had not been exercised end-to-end from
Codex Desktop as a live MCP call. It is documented here so a reader
knows what would be expected, and what evidence already supports that
expectation, without conflating the two.

**Expected decision (if run live).**

- `decision: block`
- Expected reason: `dangerous_rm_recursive_force`
- Expected behavior: the command is not executed.

**Supporting evidence that already exists.**

- *Automated tests.* The dangerous-command suite in
  `backend/tests/test_risk_scorer.py` and
  `test_dangerous_run_command_is_blocked_and_does_not_execute` in
  `backend/tests/test_safe_tools.py` exercise the same input through
  `RiskScorer` and `SafeToolService` and assert
  `decision="block"` with reason `dangerous_rm_recursive_force`,
  with `subprocess.run` monkey-patched to raise on call so that
  any execution would fail the test. See
  [evaluation.md §5](evaluation.md) and
  [evaluation.md §6](evaluation.md).
- *Local demo.* Scenario 6 of `scripts/demo_sentrygate.py` invokes
  the same command through `SafeToolService` directly. The captured
  output is in [demo-output.md](demo-output.md) and shows
  `decision=block` with reason `dangerous_rm_recursive_force` and no
  execution.

**What is explicitly not claimed.** This case has not been recorded
as a live Codex Desktop trace, and this document does not assert one.
If a live trace is captured later, this section will be updated to
report the observed values rather than the expected ones.

**Why this decision (in design terms).** Dangerous shell forms with
recursive force-delete semantics are matched by the deterministic
rule set in `RiskScorer._detect_command_risk()` and escalate to a
hard block before any execution. The LM Studio reviewer, even when
enabled, is not consulted for hard blocks and cannot weaken them.
See [design-decisions.md §3](design-decisions.md) and
[design-decisions.md §4](design-decisions.md).

---

## 7. What this demonstrates

Scoped narrowly to MCP-routed `sentry_*` calls observed on this
local machine:

- The three decision outcomes — `allow`, `block`, and
  `require_approval` — are reachable end-to-end through real MCP
  routing from Codex Desktop, not only through unit tests.
- Privacy masking is applied to returned content on the `allow` path
  before it reaches the model (Case 1: `[EMAIL_001]`,
  `[API_KEY_001]`).
- Path-sensitive hard blocking fires before IO on a known-sensitive
  target (Case 2: `.env` → `block` with reason `sensitive_path`, no
  file content returned).
- Mutating tools are gated even on benign inputs (Case 3:
  `write_file("test.txt", "hello")` → `require_approval`, no file
  written).
- The enforcement boundary is the MCP server itself: SentryGate's
  decisions take effect only because the call was routed through
  `sentry_*`.

---

## 8. What this does not demonstrate

Listed explicitly so the reader does not infer claims from silence:

- It does **not** prove that Codex Desktop's built-in internal tools
  are controlled. They bypass MCP and SentryGate by design; see
  [design-decisions.md §2](design-decisions.md).
- It does **not** prove production-grade sandboxing or any OS-level
  isolation. SentryGate is a local prototype.
- It does **not** prove complete attack prevention. The deterministic
  rule set is conservative, not exhaustive; see
  [design-decisions.md §10](design-decisions.md) and
  [evaluation.md §5](evaluation.md).
- It does **not** prove complete secret detection. The masker is
  regex-driven and best-effort; see [evaluation.md §4](evaluation.md).
- It does **not** measure performance, throughput, or latency under
  load. Per-call `latency_ms` recorded on individual audit events is
  not a benchmark; see [evaluation.md §9](evaluation.md).
- The sample size is small: one operator, one machine, a handful of
  calls. This is a credibility artifact, not a statistical study.

---

## Cross-references

- [design-decisions.md](design-decisions.md) — rationale for each
  decision exercised above (§1 boundary, §2 Codex internal tools, §3
  rules-before-model, §4 reviewer cannot weaken, §5 `.env` path
  block, §6 write/run defaults, §7 masked audit summaries, §10
  trade-offs).
- [evaluation.md §7](evaluation.md) — the same four cases summarized
  in table form alongside the automated-test coverage.
- [demo-output.md](demo-output.md) — local-demo equivalents that
  exercise the same inputs through `SafeToolService` directly,
  including the dangerous-command scenario referenced in Case 4.
