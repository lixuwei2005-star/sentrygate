import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.approvals.api import create_approval_api
from app.risk.models import RiskResult, ToolCall
from app.tools.safe_tools import SafeToolService

_LOCAL_BASE_URL = "http://127.0.0.1"


def test_approval_api_health_returns_safe_payload(tmp_path: Path) -> None:
    client = _client(SafeToolService(workspace_root=tmp_path))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "sentrygate-approval-api"}


def test_pending_approvals_returns_display_safe_requests(tmp_path: Path) -> None:
    raw_secret = "sk-test123456"
    service = SafeToolService(workspace_root=tmp_path)
    result = service.sentry_write_file(
        "notes.txt",
        f"token={raw_secret}",
        session_id="session-1",
    )
    assert result.approval_request_id is not None
    client = _client(service)

    response = client.get("/approvals/pending")

    assert response.status_code == 200
    approvals = response.json()
    assert len(approvals) == 1
    approval = approvals[0]
    assert set(approval) == {
        "request_id",
        "created_at",
        "session_id",
        "tool_name",
        "arguments_summary",
        "original_arguments",
        "risk_score",
        "reasons",
        "status",
        "expires_at",
    }
    assert approval["request_id"] == result.approval_request_id
    assert approval["tool_name"] == "write_file"
    assert approval["status"] == "pending"
    serialized = json.dumps(approvals, sort_keys=True)
    assert raw_secret not in serialized
    assert "_execution_payloads" not in serialized
    assert "fingerprint" not in serialized


def test_approve_executes_original_request_without_body_arguments(
    tmp_path: Path,
) -> None:
    service = SafeToolService(workspace_root=tmp_path)
    result = service.sentry_write_file("notes.txt", "hello")
    assert result.approval_request_id is not None
    client = _client(service)

    response = client.post(
        f"/approvals/{result.approval_request_id}/approve",
        json={
            "path": "tampered.txt",
            "content": "changed",
            "command": "echo changed",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["decision"] == "require_approval"
    assert payload["error"] is None
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello"
    assert not (tmp_path / "tampered.txt").exists()
    assert service.approval_store.list_pending() == []


def test_approve_missing_request_returns_tool_result_without_traceback(
    tmp_path: Path,
) -> None:
    client = _client(SafeToolService(workspace_root=tmp_path))

    response = client.post("/approvals/missing/approve")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["decision"] == "block"
    serialized = json.dumps(payload)
    assert "Traceback" not in serialized
    assert "_execution_payloads" not in serialized


def test_approve_unexpected_error_returns_safe_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_secret = "sk-test123456"
    service = SafeToolService(workspace_root=tmp_path)

    def fail_approval(request_id: str) -> object:
        raise RuntimeError(f"boom {raw_secret} Traceback private-payload")

    monkeypatch.setattr(service, "approve_request", fail_approval)
    client = _client(service)

    with caplog.at_level("WARNING", logger="sentrygate.approval_api"):
        response = client.post("/approvals/request-1/approve")

    assert response.status_code == 500
    assert response.json() == {"detail": "approval_approve_failed"}
    serialized = json.dumps(response.json())
    assert raw_secret not in serialized
    assert "Traceback" not in serialized
    assert "private-payload" not in serialized

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in log_text
    assert raw_secret not in log_text
    assert "private-payload" not in log_text


def test_approve_blocked_by_rescore_does_not_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SafeToolService(workspace_root=tmp_path)
    pending = service.sentry_write_file("notes.txt", "hello")
    assert pending.approval_request_id is not None
    assert not (tmp_path / "notes.txt").exists()

    def force_block(tool_call: ToolCall) -> RiskResult:
        return RiskResult(
            risk_score=100,
            decision="block",
            reasons=["forced_rescore_block_for_test"],
        )

    monkeypatch.setattr(service.risk_scorer, "score_tool_call", force_block)
    client = _client(service)

    response = client.post(f"/approvals/{pending.approval_request_id}/approve")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "ok",
        "decision",
        "risk_score",
        "reasons",
        "output",
        "error",
        "masked_findings",
        "approval_request_id",
    }
    assert payload["ok"] is False
    assert payload["decision"] == "block"
    assert not (tmp_path / "notes.txt").exists()
    assert service.approval_store.list_pending() == []
    assert (
        service.approval_store.get_execution_payload(pending.approval_request_id)
        is None
    )


def test_reject_marks_request_rejected_without_execution(tmp_path: Path) -> None:
    service = SafeToolService(workspace_root=tmp_path)
    result = service.sentry_write_file("notes.txt", "hello")
    assert result.approval_request_id is not None
    client = _client(service)

    response = client.post(f"/approvals/{result.approval_request_id}/reject")

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == result.approval_request_id
    assert payload["status"] == "rejected"
    assert not (tmp_path / "notes.txt").exists()
    assert service.approval_store.list_pending() == []
    assert (
        service.approval_store.get_execution_payload(result.approval_request_id)
        is None
    )


def test_reject_missing_request_returns_safe_error(tmp_path: Path) -> None:
    client = _client(SafeToolService(workspace_root=tmp_path))

    response = client.post("/approvals/missing/reject")

    assert response.status_code == 404
    assert response.json() == {"detail": "approval_request_not_found"}
    serialized = json.dumps(response.json())
    assert "Traceback" not in serialized
    assert "_execution_payloads" not in serialized


def test_blocked_operations_are_not_listed_as_pending(tmp_path: Path) -> None:
    service = SafeToolService(workspace_root=tmp_path)
    blocked = service.sentry_write_file(".env", "secret=value")
    client = _client(service)

    response = client.get("/approvals/pending")

    assert blocked.decision == "block"
    assert blocked.approval_request_id is None
    assert response.status_code == 200
    assert response.json() == []


def test_local_guard_allows_request_without_origin(tmp_path: Path) -> None:
    client = _client(SafeToolService(workspace_root=tmp_path))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "sentrygate-approval-api"}


def test_local_guard_allows_localhost_origin(tmp_path: Path) -> None:
    client = TestClient(
        create_approval_api(SafeToolService(workspace_root=tmp_path)),
        base_url="http://localhost:8766",
    )

    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200


def test_local_guard_allows_127_0_0_1_origin(tmp_path: Path) -> None:
    client = _client(SafeToolService(workspace_root=tmp_path))

    response = client.get(
        "/health",
        headers={"Origin": "http://127.0.0.1:8766"},
    )

    assert response.status_code == 200


def test_local_guard_rejects_non_local_origin(tmp_path: Path) -> None:
    client = _client(SafeToolService(workspace_root=tmp_path))

    response = client.get(
        "/health",
        headers={"Origin": "http://evil.example.com"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "non_local_request_rejected"}


def test_local_guard_rejects_null_origin(tmp_path: Path) -> None:
    client = _client(SafeToolService(workspace_root=tmp_path))

    response = client.get("/health", headers={"Origin": "null"})

    assert response.status_code == 403
    assert response.json() == {"detail": "non_local_request_rejected"}


def test_local_guard_rejects_non_local_host(tmp_path: Path) -> None:
    client = TestClient(
        create_approval_api(SafeToolService(workspace_root=tmp_path)),
        base_url="http://evil.example.com",
    )

    response = client.get("/health")

    assert response.status_code == 403
    assert response.json() == {"detail": "non_local_request_rejected"}


def test_local_guard_rejects_default_testserver_host(tmp_path: Path) -> None:
    client = TestClient(
        create_approval_api(SafeToolService(workspace_root=tmp_path)),
    )

    response = client.get("/health")

    assert response.status_code == 403
    assert response.json() == {"detail": "non_local_request_rejected"}


def test_local_guard_rejects_approve_from_non_local_origin(tmp_path: Path) -> None:
    service = SafeToolService(workspace_root=tmp_path)
    pending = service.sentry_write_file("notes.txt", "hello")
    assert pending.approval_request_id is not None
    client = _client(service)

    response = client.post(
        f"/approvals/{pending.approval_request_id}/approve",
        headers={"Origin": "http://evil.example.com"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "non_local_request_rejected"}
    assert not (tmp_path / "notes.txt").exists()
    assert service.approval_store.list_pending()[0].request_id == (
        pending.approval_request_id
    )


def _client(service: SafeToolService) -> TestClient:
    return TestClient(create_approval_api(service), base_url=_LOCAL_BASE_URL)
