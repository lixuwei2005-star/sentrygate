import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.approvals.store import ApprovalStoreError
from app.audit.store import InMemoryAuditStore
from app.risk.models import RiskResult, ToolCall
from app.risk.scorer import RiskScorer
from app.tools.safe_tools import SafeToolService


class _SpyRiskScorer(RiskScorer):
    def __init__(self, workspace_root: Path) -> None:
        super().__init__(workspace_root)
        self.calls: list[ToolCall] = []

    def score_tool_call(self, tool_call: ToolCall) -> RiskResult:
        self.calls.append(tool_call)
        return super().score_tool_call(tool_call)


class _BlockOnSecondScoreRiskScorer(RiskScorer):
    def __init__(self, workspace_root: Path) -> None:
        super().__init__(workspace_root)
        self.calls: list[ToolCall] = []

    def score_tool_call(self, tool_call: ToolCall) -> RiskResult:
        self.calls.append(tool_call)
        if len(self.calls) == 1:
            return RiskResult(
                risk_score=50,
                decision="require_approval",
                reasons=["first_call_requires_approval"],
            )
        return RiskResult(
            risk_score=100,
            decision="block",
            reasons=["second_call_blocks"],
        )


class _RequireApprovalRiskScorer(RiskScorer):
    def score_tool_call(self, tool_call: ToolCall) -> RiskResult:
        return RiskResult(
            risk_score=50,
            decision="require_approval",
            reasons=[f"{tool_call.tool_name}_requires_approval"],
        )


def test_write_file_requires_approval_creates_safe_pending_request(
    tmp_path: Path,
) -> None:
    raw_secret = "sk-test123"
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)
    target = tmp_path / "notes.txt"

    result = service.sentry_write_file(
        "notes.txt",
        f"token={raw_secret}",
        session_id="session-1",
    )

    assert result.ok is False
    assert result.decision == "require_approval"
    assert result.approval_request_id is not None
    assert not target.exists()

    pending = service.approval_store.list_pending(session_id="session-1")
    assert len(pending) == 1
    request = pending[0]
    assert request.request_id == result.approval_request_id
    assert request.tool_name == "write_file"
    assert request.original_arguments == {
        "path": "notes.txt",
        "content_chars": len(f"token={raw_secret}"),
    }
    assert raw_secret not in request.model_dump_json()
    assert request.status == "pending"

    serialized_events = _serialized_events(store)
    assert "approval_request_created" in serialized_events
    assert raw_secret not in serialized_events


def test_run_command_requires_approval_creates_safe_request_without_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_secret = "sk-test123"

    def fail_run(
        *args: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("subprocess.run should not execute before approval")

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fail_run)
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)

    result = service.sentry_run_command(f"echo {raw_secret}", session_id="session-1")

    assert result.ok is False
    assert result.decision == "require_approval"
    assert result.approval_request_id is not None
    request = service.approval_store.get(result.approval_request_id)
    assert request is not None
    assert request.tool_name == "run_command"
    assert "[API_KEY_001]" in request.arguments_summary
    assert "[API_KEY_001]" in str(request.original_arguments)
    assert raw_secret not in request.model_dump_json()
    assert raw_secret not in _serialized_events(store)


def test_reject_request_removes_pending_payload_and_prevents_execution(
    tmp_path: Path,
) -> None:
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)
    target = tmp_path / "notes.txt"

    result = service.sentry_write_file("notes.txt", "hello")
    assert result.approval_request_id is not None

    rejected = service.reject_request(result.approval_request_id)

    assert rejected.status == "rejected"
    assert service.approval_store.list_pending() == []
    assert (
        service.approval_store.get_execution_payload(result.approval_request_id)
        is None
    )
    approve_after_reject = service.approve_request(result.approval_request_id)
    assert approve_after_reject.ok is False
    assert approve_after_reject.decision == "block"
    assert not target.exists()
    assert "approval_request_rejected" in _serialized_events(store)


def test_approve_write_file_reruns_risk_and_uses_original_private_payload(
    tmp_path: Path,
) -> None:
    raw_secret = "sk-test123"
    scorer = _SpyRiskScorer(tmp_path)
    store = InMemoryAuditStore()
    service = SafeToolService(
        workspace_root=tmp_path,
        risk_scorer=scorer,
        audit_store=store,
    )

    result = service.sentry_write_file("notes.txt", f"token={raw_secret}")
    assert result.approval_request_id is not None

    display_request = service.approval_store.get(result.approval_request_id)
    assert display_request is not None
    display_request.original_arguments["path"] = "smuggled.txt"
    display_request.tool_name = "run_command"

    approved = service.approve_request(result.approval_request_id)

    assert approved.ok is True
    assert approved.decision == "require_approval"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == f"token={raw_secret}"
    assert not (tmp_path / "smuggled.txt").exists()
    assert [call.tool_name for call in scorer.calls] == ["write_file", "write_file"]
    assert service.approval_store.get(result.approval_request_id).status == "executed"
    assert (
        service.approval_store.get_execution_payload(result.approval_request_id)
        is None
    )
    serialized_events = _serialized_events(store)
    assert "approval_operation_executed" in serialized_events
    assert raw_secret not in serialized_events


def test_approve_run_command_reruns_risk_and_uses_safe_subprocess_options(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scorer = _SpyRiskScorer(tmp_path)
    store = InMemoryAuditStore()
    service = SafeToolService(
        workspace_root=tmp_path,
        risk_scorer=scorer,
        audit_store=store,
        command_timeout_seconds=2.5,
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(
        argv: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fake_run)

    result = service.sentry_run_command("pytest --version")
    assert result.approval_request_id is not None
    approved = service.approve_request(result.approval_request_id)

    assert approved.ok is True
    assert approved.decision == "require_approval"
    assert [call.tool_name for call in scorer.calls] == ["run_command", "run_command"]
    assert calls == [
        (
            ["pytest", "--version"],
            {
                "cwd": tmp_path.resolve(),
                "timeout": 2.5,
                "capture_output": True,
                "text": True,
                "shell": False,
                "check": False,
            },
        )
    ]


def test_approve_request_denies_if_rescore_blocks_and_is_not_pending(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_run(
        *args: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("blocked approval must not execute")

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fail_run)
    scorer = _BlockOnSecondScoreRiskScorer(tmp_path)
    store = InMemoryAuditStore()
    service = SafeToolService(
        workspace_root=tmp_path,
        risk_scorer=scorer,
        audit_store=store,
    )

    result = service.sentry_run_command("pytest --version")
    assert result.approval_request_id is not None

    approved = service.approve_request(result.approval_request_id)

    assert approved.ok is False
    assert approved.decision == "block"
    assert "second_call_blocks" in approved.reasons
    assert service.approval_store.list_pending() == []
    assert service.approval_store.get(result.approval_request_id).status == "approved"
    assert (
        service.approval_store.get_execution_payload(result.approval_request_id)
        is None
    )
    serialized_events = _serialized_events(store)
    assert "approval_execution_denied" in serialized_events
    assert "second_call_blocks" in serialized_events


def test_outside_workspace_write_file_requires_approval_scorer_blocks_without_request(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    store = InMemoryAuditStore()
    service = SafeToolService(
        workspace_root=workspace,
        risk_scorer=_RequireApprovalRiskScorer(workspace),
        audit_store=store,
    )

    result = service.sentry_write_file(str(outside), "hello")

    assert result.ok is False
    assert result.decision == "block"
    assert "path_outside_workspace" in result.reasons
    assert result.approval_request_id is None
    assert service.approval_store.list_pending() == []
    assert not outside.exists()

    events = store.list_events()
    assert len(events) == 1
    assert events[0].tool_name == "write_file"
    assert events[0].decision == "block"
    assert events[0].executed is False
    assert "approval_request_created" not in _serialized_events(store)


def test_approve_request_boundary_denial_uses_lifecycle_audit(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    other_workspace = tmp_path / "other"
    workspace.mkdir()
    other_workspace.mkdir()
    target = workspace / "notes.txt"
    store = InMemoryAuditStore()
    service = SafeToolService(
        workspace_root=workspace,
        risk_scorer=_SpyRiskScorer(workspace),
        audit_store=store,
    )

    result = service.sentry_write_file(str(target), "hello")
    assert result.approval_request_id is not None
    service.workspace_root = other_workspace.resolve()

    approved = service.approve_request(result.approval_request_id)

    assert approved.ok is False
    assert approved.decision == "block"
    assert "path_outside_workspace" in approved.reasons
    assert not target.exists()
    assert service.approval_store.list_pending() == []
    assert service.approval_store.get(result.approval_request_id).status == "approved"
    assert (
        service.approval_store.get_execution_payload(result.approval_request_id)
        is None
    )

    events = store.list_events(limit=1000)
    assert events[-1].tool_name == "approval_execution_denied"
    assert events[-1].executed is False
    assert "path_outside_workspace" in events[-1].model_dump_json()


def test_expired_request_cannot_be_approved_and_discards_payload(
    tmp_path: Path,
) -> None:
    service = SafeToolService(workspace_root=tmp_path)

    result = service.sentry_write_file("notes.txt", "hello")
    assert result.approval_request_id is not None
    request_id = result.approval_request_id
    stored_request = service.approval_store._requests[request_id]
    service.approval_store._requests[request_id] = stored_request.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        deep=True,
    )

    approved = service.approve_request(request_id)

    assert approved.ok is False
    assert approved.decision == "block"
    assert any("expired" in reason for reason in approved.reasons)
    assert service.approval_store.get(request_id).status == "expired"
    assert service.approval_store.get_execution_payload(request_id) is None
    assert not (tmp_path / "notes.txt").exists()


def test_private_payload_cannot_be_replaced_for_existing_request(
    tmp_path: Path,
) -> None:
    service = SafeToolService(workspace_root=tmp_path)

    result = service.sentry_write_file("notes.txt", "hello")
    assert result.approval_request_id is not None

    with pytest.raises(
        ApprovalStoreError,
        match="approval_execution_payload_already_exists",
    ):
        service.approval_store.attach_execution_payload(
            result.approval_request_id,
            object(),
        )


def test_payload_fingerprint_mismatch_prevents_execution(
    tmp_path: Path,
) -> None:
    store = InMemoryAuditStore()
    service = SafeToolService(workspace_root=tmp_path, audit_store=store)

    result = service.sentry_write_file("notes.txt", "hello")
    assert result.approval_request_id is not None
    payload = service.approval_store.get_execution_payload(result.approval_request_id)
    assert payload is not None
    payload.arguments["path"] = "tampered.txt"

    approved = service.approve_request(result.approval_request_id)

    assert approved.ok is False
    assert approved.decision == "block"
    assert "approval_payload_mismatch" in approved.reasons
    assert not (tmp_path / "notes.txt").exists()
    assert not (tmp_path / "tampered.txt").exists()
    assert service.approval_store.get(result.approval_request_id).status == "approved"
    assert (
        service.approval_store.get_execution_payload(result.approval_request_id)
        is None
    )
    serialized_events = _serialized_events(store)
    assert "approval_execution_denied" in serialized_events
    assert "approval_payload_mismatch" in serialized_events


def test_blocked_operations_do_not_create_approval_requests(tmp_path: Path) -> None:
    service = SafeToolService(workspace_root=tmp_path)

    blocked_write = service.sentry_write_file(".env", "secret=value")
    blocked_command = service.sentry_run_command("rm -rf tmp")

    assert blocked_write.decision == "block"
    assert blocked_write.approval_request_id is None
    assert blocked_command.decision == "block"
    assert blocked_command.approval_request_id is None
    assert service.approval_store.list_pending() == []


def test_read_file_and_list_directory_do_not_create_approval_requests(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    service = SafeToolService(
        workspace_root=tmp_path,
        risk_scorer=_RequireApprovalRiskScorer(tmp_path),
    )

    read_result = service.sentry_read_file("README.md")
    list_result = service.sentry_list_directory(".")

    assert read_result.decision == "require_approval"
    assert read_result.approval_request_id is None
    assert list_result.decision == "require_approval"
    assert list_result.approval_request_id is None
    assert service.approval_store.list_pending() == []


def _serialized_events(store: InMemoryAuditStore) -> str:
    return json.dumps(
        [event.model_dump(mode="json") for event in store.list_events(limit=1000)],
        sort_keys=True,
    )
