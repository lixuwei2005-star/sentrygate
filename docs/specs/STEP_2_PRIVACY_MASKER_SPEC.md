# Step 2 Privacy Masker Spec

## Goal

Implement a stable tokenization privacy masking engine for SentryGate.

The privacy masker should detect sensitive values in tool inputs, tool outputs, and future audit payloads, then replace those values with deterministic placeholder tokens for the duration of one masking session.

This step defines the behavior only. Backend implementation is deferred.

## Inputs and Outputs

### Inputs

The privacy masking engine should accept plain text content that may contain sensitive values.

Examples include:

- File contents read from the workspace.
- Command stdout or stderr.
- Tool request payloads.
- Tool response payloads.
- Audit event fields before persistence.

### Outputs

The privacy masking engine should return:

- Masked text with sensitive values replaced by stable tokens.
- A session-local mapping of raw sensitive values to generated tokens, kept in memory only.

The raw-to-token mapping is for internal masking consistency and must not be written to audit logs by default.

## Sensitive Patterns

The masking engine should detect at least the following sensitive patterns:

- Email addresses.
- OpenAI-style API keys starting with `sk-`.
- GitHub tokens starting with `ghp_` or `github_pat_`.
- JWT-like tokens with three base64url-style segments separated by dots.
- Database URLs starting with schemes such as `postgres://`, `postgresql://`, or `mysql://`.
- Private key blocks, including PEM-style blocks such as `-----BEGIN PRIVATE KEY-----`.
- `.env`-style secrets such as `API_KEY=value`, `SECRET_KEY=value`, `TOKEN=value`, or `DATABASE_URL=value`.

Pattern detection should favor avoiding raw secret leakage over perfect classification.

## Stable Tokenization Behavior

Masking must be stable within one masking session:

- The same raw secret maps to the same token every time it appears in that session.
- Different raw secrets map to different tokens.
- Token counters are scoped by detected secret type.
- Tokenization does not need to be stable across process restarts or separate masking sessions.

Token examples:

```text
[EMAIL_001]
[API_KEY_001]
[GITHUB_TOKEN_001]
[JWT_001]
[DATABASE_URL_001]
[PRIVATE_KEY_001]
[ENV_SECRET_001]
```

For `.env`-style key-value lines, preserve the key name when possible and mask only the value.

Example behavior:

```text
Input:
Contact admin@example.com and backup admin@example.com.

Output:
Contact [EMAIL_001] and backup [EMAIL_001].
```

```text
Input:
DATABASE_URL=postgres://user:pass@localhost:5432/app
OPENAI_API_KEY=sk-test123

Output:
DATABASE_URL=[DATABASE_URL_001]
OPENAI_API_KEY=[API_KEY_001]
```

## Audit Safety

Raw secrets must not be written to audit logs by default.

Audit events should store masked text and token identifiers rather than raw sensitive values. Masked text is considered safe to log by default because detected secrets have been replaced with non-secret placeholders.

If future debugging features require raw secret access, they must be explicitly opt-in, clearly documented, and excluded from default behavior.

## Files Likely to Be Implemented Later

Expected implementation files for a later step:

```text
backend/app/privacy/patterns.py
backend/app/privacy/masker.py
backend/tests/test_privacy_masker.py
```

## Acceptance Criteria

- Unit tests cover each sensitive pattern listed in this spec.
- The same secret maps to the same token within one masking session.
- Different secrets get different tokens.
- Non-sensitive text stays unchanged.
- Raw secrets are not written to audit logs by default.
- Masked text is safe to log by default.
- `pytest` passes.
- `ruff` passes.
- `mypy` passes.
