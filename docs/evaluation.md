# SentryGate Evaluation

This document is a factual, conservative report of how the SentryGate
prototype was verified. It is meant for a reviewer who has read
[README.md](../README.md) and [design-decisions.md](design-decisions.md)
and now wants to know *which behaviors were checked, by what means, and
what was deliberately not measured*.

No metric in this document was invented. Every number is either:

- an observed result of a command run locally on the author's machine,
  with the command shown so a reviewer can re-run it; or
- explicitly marked as **not measured** so the reader does not infer a
  number that does not exist.

Scope reminder before we begin: SentryGate evaluates *MCP-routed*
`sentry_*` tool calls only. Calls that never reach the SentryGate MCP
server — including Codex Desktop's built-in internal tools — are
outside the boundary this document evaluates, by design. See
[design-decisions.md §2](design-decisions.md) for the reasoning.

---

## 1. Evaluation summary

**What was evaluated.** Three layers of verification:

1. *Automated checks.* The backend test suite, `ruff` lint, and `mypy`
   static type checking, all run from the `backend/` directory.
2. *Local manual exercise.* The bundled demo script
   (`scripts/demo_sentrygate.py`) and the Streamlit AgentOps dashboard.
3. *MCP-routed manual exercise.* `sentry_*` tool calls invoked from
   Codex Desktop against a running SentryGate MCP server, with audit
   events read back from `.sentrygate/*.jsonl`.

**Evidence included.** Observed `pytest`, `ruff`, and `mypy` results;
the canonical demo output captured in
[demo-output.md](demo-output.md); and a small set of MCP-routed cases
exercised live from Codex Desktop and recorded in §7.

**What is not claimed.** This document does not claim production-grade
security, full sandboxing, complete secret detection, complete
command-risk detection, throughput numbers, latency under load, or any
form of cost / incident reduction. See §9 for the explicit list.

---

## 2. Test suite summary

**Command used.**

```powershell
cd backend
uv run pytest
```

**Observed result (latest local run).**

- 114 tests passed, 0 failed.

The tests live under `backend/tests/`. They are organized one file per
behavioral surface; the table below maps each file to the property it
verifies, so a reviewer can read the test instead of trusting this
document.

| Test file                          | Category                       | What it checks |
|------------------------------------|--------------------------------|----------------|
| `test_health.py`                   | FastAPI health endpoint        | `/health` returns 200 with the SentryGate identity payload. |
| `test_privacy_masker.py`           | Privacy masker                 | Rule families, stable tokenization, no-raw-secret invariant on serialized output. |
| `test_risk_scorer.py`              | Risk scorer                    | Path policy, dangerous command policy (POSIX + PowerShell), behavior tracking. |
| `test_safe_tools.py`               | Safe tool service              | `allow` / `block` / `require_approval` execution, audit record shape, defense-in-depth against a permissive scorer. |
| `test_mcp_server.py`               | MCP server adapter             | Workspace-root and audit-log-path resolution, tool registration, end-to-end pass-through to `SafeToolService`. |
| `test_lmstudio_review.py`          | LM Studio semantic review      | Disabled by default, conservative merge, escalation only, no raw secrets sent. |
| `test_jsonl_audit_store.py`        | JSONL audit store              | Append, list, malformed-line skip, no raw secret on disk. |
| `test_audit_metrics.py`            | Audit metrics                  | `summarize_audit_events` counts, top-reason limit, empty-input defaults. |
| `test_dashboard_data.py`           | Dashboard data helpers         | Path validation, missing/empty handling, dataframe shape, latency series, sort order. |

The tests are unit-grain. They do not require Codex Desktop, an MCP
client, or LM Studio to be running.

---

## 3. Static checks

**Commands used.**

```powershell
cd backend
uv run ruff check .
uv run mypy app dashboard
```

**Observed results (latest local run).**

- `ruff check .` — passed (no issues).
- `mypy app dashboard` — passed (no issues).

`mypy` is configured with `disallow_untyped_defs = true` in
`backend/pyproject.toml`, and its target set explicitly includes both
the backend (`app`) and the dashboard (`dashboard`). The clean result
covers both.

---

## 4. Privacy masking coverage

Rule families verified by `backend/tests/test_privacy_masker.py`:

- Email addresses → `[EMAIL_NNN]`.
- OpenAI-style `sk-…` API keys → `[API_KEY_NNN]`.
- GitHub tokens (`ghp_…`, `github_pat_…`) → `[GITHUB_TOKEN_NNN]`.
- JWT-like three-segment tokens → `[JWT_NNN]`.
- Database URLs (`postgres://`, `postgresql://`, `mysql://`) →
  `[DATABASE_URL_NNN]`.
- PEM `-----BEGIN PRIVATE KEY-----` blocks → `[PRIVATE_KEY_NNN]`.
- `.env`-style `KEY=value` pairs (quoted, unquoted, `export`-prefixed,
  and generic non-pattern values) → `[ENV_SECRET_NNN]`, with the
  variable name preserved and empty values not masked.

Stable-tokenization properties verified:

- The same secret value receives the same token within one input.
- The same secret value receives the same token across multiple calls
  within one masker session.
- Different secret values receive different tokens.
- Non-sensitive text is returned unchanged.
- `MaskingResult.model_dump_json()` never contains the raw secret
  string.

**Not guaranteed.** Vendor key formats not in the rule set above,
novel high-entropy strings without a known prefix, partially obfuscated
secrets (e.g., split across lines, base64-wrapped), and secrets
embedded in arbitrary natural-language phrasing. The masker is a
regex-driven best-effort scrub; it is not a proof of complete secret
detection.

---

## 5. Risk scoring coverage

Verified by `backend/tests/test_risk_scorer.py`:

*Read paths.*

- Safe `read_file` → `allow`, reason `safe_file_read`, risk score < 40.
- Sensitive paths (`.env`, `.aws/credentials`, `id_rsa`, and sensitive
  names appearing as path components) → `block`, reason
  `sensitive_path`, risk score 100.
- Relative path traversal (`../outside.txt`) and absolute paths
  outside the workspace root → `block`, reason
  `path_outside_workspace`.

*Write paths.*

- `write_file` → `require_approval`, reason
  `write_file_requires_approval`, risk score 50.

*Command paths.*

- Normal `run_command` (e.g., `pytest --version`) →
  `require_approval`, reason `run_command_requires_approval`.
- Dangerous POSIX commands → `block`. Verified patterns include
  `rm -rf`, `curl … | bash`, `sudo`, `chmod 777`, `dd`, and `mkfs`,
  including absolute-path variants such as `/bin/rm -rf …` and
  `/usr/bin/sudo …`.
- Dangerous PowerShell commands → `block`. Verified patterns include
  `Remove-Item -Recurse -Force` and its aliases (`ri`, `rmdir`, `del`,
  `erase`), partial-flag forms (`-rec -fo`), `Invoke-WebRequest … | iex`,
  `iwr … | iex`, `Start-Process`, `Format-Volume`, and
  `Set-ExecutionPolicy Bypass`.
- PowerShell substring false-positives (e.g., the literal text
  `"Set-ExecutionPolicy Bypass"` inside an `echo` argument) are *not*
  blocked, confirming the scorer parses tokens rather than scanning
  raw substrings.

*Behavior tracking.*

- Twenty-one rapid `read_file` calls within one session escalate the
  twenty-first call to `require_approval`, reason
  `many_recent_read_file_calls`.
- Unknown tool calls do not pollute the behavior tracker.
- Invalid argument shapes (e.g., non-string `path`) do not pollute the
  behavior tracker.

**Not guaranteed.** Obfuscated or encoded shell forms, non-English
command variants, novel destructive utilities not on the rule list,
and any semantic-intent classification beyond pattern matching. The
rule set in `RiskScorer._detect_command_risk()` is conservative, not
exhaustive — see [design-decisions.md §10](design-decisions.md).

---

## 6. Safe tool and audit coverage

Verified by `backend/tests/test_safe_tools.py`,
`backend/tests/test_jsonl_audit_store.py`, and
`backend/tests/test_lmstudio_review.py`.

*Execution order.*

- `RiskScorer.score_tool_call()` is invoked before any execution. The
  `subprocess.run` tests assert this by monkey-patching
  `subprocess.run` to raise on call: every `block` and
  `require_approval` test passes, proving the command was never
  executed.

*`block` path.*

- `sentry_read_file(".env")` returns `ok=False`, `output is None`,
  `error="operation_blocked"`. The file is not opened.
- `sentry_run_command("rm -rf tmp")` returns `decision="block"` with
  reason `dangerous_rm_recursive_force`. The command is not executed.
- Workspace-boundary breach is blocked even when paired with a
  permissive risk scorer (defense-in-depth).

*`require_approval` path.*

- `sentry_write_file("notes.txt", …)` returns
  `decision="require_approval"`, `error="operation_requires_approval"`,
  and the target file does not exist after the call.
- `sentry_run_command("pytest --version")` returns
  `decision="require_approval"` and does not invoke `subprocess.run`.

*`allow` path with masked output.*

- A `read_file` over a workspace file containing
  `admin@example.com` returns `output="Contact [EMAIL_001]"`. The
  raw email never appears in the result, nor in the serialized audit
  event.

*Audit record shape.*

- Masked summaries only: `arguments_summary` and `output_summary` are
  passed through `PrivacyMasker` and bounded in length; raw secret
  strings never appear in `event.model_dump_json()`.
- `trace_id` mirrors the supplied `session_id`; `span_id`,
  `started_at`, `ended_at`, and `latency_ms` are populated for
  executed calls. All trace/span fields are optional and default to
  `None` when not provided.
- The JSONL audit store on disk does not contain raw secret strings:
  `test_jsonl_audit_store_does_not_persist_raw_secrets` writes a
  fake `sk-test123` through a `run_command` argument and asserts the
  resulting JSONL file contains `[API_KEY_001]` but not the raw
  secret.

*LM Studio review.*

- Disabled by default (`LMSTUDIO_REVIEW_ENABLED` unset → `enabled=False`).
- Never called for an original `allow` or `block`; only invoked when
  the deterministic decision is `require_approval`.
- Cannot weaken a decision: a model-returned `allow` is discarded;
  the original `require_approval` stands.
- Can escalate `require_approval` → `block` when the model returns a
  high risk score (≥ 75) or `decision="block"`.
- Raw secrets in command arguments are masked *before* the request
  is sent to LM Studio; model-returned reason text is masked again
  before it reaches the audit event.
- Network failures, malformed JSON, and bad-schema responses all
  fall back to the original deterministic result.

---

## 7. MCP integration verification

All cases below are **MCP-routed** `sentry_*` tool calls, invoked from
Codex Desktop against a locally running SentryGate MCP server. None of
them touch Codex Desktop's built-in internal tools, which remain
outside the SentryGate boundary by design
(see [design-decisions.md §2](design-decisions.md)). Narrative traces
will live in [case-study-codex.md](case-study-codex.md) (to be written
in a later sub-step).

| # | MCP call                                       | Observed decision     | Observed behavior |
|---|------------------------------------------------|------------------------|-------------------|
| 1 | `sentry_read_file("README.md")`                | `allow`                | File content returned with email addresses and an OpenAI-style API key replaced by mask tokens; audit event written to `.sentrygate/*.jsonl` with masked summaries. |
| 2 | `sentry_read_file(".env")`                     | `block`                | Reason `sensitive_path`. No file content returned to the model. Audit event recorded with `executed=false`. |
| 3 | `sentry_write_file("test.txt", "hello")`       | `require_approval`     | Target file `test.txt` does **not** exist after the call. The absence of the write is the correct outcome under the current "decision, not workflow" approval model. |
| 4 | `sentry_run_command("rm -rf tmp")`             | **pending live verification** | Not yet recorded as a live Codex Desktop trace at the time of writing. The same input is exercised end-to-end by the automated tests (`test_dangerous_run_command_is_blocked_and_does_not_execute` and the `test_risk_scorer.py` dangerous-command suite) and by the local demo (see [demo-output.md](demo-output.md) scenario 6), which return `block` with reason `dangerous_rm_recursive_force` and do not execute. |

When the MCP server is started with `--audit-log-path`, these
MCP-routed calls are recorded as JSONL audit events with masked
summaries. The live Codex Desktop checks above verified the decisions
and returned outputs; JSONL persistence is covered by the JSONL audit
store and dashboard tests.

---

## 8. Dashboard verification

*Static helpers.* Verified by `backend/tests/test_dashboard_data.py`:

- A path that does not end in `.jsonl` is rejected without opening
  the file. The monkey-patched `Path.open` would raise on any access,
  and the test passes — proving validation happens before IO.
- A path that points to a directory is rejected without opening it.
- A missing file produces `missing=True`, `empty=True`, and no error.
- An empty file produces `empty=True` with no events and no error.
- A JSONL stream that mixes valid events, malformed JSON, and
  invalid-shape JSON returns only the valid events and reports a
  correct `skipped` count.
- The recent-events dataframe has the documented column shape, sorts
  newest-first, caps to the requested limit, and counts masked
  findings per row.
- Risk-score buckets cover boundaries `0-19`, `20-39`, `40-59`,
  `60-79`, `80-100`.
- `has_latency_data()` correctly distinguishes empty vs. populated
  latency, and `build_latency_series()` filters out `None` latency
  rows and sorts ascending.

*JSONL contract.* Verified by `backend/tests/test_jsonl_audit_store.py`:
events are persisted across appends, malformed lines are skipped on
read, and the on-disk file never contains raw secret strings even when
the underlying tool call carried one.

*Streamlit smoke check.*

**Command used.**

```powershell
cd backend
uv run streamlit run dashboard/agentops_dashboard.py
```

**Observed result (latest local run).**

- Streamlit server started successfully.
- HTTP 200 returned from the local dashboard URL.
- The dashboard rendered the metrics and recent-events views against
  a populated `.sentrygate/audit_events.jsonl`.

This is a smoke check, not a load test or a UX evaluation.

---

## 9. What was not measured

The following are **not measured** and **not claimed** by this
prototype. They are listed here so the reader cannot mistake silence
for an implicit claim:

- Throughput under load — not measured.
- Latency under load — not measured. (Per-call `latency_ms` is
  recorded on individual audit events; that is not a load benchmark.)
- Cost reduction — not measured, not claimed.
- Review-cost reduction — not measured, not claimed.
- Incident reduction — not measured, not claimed.
- Production security guarantees — not claimed. SentryGate is a
  local prototype; see [design-decisions.md §10](design-decisions.md).
- Complete secret detection — not claimed. The masker is regex-driven
  and best-effort; see §4.
- Complete command-risk detection — not claimed. The rule set is
  conservative; see §5.
- Real-world attack prevention — not claimed.
- Coverage of Codex Desktop built-in internal tools — **outside the
  boundary** by design. SentryGate evaluates MCP-routed `sentry_*`
  calls only. See [design-decisions.md §2](design-decisions.md).

---

## 10. Reproducibility commands

To re-run the local validation captured in this document, from the
repository root:

```powershell
cd backend
uv run pytest
uv run ruff check .
uv run mypy app dashboard
uv run python scripts/demo_sentrygate.py
uv run streamlit run dashboard/agentops_dashboard.py
```

The MCP server itself is started separately (see
[README.md](../README.md) "Run the MCP Server" and "AgentOps
Dashboard"), with an explicit `--workspace-root` and, for §7's MCP
cases, an `--audit-log-path` pointing under `.sentrygate/`. The
dashboard then reads `backend/.sentrygate/*.jsonl` by default.

---

## Cross-references

- [design-decisions.md](design-decisions.md) — the rationale behind
  each enforced behavior; this document evaluates whether those
  decisions hold under the tests and commands above.
- [case-study-codex.md](case-study-codex.md) (to be written in a
  later sub-step) — narrative traces of the MCP-routed cases recorded
  in §7.
- [demo-output.md](demo-output.md) — canonical output from
  `scripts/demo_sentrygate.py`, including the local-demo decision for
  every scenario referenced above.
