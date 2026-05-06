# SentryGate Demo Output

This document shows how to run the local SentryGate demo and how to explain the
output in a portfolio or interview setting.

The demo uses a temporary workspace and fake secrets only. It calls
`SafeToolService` directly, so it does not require Codex or a running MCP
client. The same security boundary still matters: SentryGate protects only tool
calls routed through its own service or MCP tools.

## Run the Demo

From the `backend` directory:

```powershell
cd backend
uv run python scripts/demo_sentrygate.py
```

The script creates a temporary workspace with:

- `public_note.txt`
- `.env`
- `src/app.py`

The fake secrets are present in demo files, but raw secret values should never
appear in terminal output.

## Sample Output

Temporary paths vary by machine, so the workspace path is normalized here.

```text
SentryGate local demo
Workspace: <temporary workspace>

Fake secrets are present in demo files, but terminal output
is checked before printing and must never expose them.

1. read_file masks secrets
decision: allow
ok: true
risk_score: 10
reasons: safe_file_read
output:
Demo note
Contact: [EMAIL_001]
Fake API key: [API_KEY_001]
masked_findings: API_KEY=[API_KEY_001], EMAIL=[EMAIL_001]

2. .env read is blocked
decision: block
ok: false
risk_score: 100
reasons: sensitive_path
error: operation_blocked

3. write_file requires approval and does not write
decision: require_approval
ok: false
risk_score: 50
reasons: write_file_requires_approval
error: operation_requires_approval
generated.txt exists after call: false

4. list_directory is allowed
decision: allow
ok: true
risk_score: 10
reasons: safe_directory_list
output:
[file] .env
[file] public_note.txt
[dir] src

5. normal run_command requires approval and does not execute
decision: require_approval
ok: false
risk_score: 50
reasons: run_command_requires_approval
error: operation_requires_approval

6. dangerous run_command is blocked
decision: block
ok: false
risk_score: 100
reasons: dangerous_rm_recursive_force
error: operation_blocked

Audit events
1. tool_name: read_file
   decision: allow
   executed: true
   risk_score: 10
   reasons: safe_file_read
   arguments_summary: path=public_note.txt
   output_summary: read_file succeeded; chars=99; masked_findings=2
   masked_findings: API_KEY=[API_KEY_001], EMAIL=[EMAIL_001]
2. tool_name: read_file
   decision: block
   executed: false
   risk_score: 100
   reasons: sensitive_path
   arguments_summary: path=.env
   output_summary: operation_blocked
3. tool_name: write_file
   decision: require_approval
   executed: false
   risk_score: 50
   reasons: write_file_requires_approval
   arguments_summary: path=generated.txt; content_chars=22
   output_summary: operation_requires_approval
4. tool_name: list_directory
   decision: allow
   executed: true
   risk_score: 10
   reasons: safe_directory_list
   arguments_summary: path=.
   output_summary: list_directory succeeded; entries=3; listing=[file] .env
[file] public_note.txt
[dir] src
5. tool_name: run_command
   decision: require_approval
   executed: false
   risk_score: 50
   reasons: run_command_requires_approval
   arguments_summary: command=echo sentrygate-demo-command
   output_summary: operation_requires_approval
6. tool_name: run_command
   decision: block
   executed: false
   risk_score: 100
   reasons: dangerous_rm_recursive_force
   arguments_summary: command=rm -rf tmp
   output_summary: operation_blocked
```

## Scenario Notes

### Safe Read Masks Secrets

The demo reads `public_note.txt` through `SafeToolService`.

Expected decision: `allow`.

The operation executes, but output is passed through `PrivacyMasker` before it
is printed. The email and API-key-like value are replaced with stable mask
tokens such as `[EMAIL_001]` and `[API_KEY_001]`.

This demonstrates common-pattern masking in the prototype. It does not claim
complete detection of every possible secret format.

### `.env` Read Blocked

The demo requests `.env`.

Expected decision: `block`.

The file content is not returned. The result shows `operation_blocked` with the
`sensitive_path` reason.

This demonstrates deterministic blocking for sensitive file paths routed
through SentryGate.

### Write Requires Approval

The demo requests a write to `generated.txt`.

Expected decision: `require_approval`.

The write does not execute because the current prototype does not include a
human approval workflow. The demo verifies this with:

```text
generated.txt exists after call: false
```

### List Directory Allowed

The demo lists the temporary workspace root.

Expected decision: `allow`.

The operation executes and returns file and directory names only. Listing a
directory is different from reading sensitive file contents; `.env` can appear
as a filename while its contents remain blocked.

### Normal Command Requires Approval

The demo requests:

```text
echo sentrygate-demo-command
```

Expected decision: `require_approval`.

The command does not execute while no approval workflow exists. The output shows
`operation_requires_approval`, not command stdout.

### Dangerous Command Blocked

The demo passes this command string into `SafeToolService`:

```text
rm -rf tmp
```

Expected decision: `block`.

The command does not execute. This demonstrates rule-based blocking for a known
dangerous pattern in the prototype. It does not claim to detect every possible
dangerous command form.

### Audit Events Printed

At the end, the demo prints in-memory audit events for each SentryGate tool
call.

Each event includes the tool name, decision, execution status, risk score,
reasons, argument summary, and output summary. Audit output uses masked values
and summaries, not raw fake secrets.

The current in-memory audit store is useful for local demos and development
inspection. It is not durable enterprise audit infrastructure.
