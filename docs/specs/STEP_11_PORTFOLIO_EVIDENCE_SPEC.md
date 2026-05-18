# Step 11: Portfolio Evidence and Project Credibility — Spec

## 1. Purpose

SentryGate currently exists as a working local prototype with MCP-integrated
tool gating, privacy masking, risk scoring, audit logging, an AgentOps
dashboard, and bilingual documentation. The remaining gap is **credibility for
a portfolio / internship reviewer**: a reader of the GitHub repo can see *what*
is implemented, but cannot yet see *why* the design looks the way it does,
*how* it was verified, or *what real Codex MCP behavior* was observed.

This step defines the documentation that closes that gap. It does **not**
change backend code, dashboard code, tests, or the README. It only specifies
the future documents and their required content, wording constraints, and
acceptance criteria.

## 2. Scope

This spec defines four future artifacts to be created in later steps:

1. `docs/design-decisions.md`
2. `docs/evaluation.md`
3. `docs/case-study-codex.md`
4. `docs/assets/dashboard-screenshot.png` (or a placeholder instruction if a
   screenshot is not yet captured)

The README may later be updated to link to these documents, but **that link
update is explicitly out of scope for Step 11 spec authoring**.

## 3. Non-Goals

- No backend code changes (no edits under `sentrygate/`, `mcp_server/`, etc.).
- No dashboard code changes (no edits under the Streamlit app).
- No test changes.
- No README changes (English or Chinese).
- No new runtime dependencies.
- No marketing claims, no invented metrics, no benchmark numbers that have
  not actually been measured.

## 4. Required Future Files

### 4.1 `docs/design-decisions.md`

A reviewer-facing document that explains the architectural and policy
decisions behind SentryGate. It should be readable in roughly 5–10 minutes by
someone who has skimmed the README but has not read the code.

**Required sections / questions answered:**

1. **Why MCP is the protected boundary.**
   - SentryGate enforces policy at the MCP tool-call interface (`sentry_read_file`,
     `sentry_write_file`, `sentry_run_command`).
   - Calls that pass through MCP are subject to PrivacyMasker, RiskScorer,
     SafeToolService, and audit logging.
   - This is a *boundary-style* control: it protects what flows through the
     boundary, not what happens outside of it.

2. **Why SentryGate cannot protect Codex built-in internal tools.**
   - Codex Desktop ships with its own internal tool implementations
     (e.g., its own file read / shell). Those bypass MCP entirely.
   - SentryGate has no visibility into, and no authority over, those internal
     calls. The doc must state this limitation plainly.

3. **Why deterministic rules run before LM Studio review.**
   - Hard rules (path blocks, dangerous command patterns) are fast,
     auditable, and reproducible.
   - LM Studio review is optional, local, and best-effort; it is treated as
     advisory signal, not as authoritative policy.

4. **Why LM Studio cannot override a hard block.**
   - A model suggestion of "this looks fine" must not be able to unlock a
     path or command that deterministic policy classified as `block`.
   - This preserves a clear, testable trust hierarchy: rules > model.

5. **Why `.env` is blocked by path, not read-then-mask.**
   - Even with masking, *reading* `.env` exposes the file's existence,
     structure, and field names to the agent transcript.
   - Path-level block is a stronger, simpler invariant than relying on
     masking to scrub everything sensitive after the fact.

6. **Why `write_file` and `run_command` default to `require_approval`.**
   - Mutating actions have larger blast radius than reads.
   - Defaulting to human-in-the-loop matches the "selected tool calls" trust
     model: the user is the final authority on writes and shell execution.

7. **Why audit logs store masked summaries only.**
   - The audit store is meant to support review and demos, not forensic
     reconstruction of raw secrets.
   - Storing masked summaries avoids creating a second copy of sensitive
     data on disk.

8. **Why the dashboard reads JSONL instead of the in-memory audit store.**
   - JSONL is durable across process restarts and across Codex sessions.
   - It decouples the dashboard from the MCP server's lifecycle and lets the
     dashboard run as a separate, read-only viewer.

9. **Why the dashboard is read-only and restricted to `.sentrygate/*.jsonl`.**
   - The dashboard is an observability surface, not a control plane.
   - Restricting its file access reduces the risk of the viewer itself
     becoming a tool for reading arbitrary files.

10. **Trade-offs and limitations.**
    - MCP-only boundary ≠ full sandboxing.
    - Deterministic rules can have false positives and false negatives.
    - Masking is regex-driven and will miss novel secret formats.
    - LM Studio review is local, optional, and not a security guarantee.
    - The project is a prototype intended to demonstrate design thinking,
      not a production gateway.

### 4.2 `docs/evaluation.md`

A factual, conservative report of how SentryGate was verified. No invented
metrics, no marketing percentages.

**Required sections:**

1. **Test suite summary.**
   - How tests are organized (unit + integration).
   - The latest `pytest` collected/passing count *as actually observed at the
     time of writing*. The doc must record the date of measurement and the
     command used (e.g., `pytest -q`).

2. **Static checks.**
   - Latest `ruff` result (clean / issues, with date).
   - Latest `mypy` result (clean / issues, with date).
   - If a check was not run, the doc must say "not run" rather than assert
     a clean result.

3. **Privacy masking coverage.**
   - List the masker rule families that have explicit tests (e.g., email,
     API-key-like tokens, generic high-entropy strings if present).
   - Explicitly note categories *not* covered.

4. **Risk scoring coverage.**
   - List the rule categories with tests (path-based blocks, command-pattern
     blocks, write/exec require-approval defaults).
   - Note what is intentionally out of scope (e.g., semantic intent
     classification).

5. **Safe tool behavior coverage.**
   - Tests covering allow / mask / block / require_approval paths through
     `SafeToolService`.
   - Tests covering audit record emission (trace_id, span_id, latency_ms,
     decision, reason).

6. **MCP integration verification.**
   - Which MCP tool calls were manually exercised from Codex Desktop.
   - The exact tool names invoked and the observed decisions.
   - This section feeds into, and cross-links to, `case-study-codex.md`.

7. **Dashboard verification.**
   - That the Streamlit dashboard loads with an empty store.
   - That it loads with a populated JSONL.
   - That it refuses paths outside `.sentrygate/`.
   - That metric summaries match the underlying JSONL.

8. **Manually tested vs. not measured.**
   - Manually tested: end-to-end Codex flow, dashboard rendering, restart
     persistence of JSONL.
   - Not measured: throughput, latency under load, model-review accuracy,
     "cost reduction", "incident reduction", or any other number that was
     never benchmarked. The doc must explicitly *decline* to state such
     numbers.

### 4.3 `docs/case-study-codex.md`

A narrative-style document showing **real** MCP-routed tool calls made from
Codex Desktop against SentryGate, with the observed decisions.

**Required cases (all are MCP-routed; none touch Codex built-in tools):**

1. `sentry_read_file("README.md")`
   - Expected decision: `allow`.
   - Expected behavior: file content is returned with email addresses and
     API-key-like tokens replaced by mask tokens.
   - Audit record: trace_id, span_id, latency_ms, decision=`allow`,
     masked-field count.

2. `sentry_read_file(".env")`
   - Expected decision: `block`.
   - Expected reason: `sensitive_path`.
   - No file content is returned to the model.

3. `sentry_write_file("test.txt", "hello")`
   - Expected decision: `require_approval`.
   - Expected behavior: nothing is written until the operator approves.
   - The case must explicitly note that the absence of a write is the
     correct outcome.

4. `sentry_run_command("rm -rf tmp")`
   - Expected decision: `block`.
   - Expected reason: matches a dangerous-command rule.

**Required framing in this document:**

- State up front that these are **MCP-routed** tool calls, invoked through
  SentryGate's `sentry_*` tools.
- State explicitly that **Codex Desktop's built-in internal tools are not
  routed through SentryGate** and therefore are not covered by these
  decisions. This boundary must not be blurred.
- Use phrasing like "demonstrates", "selected tool calls", "observed
  behavior on a local machine"; do not generalize to "Codex is now safe".

### 4.4 `docs/assets/dashboard-screenshot.png`

The README can later display a dashboard preview, but this spec only defines
the plan:

- **Target path:** `docs/assets/dashboard-screenshot.png`.
- **Preferred content:** the AgentOps dashboard showing a non-empty metrics
  summary and at least one of each decision type (`allow`, `block`,
  `require_approval`) in the recent-events view, with no real secrets
  visible (masked values are fine and in fact preferred).
- **If no screenshot exists yet:** create a short instruction note in the
  spec (and later in `docs/assets/README.md` once that file is added in a
  future step) describing how to capture it:
  1. Run the local demo script to populate `.sentrygate/audit.jsonl` with a
     mix of allow / block / require_approval events.
  2. Start the Streamlit dashboard pointed at that JSONL.
  3. Capture the browser viewport at a sensible width (e.g., 1440px).
  4. Save as `docs/assets/dashboard-screenshot.png`.
  5. Confirm no real secrets, hostnames, or personal email addresses are
     visible before committing.

Until the screenshot is captured, the README must not reference the image
path, and no doc may claim a screenshot exists.

## 5. Wording Constraints (Applies to All Three Docs)

The following claims are **forbidden** in any doc produced by this step:

- "Production-grade security."
- "Enterprise-ready governance."
- "Full sandboxing."
- "Complete attack prevention" or "blocks all prompt injection".
- Any statement implying SentryGate controls Codex's built-in internal tools.
- Any quantitative claim that was not actually measured (e.g., "reduces
  incidents by N%", "cuts cost by N%", "improves accuracy by N%").

Preferred, credible wording:

- "prototype"
- "local"
- "MCP-routed"
- "selected tool calls"
- "demonstrates"
- "observed on a local machine"
- "best-effort, advisory"
- "boundary-style control, not full sandboxing"

## 6. Cross-References

The three documents should cross-link:

- `design-decisions.md` should reference `evaluation.md` when claiming that
  a behavior is tested.
- `evaluation.md` should reference `case-study-codex.md` for the MCP
  integration section.
- `case-study-codex.md` should reference `design-decisions.md` for the
  rationale behind each decision (e.g., why `.env` is path-blocked).

This keeps each document focused while letting the reviewer follow the
reasoning end-to-end.

## 7. Acceptance Criteria

Step 11 spec authoring is complete when:

- [x] `docs/specs/STEP_11_PORTFOLIO_EVIDENCE_SPEC.md` exists.
- [x] The spec defines the required content of `docs/design-decisions.md`.
- [x] The spec defines the required content of `docs/evaluation.md`.
- [x] The spec defines the required content of `docs/case-study-codex.md`.
- [x] The spec defines the dashboard screenshot plan, including the
      fallback instruction when no screenshot exists yet.
- [x] The spec preserves the MCP-only boundary in every required document.
- [x] The spec forbids the overclaiming wording listed in §5.
- [x] No backend code was changed in this step.
- [x] No dashboard code was changed in this step.
- [x] No README was changed in this step.
- [x] No tests were changed in this step.

## 8. Out of Scope / Deferred

- Actually writing `design-decisions.md`, `evaluation.md`, and
  `case-study-codex.md`. Those are separate later steps.
- Capturing the dashboard screenshot.
- Updating the README (English or Chinese) to link to the new docs.
- Any change to the policy engine, masker, scorer, audit store, MCP server,
  or dashboard.
