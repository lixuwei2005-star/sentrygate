import sys
from pathlib import Path
from tempfile import TemporaryDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.audit.models import AuditEvent  # noqa: E402
from app.audit.store import InMemoryAuditStore  # noqa: E402
from app.privacy.masker import MaskingFinding  # noqa: E402
from app.tools.models import ToolExecutionResult  # noqa: E402
from app.tools.safe_tools import SafeToolService  # noqa: E402

SESSION_ID = "demo-session"

FAKE_EMAIL = "demo@example.com"
FAKE_PUBLIC_API_KEY = "sk-demo1234567890abcdef1234567890abcdef1234567890"
FAKE_ENV_API_KEY = "sk-fakeenv1234567890abcdef1234567890abcdef123456"
FAKE_DATABASE_URL = "postgres://demo:password@localhost:5432/sentrygate_demo"

RAW_FAKE_SECRETS = (
    FAKE_EMAIL,
    FAKE_PUBLIC_API_KEY,
    FAKE_ENV_API_KEY,
    FAKE_DATABASE_URL,
)


def main() -> None:
    with TemporaryDirectory(prefix="sentrygate-demo-") as temp_dir:
        workspace = Path(temp_dir) / "workspace"
        workspace.mkdir()
        create_demo_workspace(workspace)

        audit_store = InMemoryAuditStore()
        service = SafeToolService(workspace_root=workspace, audit_store=audit_store)

        emit(
            "\n".join(
                [
                    "SentryGate local demo",
                    f"Workspace: {workspace}",
                    "",
                    "Fake secrets are present in demo files, but terminal output",
                    "is checked before printing and must never expose them.",
                ]
            ),
            RAW_FAKE_SECRETS,
        )

        result = service.sentry_read_file("public_note.txt", session_id=SESSION_ID)
        print_result("1. read_file masks secrets", result, RAW_FAKE_SECRETS)

        result = service.sentry_read_file(".env", session_id=SESSION_ID)
        print_result("2. .env read is blocked", result, RAW_FAKE_SECRETS)

        result = service.sentry_write_file(
            "generated.txt",
            "demo generated content",
            session_id=SESSION_ID,
        )
        print_result(
            "3. write_file requires approval and does not write",
            result,
            RAW_FAKE_SECRETS,
            extra_lines=[
                f"generated.txt exists after call: "
                f"{str((workspace / 'generated.txt').exists()).lower()}"
            ],
        )

        result = service.sentry_list_directory(".", session_id=SESSION_ID)
        print_result("4. list_directory is allowed", result, RAW_FAKE_SECRETS)

        result = service.sentry_run_command(
            "echo sentrygate-demo-command",
            session_id=SESSION_ID,
        )
        print_result(
            "5. normal run_command requires approval and does not execute",
            result,
            RAW_FAKE_SECRETS,
        )

        result = service.sentry_run_command("rm -rf tmp", session_id=SESSION_ID)
        print_result(
            "6. dangerous run_command is blocked",
            result,
            RAW_FAKE_SECRETS,
        )

        print_audit_events(audit_store, RAW_FAKE_SECRETS)


def create_demo_workspace(workspace: Path) -> None:
    (workspace / "src").mkdir()
    (workspace / "public_note.txt").write_text(
        "\n".join(
            [
                "Demo note",
                f"Contact: {FAKE_EMAIL}",
                f"Fake API key: {FAKE_PUBLIC_API_KEY}",
            ]
        ),
        encoding="utf-8",
    )
    (workspace / ".env").write_text(
        "\n".join(
            [
                f"OPENAI_API_KEY={FAKE_ENV_API_KEY}",
                f"DATABASE_URL={FAKE_DATABASE_URL}",
            ]
        ),
        encoding="utf-8",
    )
    (workspace / "src" / "app.py").write_text(
        "print('hello from the SentryGate demo')\n",
        encoding="utf-8",
    )


def print_result(
    title: str,
    result: ToolExecutionResult,
    raw_secrets: tuple[str, ...],
    extra_lines: list[str] | None = None,
) -> None:
    lines = [
        "",
        title,
        f"decision: {result.decision}",
        f"ok: {str(result.ok).lower()}",
        f"risk_score: {result.risk_score}",
        f"reasons: {format_reasons(result.reasons)}",
    ]

    if result.output is not None:
        lines.extend(["output:", result.output])
    if result.error is not None:
        lines.append(f"error: {result.error}")
    if result.masked_findings:
        lines.append(f"masked_findings: {format_findings(result.masked_findings)}")
    if extra_lines is not None:
        lines.extend(extra_lines)

    emit("\n".join(lines), raw_secrets)


def print_audit_events(
    audit_store: InMemoryAuditStore,
    raw_secrets: tuple[str, ...],
) -> None:
    lines = ["", "Audit events"]
    events = audit_store.list_events(session_id=SESSION_ID)

    for index, event in enumerate(events, start=1):
        lines.extend(format_audit_event(index, event))

    emit("\n".join(lines), raw_secrets)


def format_audit_event(index: int, event: AuditEvent) -> list[str]:
    lines = [
        f"{index}. tool_name: {event.tool_name}",
        f"   decision: {event.decision}",
        f"   executed: {str(event.executed).lower()}",
        f"   risk_score: {event.risk_score}",
        f"   reasons: {format_reasons(event.reasons)}",
        f"   arguments_summary: {event.arguments_summary}",
    ]
    if event.output_summary is not None:
        lines.append(f"   output_summary: {event.output_summary}")
    if event.masked_findings:
        lines.append(f"   masked_findings: {format_findings(event.masked_findings)}")
    return lines


def format_reasons(reasons: list[str]) -> str:
    if reasons == []:
        return "(none)"
    return ", ".join(reasons)


def format_findings(findings: tuple[MaskingFinding, ...]) -> str:
    rendered: list[str] = []
    for finding in findings:
        rendered.append(f"{finding.kind.value}={finding.token}")
    return ", ".join(rendered)


def emit(text: str, raw_secrets: tuple[str, ...]) -> None:
    assert_no_raw_secrets(text, raw_secrets)
    print(text)


def assert_no_raw_secrets(text: str, raw_secrets: tuple[str, ...]) -> None:
    leaked = [secret for secret in raw_secrets if secret in text]
    if leaked:
        raise RuntimeError("raw fake secret appeared in demo output")


if __name__ == "__main__":
    main()
