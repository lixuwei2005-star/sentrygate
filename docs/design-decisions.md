# SentryGate Design Decisions

SentryGate is a local MCP security gateway prototype for selected tool calls.
This document explains *why* the design looks the way it does — what
trade-offs were accepted, what was deliberately excluded, and where in the
code each decision lives.

It is meant for a reviewer who has skimmed the README but has not read the
source. Each section follows the same shape:

- **Decision** — what SentryGate actually does.
- **Why** — the reasoning behind the choice.
- **What this rules out** — the limits of the claim.
- **Where in the code** — a pointer the reviewer can open.

For verification of these behaviors, see [evaluation.md](evaluation.md) (to
be written). For real MCP-routed traces from Codex Desktop, see
[case-study-codex.md](case-study-codex.md) (to be written).

A note on tone before we begin: SentryGate is a prototype. It is not a
production-grade gateway, not a sandbox, and not a replacement for OS-level
isolation. The decisions below are about getting *one* boundary right —
the boundary the prototype actually owns.

---

## 1. Why MCP is the protected boundary

**Decision.** SentryGate enforces policy at the MCP tool-call interface.
The protected tools are `sentry_read_file`, `sentry_write_file`,
`sentry_list_directory`, and `sentry_run_command`. Calls that traverse
those tools are scored, optionally masked, optionally held for approval,
and audited.

**Why.** MCP exposes a structured tool name plus typed arguments *before*
execution. That gives policy something concrete to inspect: a path string,
a command string, a workspace-relative target. A free-text prompt does
not. Working at the tool boundary also means the policy code does not have
to parse natural language, infer intent, or model the agent's plan — it
only has to answer "given this call, what should happen?".

This is a *boundary-style* control. It protects what flows through the
boundary, nothing else.

**What this rules out.** SentryGate is not an OS sandbox, not a kernel
module, not a syscall hook, not a container, not a VM, not an EDR, and
not antivirus. Any call that does not traverse the SentryGate MCP server
is outside the boundary.

**Where in the code.** `backend/app/mcp/server.py` is a thin adapter
that forwards each MCP tool call into `backend/app/tools/safe_tools.py
-> SafeToolService`. All policy logic lives in `SafeToolService` and its
collaborators, not in the MCP layer.

---

## 2. Why SentryGate cannot protect Codex built-in internal tools

**Decision.** Codex Desktop's built-in internal tools — its own file
reader, its own shell, its own anything-not-routed-through-MCP — are
explicitly outside SentryGate's enforcement boundary.

**Why.** Those calls never reach the MCP server, so there is no hook
point. A gateway can only gate traffic it actually sees. Claiming
otherwise would be a security false advertisement, and the README, the
interview notes, and this document all draw the same line in the same
place to keep the story coherent.

**What this rules out.** Any claim that "SentryGate protects Codex" as a
product. Protection is on `sentry_*` MCP-routed calls only. If a Codex
session uses a built-in file read instead of `sentry_read_file`,
SentryGate has no visibility into it.

**Where in the code.** This is a *negative* property — there is no
interception layer for Codex's internal tools to point at. The only
enforced entry points are the four `sentry_*` methods on
`SafeToolService`.

---

## 3. Why deterministic rules run before LM Studio review

**Decision.** Every `sentry_*` method calls the deterministic
`RiskScorer` first. The optional LM Studio reviewer is consulted
afterward, and only for the narrow case of `require_approval`.

**Why.** Hard rules are fast, reproducible, and unit-testable. They
handle the cases that must not depend on a probabilistic model:
sensitive paths like `.env`, `id_rsa`, `*.pem`; dangerous shell forms
like `rm -rf` with force flags, `sudo`, `mkfs`, `chmod 777`,
`curl | bash`. Putting deterministic policy first means the cases with
clear answers get clear answers, and the model never gets to vote on
them.

The reviewer is then a conservative second opinion on the genuinely
ambiguous middle band — calls that already landed at `require_approval`
because of the default policy, not because of a hard rule. The reviewer's
job is to potentially *raise* risk on those, never to lower it.

**What this rules out.** This is not a model-first architecture. The
model is not the source of truth for safety decisions. It is also not
required: SentryGate runs with the reviewer disabled by default, and the
deterministic layer alone produces the `allow` / `require_approval` /
`block` outcome.

**Where in the code.** `backend/app/tools/safe_tools.py
-> SafeToolService.sentry_read_file()` (and the other three `sentry_*`
methods) call `RiskScorer.score_tool_call()` first, then pass the result
through `SafeToolService._review_risk_result()`.
`SafeToolService._is_review_candidate()` is the gate that decides whether
the reviewer is even invoked.

---

## 4. Why LM Studio cannot override a hard block

**Decision.** A deterministic `block` (or `allow`) is final. The reviewer
is not asked, and if it were asked, its output would be discarded.

**Why.** A local language model is probabilistic. It can return malformed
output, be inconsistent across calls, or be coaxed into "this looks fine"
by hostile content embedded in an argument. None of that should be able
to unlock `.env` reads or `rm -rf /`. The trust hierarchy is rules first,
model second.

The prototype enforces this invariant in two places — once in the prompt
(the system message tells the model it "may not weaken" the deterministic
result) and once in code (the merge function refuses to act on any
result whose original decision was `allow` or `block`). The redundancy is
intentional: a misbehaving prompt template alone cannot break the
invariant.

**What this rules out.** This is not "AI safety review" in the sense of
trusting a model to make safety calls. The model is advisory. It can keep
the current decision or escalate `require_approval` to `block`; it cannot
do anything else.

**Where in the code.** `backend/app/tools/safe_tools.py
-> SafeToolService._is_review_candidate()` only returns true for
`require_approval` calls. `SafeToolService._conservative_review_result()`
short-circuits with `return original_result` when the original decision
is `allow` or `block`. The same invariant is duplicated in
`backend/app/risk/lmstudio_client.py -> merge_review()` and stated in the
`SYSTEM_PROMPT` constant.

---

## 5. Why `.env` is blocked by path, not read-then-mask

**Decision.** Reads targeting `.env`, `*.pem`, `id_rsa`, and similar
sensitive paths return `block` with reason `sensitive_path`. The file is
never opened.

**Why.** Masking is a regex-driven scrub of file *contents*. Even when
it works perfectly on the body, a successful read still leaks the file's
existence, its size, the count and shape of its lines, and the *names*
of the variables inside it. Knowing that a workspace has a
`STRIPE_SECRET_KEY=` line is itself signal — masking the value doesn't
help with that. A path-level block is a binary, testable invariant;
masking is best-effort. For known-sensitive paths, the binary invariant
is the right tool.

**What this rules out.** This does not mean every secret in the
workspace is reachable through a known sensitive name. Secrets stored in
unusually named files still depend on the masker to catch their *values*
on read. The path block is a strong rule for an obvious class of files,
not a complete solution to secret exposure. See §10.

**Where in the code.** `backend/app/risk/scorer.py
-> RiskScorer._score_path_tool()` calls
`RiskScorer._is_sensitive_path()` and short-circuits to
`HARD_BLOCK_SCORE` with reason `sensitive_path` before any file IO is
attempted. `SafeToolService.sentry_read_file()` then takes the
`block` branch and returns without opening the file.

---

## 6. Why `write_file` and `run_command` default to `require_approval`

**Decision.** Writes and shell commands land in `require_approval` by
default, even when no hard rule fires. Reads and directory listings can
reach `allow`.

**Why.** A read at worst leaks. A write or a command can mutate the
workspace, delete data, install something, or escalate. The blast radius
of a state-changing call is categorically larger than the blast radius
of an inspection call, so the default should be different.

Defaulting these to human-in-the-loop also matches the trust model the
project is honest about: "selected tool calls" through a local prototype,
where the operator remains the final authority for anything that changes
state.

**What this rules out.** SentryGate does not currently have an approval
UI or a delayed-execution workflow. `require_approval` is returned as a
decision; the call is not executed and nothing is held in a queue waiting
for human input. Building that workflow is roadmap, not a current
feature. See §10.

**Where in the code.** `backend/app/risk/scorer.py
-> RiskScorer._score_path_tool()` tags writes with reason
`write_file_requires_approval` and uses `WRITE_FILE_SCORE` to land them
in the `require_approval` band. `RiskScorer._score_run_command()` does
the analogous thing for shell commands with reason
`run_command_requires_approval`, except when a dangerous-command rule
fires and escalates to `HARD_BLOCK_SCORE`.

---

## 7. Why audit logs store masked summaries only

**Decision.** Every `AuditEvent` records masked, length-bounded summaries
of arguments and output. Findings emitted by the masker are recorded as
stable tokens. Reasons added by the optional reviewer are also passed
through the masker before being stored.

**Why.** An audit log is for answering "did the gateway decide
correctly?", not "reconstruct the secret that triggered the decision."
Storing raw values would create a second on-disk copy of exactly the
data SentryGate is trying to keep out of the agent transcript — strictly
worse than not auditing. Bounded length (2 KB per summary) also keeps
the log itself from becoming a side-channel for large data exfiltration.

**What this rules out.** This is not a forensic store and is not a
replacement for centralized audit infrastructure. It is observability for
a local prototype.

**Where in the code.** `backend/app/tools/safe_tools.py
-> SafeToolService._append_audit_event()` builds every event from
already-masked summaries. `SafeToolService._mask_text()` is the single
chokepoint that funnels strings through `PrivacyMasker.mask_text()`, and
`SafeToolService._bounded_summary()` enforces the 2 KB cap.
`SafeToolService._mask_added_reasons()` masks any reasons the optional
reviewer appends.

---

## 8. Why the dashboard reads JSONL instead of the in-memory audit store

**Decision.** The Streamlit AgentOps dashboard loads events from
`.sentrygate/*.jsonl` files on disk. It does not talk to the MCP server
over a socket or import the in-memory audit store.

**Why.** JSONL is durable across process restarts and across multiple
Codex sessions. A reviewer can open the dashboard tomorrow to inspect
what happened today, without keeping the MCP server alive. Reading from
a file also decouples the dashboard's lifecycle from the MCP server's,
and lets the dashboard be a separate process with no execution authority.
The MCP server's job is to gate live calls; the dashboard's job is to
read the trail those calls left behind.

**What this rules out.** This is not live streaming. It is a "tail the
log" model with whatever lag the user's refresh introduces. For a local
prototype that lag is fine; for live SOC monitoring it would not be.

**Where in the code.** `backend/dashboard/_data.py -> load_events()`
parses each line via `app.audit.jsonl_store.JsonlAuditStore._event_from_line`.
There is no networked path between the dashboard and the MCP server.

---

## 9. Why the dashboard is read-only and restricted to `.sentrygate/*.jsonl`

**Decision.** The dashboard validates the user-provided log path and
rejects anything that (a) does not end in `.jsonl`, (b) is a directory,
or (c) does not contain a `.sentrygate` path component.

**Why.** The dashboard is an observability surface, not a control plane.
Without the whitelist, an operator could type any path into the sidebar
and turn the dashboard into a generic local file viewer — exactly the
shape of failure SentryGate is meant to prevent for the agent. Applying
the same instinct to the human-facing tool keeps the design coherent.

**What this rules out.** This is not a sandboxed renderer and not a
cryptographic guarantee. A user with shell access to the machine can
always read the underlying file directly. The whitelist removes the
*dashboard itself* as a misuse vector; it does not change filesystem
permissions.

**Where in the code.** `backend/dashboard/_data.py
-> validate_audit_log_path()` enforces the suffix, directory, and
`.sentrygate`-component checks. `backend/dashboard/_data.py
-> load_events()` calls the validator first and returns a `rejected=True`
result before any IO if validation fails.

---

## 10. Trade-offs and limitations

This section collects the limits of the design above. None of them are
surprises — they are the deliberate other side of each decision.

- **MCP-only boundary, not full sandboxing.** Anything that does not go
  through `sentry_*` is unprotected. The README, the interview notes,
  and this doc all say the same thing on purpose.

- **Deterministic rules have false positives and false negatives.** A
  legitimate `rm -rf` against a scratch directory will be blocked.
  Obfuscated commands, non-English variants, or novel shell forms can
  slip past the patterns. The rule set in
  `backend/app/risk/scorer.py -> RiskScorer._detect_command_risk()` is
  conservative, not exhaustive.

- **Masking is regex-driven.** New vendor key shapes need new patterns.
  The masker covers common families (emails, API-key-like tokens,
  database URLs, environment-style credentials, private-key blocks) but
  cannot guarantee coverage for every secret format.

- **LM Studio review is local, optional, and advisory.** It depends on
  the user actually running LM Studio. It cannot weaken a decision (see
  §4). Treating its output as authoritative was a non-goal from the
  start.

- **`require_approval` is a decision, not a workflow.** SentryGate
  returns `require_approval` and does not execute the call. There is no
  UI yet to approve and resume, and no queue. Building that is roadmap.

- **Audit storage is observability, not enterprise audit.** The
  in-memory store is lost on process exit. The JSONL store persists, but
  neither is durable, centralized, signed, or tamper-evident.

- **This is a prototype.** SentryGate demonstrates how a local MCP
  gateway can apply deterministic checks, masking, approval gating, and
  auditability to selected agent tool calls, with an explicit and
  narrow trust boundary. It is not a production gateway and should not
  be read as one.

---

## Cross-references

- **Verification of the behaviors above:** see
  [evaluation.md](evaluation.md) (to be written in a later sub-step) for
  test coverage, static checks, and what was and was not measured.
- **Real MCP-routed traces from Codex Desktop:** see
  [case-study-codex.md](case-study-codex.md) (to be written in a later
  sub-step) for observed decisions on `sentry_read_file("README.md")`,
  `sentry_read_file(".env")`, `sentry_write_file("test.txt", "hello")`,
  and `sentry_run_command("rm -rf tmp")`.
