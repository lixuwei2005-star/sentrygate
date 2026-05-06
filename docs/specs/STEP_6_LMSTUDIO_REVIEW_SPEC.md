# Step 6 LM Studio Local Review Spec

## Goal

Define how SentryGate may use LM Studio as an optional local semantic review
layer for medium-risk tool calls.

The local review layer is advisory and conservative. It can add semantic
context to the deterministic `RiskScorer` result, increase risk, or escalate a
medium-risk approval decision to a block. It must not weaken deterministic
policy outcomes or bypass hard blocks.

This spec creation step defines the behavior only. Backend implementation is
deferred until the future Step 6 implementation.

## Scope

This step includes:

- LM Studio local review design.
- OpenAI-compatible API client design.
- Review prompt design.
- Conservative merge behavior with `RiskScorer`.
- Safe summary requirements for review inputs.
- Failure and fallback behavior.

Out of scope for this spec creation step:

- Backend code changes.

Out of scope for the future Step 6 implementation:

- MCP changes.
- Frontend UI.
- SQLite audit storage.
- Human approval UI or approval API.

## Core Safety Rules

LM Studio review is optional and disabled by default.

`RiskScorer` remains the source of truth for hard blocks. LM Studio must never
override a hard block, and a deterministic `block` result must stay `block`
without requiring LM Studio review.

LM Studio must never reduce a `require_approval` decision to `allow` in the
MVP. It may only:

- Keep the current decision.
- Increase the final risk score.
- Escalate `require_approval` to `block`.
- Add semantic review reasons.

Low-risk `allow` calls do not need LM Studio review.

High-risk `block` calls do not need LM Studio review.

Only medium-risk calls, usually score `40-74`, should be sent to LM Studio.

SentryGate must send only safe summaries to LM Studio. Raw secrets, raw file
contents, raw command output, raw environment variables, raw credential values,
and raw secret mappings must not be included in review requests.

If LM Studio is disabled, unavailable, times out, raises an error, or returns
invalid JSON, SentryGate must fall back to the original `RiskResult`.

## Configuration

The future implementation should read these environment variables:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `LMSTUDIO_REVIEW_ENABLED` | `false` | Enables optional local semantic review. |
| `LMSTUDIO_BASE_URL` | `http://localhost:1234/v1` | Base URL for LM Studio's OpenAI-compatible API. |
| `LMSTUDIO_MODEL` | unset | Optional model name to request from LM Studio. |
| `LMSTUDIO_TIMEOUT_SECONDS` | `5` | Small request timeout for local review. |

Required configuration behavior:

- Review must be disabled unless `LMSTUDIO_REVIEW_ENABLED` is explicitly true.
- `LMSTUDIO_BASE_URL` should default to the local LM Studio OpenAI-compatible
  API base URL.
- `LMSTUDIO_MODEL` may be omitted if the local server accepts requests without
  an explicit model, but the client should include it when configured.
- `LMSTUDIO_TIMEOUT_SECONDS` should be short so local review does not block tool
  calls for long periods.
- Invalid configuration should disable review or fall back safely rather than
  weakening a risk decision.

## OpenAI-Compatible Client Design

The future implementation should add a small client around LM Studio's
OpenAI-compatible chat completions API.

Expected future file:

```text
backend/app/risk/lmstudio_client.py
```

Recommended client interface:

```python
class LMStudioReviewInput(BaseModel):
    tool_name: str
    arguments_summary: str
    original_risk_score: int
    original_decision: Literal["allow", "block", "require_approval"]
    original_reasons: list[str]


class LMStudioReviewOutput(BaseModel):
    risk_score: int
    decision: Literal["allow", "block", "require_approval"]
    reason: str
```

Recommended client method:

```python
class LMStudioReviewClient:
    def review(self, review_input: LMStudioReviewInput) -> LMStudioReviewOutput:
        ...
```

The client should:

- Call the local OpenAI-compatible chat completions endpoint.
- Use the configured base URL, model, and timeout.
- Request a JSON-only response.
- Parse and validate JSON into `LMStudioReviewOutput`.
- Clamp `risk_score` to the inclusive range `0` to `100`.
- Treat missing fields, invalid decisions, invalid scores, non-JSON responses,
  network errors, and timeouts as review failures.
- Never log raw request payloads if they may contain user-controlled content.

The client should not:

- Depend on MCP transport.
- Execute tools.
- Mutate files.
- Access SQLite.
- Implement approval workflows.
- Reimplement deterministic policy rules.

## Review Eligibility

LM Studio review should only run when all of these conditions are true:

- `LMSTUDIO_REVIEW_ENABLED` is true.
- The original `RiskScorer` decision is `require_approval`.
- The original `risk_score` is in the medium-risk range, usually `40-74`.
- A safe masked argument summary is available.
- The tool call is not already a deterministic hard block.

Review should not run when:

- Review is disabled.
- The original decision is `allow`.
- The original decision is `block`.
- The original score is below `40`.
- The original score is `75` or greater.
- Safe summaries cannot be produced.

This keeps low-risk allowed calls fast and avoids sending already blocked
high-risk calls to the model.

## Review Input

The review input should include only safe, masked, bounded summaries:

```python
{
    "tool_name": "run_command",
    "arguments_summary": "command: npm test",
    "original_risk_score": 50,
    "original_decision": "require_approval",
    "original_reasons": ["command_requires_approval_by_default"],
}
```

Required input fields:

- `tool_name`
- Masked or safe argument summary.
- Original risk score.
- Original decision.
- Original reasons.

The safe argument summary should be produced with existing masking and summary
logic before LM Studio review.

The review input must not include:

- Raw secrets.
- Raw secret mappings.
- Raw `.env` contents.
- Raw private keys, tokens, API keys, passwords, cookies, or credentials.
- Raw file contents.
- Raw command output.
- Full environment dumps.
- Tracebacks containing sensitive paths or values.

If the only available input is unsafe raw content, skip LM Studio review and use
the original `RiskResult`.

## Review Prompt Design

The prompt should instruct LM Studio to act as a conservative local security
reviewer for a tool call that has already been evaluated by deterministic
rules.

The prompt should make these constraints explicit:

- The deterministic rule result is authoritative for hard blocks.
- The model must not reduce risk.
- The model must not turn `require_approval` into `allow`.
- The model may keep the current decision.
- The model may increase risk.
- The model may escalate `require_approval` to `block`.
- The model must return valid JSON only.
- The model must use a short, specific reason.

Recommended system message:

```text
You are a conservative local security reviewer for SentryGate tool calls.
Deterministic policy has already reviewed this call. You may not weaken that
result. You may only keep the current decision, increase risk, or escalate
require_approval to block. Return valid JSON only.
```

Recommended user message shape:

```text
Review this tool call summary for semantic risk.

Input:
{
  "tool_name": "...",
  "arguments_summary": "...",
  "original_risk_score": 50,
  "original_decision": "require_approval",
  "original_reasons": ["..."]
}

Return exactly this JSON object:
{
  "risk_score": 65,
  "decision": "require_approval",
  "reason": "short reason"
}

The risk_score must be 0-100. The decision must be one of allow,
require_approval, or block. Do not include markdown.
```

Even though `allow` is a valid schema value, the merge layer will ignore any
model attempt to downgrade `require_approval` to `allow`.

The merge layer remains responsible for enforcing conservative behavior even if
the model returns a weaker decision.

## Review Output

LM Studio should return a JSON object:

```json
{
  "risk_score": 65,
  "decision": "require_approval",
  "reason": "Command may modify dependencies and should remain approval-gated."
}
```

Required output fields:

- `risk_score`: integer from `0` to `100`.
- `decision`: `"allow"`, `"block"`, or `"require_approval"`.
- `reason`: short string.

Validation requirements:

- Missing `risk_score`, `decision`, or `reason` invalidates the review.
- Non-integer risk scores invalidate the review unless safely coercible without
  ambiguity.
- Scores outside `0-100` should be clamped or rejected consistently.
- Unknown decisions invalidate the review.
- Empty reasons should be ignored or replaced with a generic semantic review
  reason.
- Invalid JSON must trigger fallback to the original `RiskResult`.

## Conservative Merge Behavior

The merge layer should combine the original `RiskResult` and optional
`LMStudioReviewOutput` without ever weakening deterministic policy.

Required behavior:

- A hard block from `RiskScorer` stays `block`.
- An `allow` from `RiskScorer` stays `allow` without LM Studio review.
- A `require_approval` from `RiskScorer` can remain `require_approval`.
- A `require_approval` from `RiskScorer` can escalate to `block`.
- LM Studio cannot reduce the final risk score below the original rule score.
- LM Studio cannot reduce the final decision from `require_approval` to
  `allow`.
- Final reasons include original rule reasons plus a semantic review reason
  when a valid review is available.
- Review failures return the original `RiskResult` unchanged.

Recommended merge logic:

```python
def merge_review(
    original: RiskResult,
    review: LMStudioReviewOutput | None,
) -> RiskResult:
    if review is None:
        return original

    if original.decision == "block":
        return original

    if original.decision == "allow":
        return original

    final_score = max(original.risk_score, review.risk_score)
    final_decision = original.decision

    if original.decision == "require_approval" and review.decision == "block":
        final_decision = "block"

    return RiskResult(
        risk_score=final_score,
        decision=final_decision,
        reasons=[
            *original.reasons,
            f"lmstudio_semantic_review: {review.reason}",
        ],
    )
```

If the final score reaches a normal block threshold because LM Studio increased
the score to `75` or higher, the implementation may either:

- Escalate to `block`, matching threshold semantics.
- Keep `require_approval` unless the model explicitly returned `block`.

For MVP, prefer the stricter behavior: a valid LM Studio score of `75` or
higher should escalate the final decision to `block`.

## Failure and Fallback Behavior

LM Studio review must fail closed relative to availability but fail safe
relative to deterministic policy: unavailable semantic review should not block
or allow anything by itself.

Fallback to the original `RiskResult` when:

- Review is disabled.
- The request is ineligible for review.
- LM Studio connection fails.
- LM Studio times out.
- LM Studio returns invalid JSON.
- LM Studio returns missing or invalid fields.
- The review client raises an exception.
- Safe argument summaries cannot be produced.

Fallback should preserve:

- Original risk score.
- Original decision.
- Original reasons.

Fallback should not add noisy semantic review reasons unless useful for local
debugging. If a failure reason is logged, it must be safe and must not include
raw prompts, raw arguments, raw responses, or secrets.

## Integration Point With RiskScorer

The future implementation should keep deterministic scoring as the first step.

Recommended flow:

1. Build a `ToolCall`.
2. Call `RiskScorer`.
3. If the result is `allow`, return it directly.
4. If the result is `block`, return it directly.
5. If the result is medium-risk `require_approval`, build a safe masked review
   input.
6. Call LM Studio only when enabled and eligible.
7. Merge the review conservatively.
8. Return the merged `RiskResult` to the safe tool wrapper.

The safe tool wrapper should continue to execute only when the final decision
is `allow`. Since LM Studio review cannot downgrade medium-risk calls to
`allow`, reviewed calls remain non-executing unless a future approval workflow
is explicitly added in a later step.

## Privacy Requirements

Privacy masking must happen before semantic review input is created.

Required privacy behavior:

- Send safe summaries, not raw payloads.
- Mask secrets before building `arguments_summary`.
- Bound summary length.
- Do not include raw secret mappings.
- Do not include raw file content in prompts.
- Do not include raw command output in prompts.
- Do not include raw traceback text in prompts.
- Do not persist raw prompts or raw model responses in audit logs.

Examples:

```text
Allowed summary:
tool_name=write_file path=docs/specs/example.md content_length=1200

Disallowed summary:
tool_name=write_file content="OPENAI_API_KEY=sk-raw-secret..."
```

```text
Allowed summary:
tool_name=run_command command="npm test"

Disallowed summary:
tool_name=run_command env="AWS_SECRET_ACCESS_KEY=raw-secret"
```

## Audit Considerations

Step 6 does not add SQLite audit storage.

Existing in-memory audit behavior from Step 4 should continue to record the
final merged decision, risk score, and reasons when the safe tool wrapper
returns a result.

Audit records must contain masked summaries only. If semantic review adds a
reason, the reason may be included in audit logs only after validation and
masking.

Audit records should not include:

- Raw LM Studio prompts.
- Raw LM Studio responses.
- Raw secrets.
- Raw secret mappings.
- Raw file contents.
- Raw command output.

## No MCP Changes

Step 6 should not change MCP tool definitions, MCP response shape, MCP startup
configuration, or MCP transport behavior.

The MCP server should continue to delegate through `SafeToolService`. If
`SafeToolService` receives a merged risk result in the future, MCP should simply
return the resulting `ToolExecutionResult` as already defined in Step 5.

## No Approval Workflow

Step 6 must not add approval UI, approval API, approval tokens, delayed
execution, or any mechanism that turns `require_approval` into execution.

For MVP, `require_approval` remains terminal for a tool call.

## Likely Future Implementation Files

Expected implementation files for a later step:

```text
backend/app/risk/lmstudio_client.py
backend/tests/test_lmstudio_review.py
```

These files should not be created or modified as part of Step 6 spec creation.

## Acceptance Criteria

Future implementation should satisfy:

- Unit tests cover disabled LM Studio review.
- Unit tests cover a medium-risk request calling LM Studio.
- Unit tests cover LM Studio escalating `require_approval` to `block`.
- Unit tests cover LM Studio trying to downgrade `require_approval` to `allow`
  and being ignored.
- Unit tests cover invalid JSON fallback.
- Unit tests cover timeout or error fallback.
- Unit tests cover raw secrets not being sent to LM Studio input.
- Low-risk `allow` calls are not sent to LM Studio.
- High-risk `block` calls are not sent to LM Studio.
- A `RiskScorer` hard block cannot be overridden by LM Studio.
- LM Studio cannot lower the final risk score below the original rule score.
- Final reasons include original rule reasons plus a semantic review reason
  when a valid review is available.
- `pytest` passes.
- `ruff` passes.
- `mypy` passes.
