import subprocess
from pathlib import Path

from app.audit.store import InMemoryAuditStore
from app.tools.safe_tools import SafeToolService


def test_blocked_read_file_env_does_not_read_and_audits(tmp_path: Path) -> None:
    secret = "OPENAI_API_KEY=sk-test123"
    (tmp_path / ".env").write_text(secret, encoding="utf-8")
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)

    result = service.sentry_read_file(".env", session_id="session-1")

    assert result.ok is False
    assert result.decision == "block"
    assert result.output is None
    assert result.error == "operation_blocked"
    events = store.list_events()
    assert len(events) == 1
    assert events[0].tool_name == "read_file"
    assert events[0].executed is False
    assert secret not in events[0].model_dump_json()


def test_require_approval_write_file_does_not_write_and_audits(
    tmp_path: Path,
) -> None:
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)
    target = tmp_path / "notes.txt"

    result = service.sentry_write_file(
        "notes.txt",
        "SECRET_KEY=plain-secret",
        session_id="session-1",
    )

    assert result.ok is False
    assert result.decision == "require_approval"
    assert result.error == "operation_requires_approval"
    assert not target.exists()
    event = store.list_events()[0]
    assert event.tool_name == "write_file"
    assert event.executed is False
    serialized = event.model_dump_json()
    assert "plain-secret" not in serialized
    assert "[ENV_SECRET_001]" not in event.arguments_summary
    assert "content_chars=23" in event.arguments_summary


def test_allowed_read_file_returns_masked_content_and_safe_audit(
    tmp_path: Path,
) -> None:
    secret = "admin@example.com"
    (tmp_path / "README.md").write_text(f"Contact {secret}", encoding="utf-8")
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)

    result = service.sentry_read_file("README.md")

    assert result.ok is True
    assert result.decision == "allow"
    assert result.output == "Contact [EMAIL_001]"
    assert result.masked_findings[0].token == "[EMAIL_001]"
    event = store.list_events()[0]
    serialized = event.model_dump_json()
    assert event.executed is True
    assert "Contact [EMAIL_001]" not in event.output_summary
    assert secret not in serialized
    assert "[EMAIL_001]" in serialized


def test_allowed_list_directory_returns_sorted_listing(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hello')", encoding="utf-8")
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)

    result = service.sentry_list_directory(".")

    assert result.ok is True
    assert result.decision == "allow"
    assert result.output == "\n".join(
        [
            "[file] app.py",
            "[dir] docs",
            "[file] README.md",
        ]
    )
    event = store.list_events()[0]
    assert event.tool_name == "list_directory"
    assert event.executed is True


def test_normal_run_command_requires_approval_and_does_not_execute(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("subprocess.run should not execute")

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fail_run)
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)

    result = service.sentry_run_command("pytest --version")

    assert result.ok is False
    assert result.decision == "require_approval"
    assert result.error == "operation_requires_approval"
    event = store.list_events()[0]
    assert event.tool_name == "run_command"
    assert event.executed is False


def test_dangerous_run_command_is_blocked_and_does_not_execute(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("subprocess.run should not execute")

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fail_run)
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)

    result = service.sentry_run_command("rm -rf tmp")

    assert result.ok is False
    assert result.decision == "block"
    assert "dangerous_rm_recursive_force" in result.reasons
    event = store.list_events()[0]
    assert event.executed is False


def test_path_outside_workspace_is_blocked_and_audited(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("hello", encoding="utf-8")
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=workspace, audit_store=store)

    result = service.sentry_read_file(str(outside))

    assert result.ok is False
    assert result.decision == "block"
    assert "path_outside_workspace" in result.reasons
    event = store.list_events()[0]
    assert event.executed is False


def test_audit_store_filters_by_session_and_limit() -> None:
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=Path.cwd(), audit_store=store)

    service.sentry_run_command("pytest --version", session_id="a")
    service.sentry_run_command("pytest --version", session_id="b")
    service.sentry_run_command("pytest --version", session_id="a")

    assert [event.session_id for event in store.list_events()] == ["a", "b", "a"]
    assert [event.session_id for event in store.list_events(session_id="a")] == [
        "a",
        "a",
    ]
    assert [event.session_id for event in store.list_events(limit=2)] == ["b", "a"]


def test_audit_events_mask_command_arguments(tmp_path: Path) -> None:
    raw_secret = "sk-test123"
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)

    result = service.sentry_run_command(f"echo {raw_secret}")

    assert result.decision == "require_approval"
    event = store.list_events()[0]
    serialized = event.model_dump_json()
    assert raw_secret not in serialized
    assert "[API_KEY_001]" in serialized
