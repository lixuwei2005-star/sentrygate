import subprocess
from pathlib import Path

import pytest

from app.audit.models import AuditEvent
from app.audit.store import InMemoryAuditStore
from app.risk.models import RiskResult, ToolCall
from app.risk.scorer import RiskScorer
from app.tools.safe_tools import (
    SafeToolService,
    configure_default_service,
    reset_default_service,
    sentry_read_file,
)


class _PermissiveRiskScorer(RiskScorer):
    def score_tool_call(self, tool_call: ToolCall) -> RiskResult:
        return RiskResult(
            risk_score=0,
            decision="allow",
            reasons=["test_permissive_scorer"],
        )


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


def test_audit_event_supports_optional_observability_fields() -> None:
    event = AuditEvent(
        session_id="session-1",
        tool_name="read_file",
        decision="allow",
        risk_score=10,
        reasons=["safe_file_read"],
        arguments_summary="path=README.md",
        output_summary="read_file succeeded; chars=5; masked_findings=0",
        executed=True,
    )

    assert event.trace_id is None
    assert event.span_id is None
    assert event.parent_span_id is None
    assert event.started_at is None
    assert event.ended_at is None
    assert event.latency_ms is None


def test_safe_tool_service_records_trace_span_and_latency(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)

    result = service.sentry_read_file("README.md", session_id="session-1")

    assert result.ok is True
    event = store.list_events()[0]
    assert event.trace_id == "session-1"
    assert event.span_id is not None
    assert event.parent_span_id is None
    assert event.started_at is not None
    assert event.ended_at is not None
    assert event.ended_at >= event.started_at
    assert event.latency_ms is not None
    assert event.latency_ms >= 0


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

    service.sentry_read_file("pyproject.toml", session_id="a")
    service.sentry_read_file("pyproject.toml", session_id="b")
    service.sentry_read_file("pyproject.toml", session_id="a")

    assert [event.session_id for event in store.list_events()] == ["a", "b", "a"]
    assert [event.session_id for event in store.list_events(session_id="a")] == [
        "a",
        "a",
    ]
    assert [event.session_id for event in store.list_events(limit=2)] == ["b", "a"]


def test_public_wrapper_raises_runtime_error_before_configure() -> None:
    reset_default_service()
    try:
        with pytest.raises(RuntimeError):
            sentry_read_file("README.md")
    finally:
        reset_default_service()


def test_public_wrapper_works_after_configure_default_service(
    tmp_path: Path,
) -> None:
    reset_default_service()
    (tmp_path / "README.md").write_text("hello world", encoding="utf-8")
    try:
        configure_default_service(workspace_root=tmp_path)
        result = sentry_read_file("README.md")
        assert result.ok is True
        assert result.decision == "allow"
        assert result.output == "hello world"
    finally:
        reset_default_service()


def test_reset_default_service_clears_configured_service(tmp_path: Path) -> None:
    configure_default_service(workspace_root=tmp_path)
    reset_default_service()
    try:
        with pytest.raises(RuntimeError):
            sentry_read_file("README.md")
    finally:
        reset_default_service()


def test_safe_tool_blocks_outside_workspace_even_with_permissive_scorer(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-secret", encoding="utf-8")
    store = InMemoryAuditStore()
    service = SafeToolService(
        workspace_root=workspace,
        risk_scorer=_PermissiveRiskScorer(workspace),
        audit_store=store,
    )

    result = service.sentry_read_file(str(outside))

    assert result.ok is False
    assert result.output is None
    assert result.error is not None
    assert "path_outside_workspace" in result.error
    event = store.list_events()[0]
    assert event.executed is False
    assert event.tool_name == "read_file"
    assert "outside-secret" not in event.model_dump_json()


def test_run_command_empty_string_setup_error_marks_executed_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(
        *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("subprocess.run should not execute on empty command")

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fail_run)
    store = InMemoryAuditStore()
    service = SafeToolService(
        workspace_root=tmp_path,
        risk_scorer=_PermissiveRiskScorer(tmp_path),
        audit_store=store,
    )

    result = service.sentry_run_command("   ")

    assert result.ok is False
    assert result.error is not None
    assert "empty_command" in result.error
    event = store.list_events()[0]
    assert event.executed is False


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
