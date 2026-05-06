import json
from pathlib import Path

import httpx
import pytest

from app.audit.store import InMemoryAuditStore
from app.risk.lmstudio_client import (
    DEFAULT_LMSTUDIO_BASE_URL,
    DEFAULT_LMSTUDIO_TIMEOUT_SECONDS,
    SEMANTIC_REVIEW_REASON_PREFIX,
    LMStudioReviewClient,
    LMStudioReviewConfig,
    LMStudioReviewInput,
    LMStudioReviewOutput,
    LMStudioRiskReviewer,
)
from app.risk.models import RiskResult, ToolCall
from app.tools.safe_tools import SafeToolService


class FakeReviewClient:
    def __init__(self, output: LMStudioReviewOutput | None) -> None:
        self.output = output
        self.calls: list[LMStudioReviewInput] = []

    def review(
        self,
        review_input: LMStudioReviewInput,
    ) -> LMStudioReviewOutput | None:
        self.calls.append(review_input)
        return self.output


class FakeRiskReviewer:
    def __init__(self, result: RiskResult | None = None) -> None:
        self.result = result
        self.calls: list[tuple[ToolCall, RiskResult, str]] = []

    def review_risk(
        self,
        tool_call: ToolCall,
        original_result: RiskResult,
        arguments_summary: str,
    ) -> RiskResult:
        self.calls.append((tool_call, original_result, arguments_summary))
        return self.result or original_result


def test_config_from_env_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LMSTUDIO_REVIEW_ENABLED", raising=False)
    monkeypatch.delenv("LMSTUDIO_BASE_URL", raising=False)
    monkeypatch.delenv("LMSTUDIO_MODEL", raising=False)
    monkeypatch.delenv("LMSTUDIO_TIMEOUT_SECONDS", raising=False)

    config = LMStudioReviewConfig.from_env()

    assert config.enabled is False
    assert config.base_url == DEFAULT_LMSTUDIO_BASE_URL
    assert config.model is None
    assert config.timeout_seconds == DEFAULT_LMSTUDIO_TIMEOUT_SECONDS


def test_disabled_lmstudio_review_returns_original_without_calling_client() -> None:
    original = _medium_risk_result()
    client = FakeReviewClient(
        LMStudioReviewOutput(
            risk_score=90,
            decision="block",
            reason="would block if enabled",
        )
    )
    reviewer = LMStudioRiskReviewer(
        config=LMStudioReviewConfig(enabled=False),
        client=client,
    )

    result = reviewer.review_risk(
        ToolCall(tool_name="run_command", arguments={"command": "pytest --version"}),
        original,
        "command=pytest --version",
    )

    assert result == original
    assert client.calls == []


def test_medium_risk_safe_tool_calls_fake_reviewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("subprocess.run should not execute")

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fail_run)
    reviewer = FakeRiskReviewer(
        RiskResult(
            risk_score=65,
            decision="require_approval",
            reasons=[
                "run_command_requires_approval",
                f"{SEMANTIC_REVIEW_REASON_PREFIX}: keep approval",
            ],
        )
    )
    service = SafeToolService(workspace_root=tmp_path, risk_reviewer=reviewer)

    result = service.sentry_run_command("pytest --version")

    assert result.decision == "require_approval"
    assert result.risk_score == 65
    assert f"{SEMANTIC_REVIEW_REASON_PREFIX}: keep approval" in result.reasons
    assert len(reviewer.calls) == 1
    assert reviewer.calls[0][2] == "command=pytest --version"


def test_lmstudio_escalates_require_approval_to_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("subprocess.run should not execute")

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fail_run)
    client = FakeReviewClient(
        LMStudioReviewOutput(
            risk_score=90,
            decision="block",
            reason="semantic review found destructive intent",
        )
    )
    reviewer = LMStudioRiskReviewer(
        config=LMStudioReviewConfig(enabled=True),
        client=client,
    )
    store = InMemoryAuditStore()
    service = SafeToolService(
        workspace_root=tmp_path,
        audit_store=store,
        risk_reviewer=reviewer,
    )

    result = service.sentry_run_command("pytest --version")

    assert result.ok is False
    assert result.decision == "block"
    assert result.risk_score == 90
    assert result.error == "operation_blocked"
    assert (
        f"{SEMANTIC_REVIEW_REASON_PREFIX}: semantic review found destructive intent"
        in result.reasons
    )
    event = store.list_events()[0]
    assert event.decision == "block"
    assert event.executed is False
    assert len(client.calls) == 1


def test_lmstudio_downgrade_to_allow_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("subprocess.run should not execute")

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fail_run)
    client = FakeReviewClient(
        LMStudioReviewOutput(
            risk_score=10,
            decision="allow",
            reason="model tried to allow",
        )
    )
    reviewer = LMStudioRiskReviewer(
        config=LMStudioReviewConfig(enabled=True),
        client=client,
    )
    service = SafeToolService(workspace_root=tmp_path, risk_reviewer=reviewer)

    result = service.sentry_run_command("pytest --version")

    assert result.ok is False
    assert result.decision == "require_approval"
    assert result.risk_score == 50
    assert result.error == "operation_requires_approval"


def test_low_risk_allow_does_not_call_reviewer(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    reviewer = FakeRiskReviewer()
    service = SafeToolService(workspace_root=tmp_path, risk_reviewer=reviewer)

    result = service.sentry_read_file("README.md")

    assert result.decision == "allow"
    assert reviewer.calls == []


def test_high_risk_block_does_not_call_reviewer(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test123", encoding="utf-8")
    reviewer = FakeRiskReviewer()
    service = SafeToolService(workspace_root=tmp_path, risk_reviewer=reviewer)

    result = service.sentry_read_file(".env")

    assert result.decision == "block"
    assert reviewer.calls == []


def test_invalid_json_falls_back_to_original_risk_result() -> None:
    original = _medium_risk_result()

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("{not-json")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LMStudioReviewClient(
            config=LMStudioReviewConfig(enabled=True),
            http_client=http_client,
        )
        reviewer = LMStudioRiskReviewer(
            config=LMStudioReviewConfig(enabled=True),
            client=client,
        )

        result = reviewer.review_risk(
            ToolCall(tool_name="run_command", arguments={"command": "pytest"}),
            original,
            "command=pytest",
        )

    assert result == original


def test_invalid_schema_falls_back_to_original_risk_result() -> None:
    original = _medium_risk_result()

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            json.dumps({"risk_score": "high", "decision": "block"})
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LMStudioReviewClient(
            config=LMStudioReviewConfig(enabled=True),
            http_client=http_client,
        )
        reviewer = LMStudioRiskReviewer(
            config=LMStudioReviewConfig(enabled=True),
            client=client,
        )

        result = reviewer.review_risk(
            ToolCall(tool_name="run_command", arguments={"command": "pytest"}),
            original,
            "command=pytest",
        )

    assert result == original


def test_timeout_error_falls_back_to_original_risk_result() -> None:
    original = _medium_risk_result()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LMStudioReviewClient(
            config=LMStudioReviewConfig(enabled=True),
            http_client=http_client,
        )
        reviewer = LMStudioRiskReviewer(
            config=LMStudioReviewConfig(enabled=True),
            client=client,
        )

        result = reviewer.review_risk(
            ToolCall(tool_name="run_command", arguments={"command": "pytest"}),
            original,
            "command=pytest",
        )

    assert result == original


def test_raw_secrets_are_not_sent_to_lmstudio_input(tmp_path: Path) -> None:
    raw_secret = "sk-test123"
    client = FakeReviewClient(
        LMStudioReviewOutput(
            risk_score=65,
            decision="require_approval",
            reason="keep approval",
        )
    )
    reviewer = LMStudioRiskReviewer(
        config=LMStudioReviewConfig(enabled=True),
        client=client,
    )
    service = SafeToolService(workspace_root=tmp_path, risk_reviewer=reviewer)

    result = service.sentry_run_command(f"echo {raw_secret}")

    assert result.decision == "require_approval"
    assert len(client.calls) == 1
    summary = client.calls[0].arguments_summary
    assert raw_secret not in summary
    assert "[API_KEY_001]" in summary


def test_lower_model_score_does_not_reduce_final_score() -> None:
    original = _medium_risk_result()
    client = FakeReviewClient(
        LMStudioReviewOutput(
            risk_score=20,
            decision="require_approval",
            reason="model thought lower",
        )
    )
    reviewer = LMStudioRiskReviewer(
        config=LMStudioReviewConfig(enabled=True),
        client=client,
    )

    result = reviewer.review_risk(
        ToolCall(tool_name="run_command", arguments={"command": "pytest"}),
        original,
        "command=pytest",
    )

    assert result.risk_score == original.risk_score
    assert result.decision == "require_approval"


def test_model_score_at_or_above_75_escalates_to_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("subprocess.run should not execute")

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fail_run)
    client = FakeReviewClient(
        LMStudioReviewOutput(
            risk_score=80,
            decision="require_approval",
            reason="elevated semantic risk",
        )
    )
    reviewer = LMStudioRiskReviewer(
        config=LMStudioReviewConfig(enabled=True),
        client=client,
    )
    store = InMemoryAuditStore()
    service = SafeToolService(
        workspace_root=tmp_path,
        audit_store=store,
        risk_reviewer=reviewer,
    )

    result = service.sentry_run_command("pytest --version")

    assert result.decision == "block"
    assert result.risk_score == 80
    assert result.error == "operation_blocked"
    event = store.list_events()[0]
    assert event.decision == "block"
    assert event.risk_score == 80
    assert event.executed is False


def test_review_reason_with_fake_secret_is_masked_in_result_and_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("subprocess.run should not execute")

    monkeypatch.setattr("app.tools.safe_tools.subprocess.run", fail_run)
    fake_secret = "sk-fakeReasonSecret1234567890"
    client = FakeReviewClient(
        LMStudioReviewOutput(
            risk_score=65,
            decision="require_approval",
            reason=f"model echoed credential {fake_secret}",
        )
    )
    reviewer = LMStudioRiskReviewer(
        config=LMStudioReviewConfig(enabled=True),
        client=client,
    )
    store = InMemoryAuditStore()
    service = SafeToolService(
        workspace_root=tmp_path,
        audit_store=store,
        risk_reviewer=reviewer,
    )

    result = service.sentry_run_command("pytest --version")

    assert result.decision == "require_approval"
    semantic_reasons = [
        reason
        for reason in result.reasons
        if reason.startswith(SEMANTIC_REVIEW_REASON_PREFIX)
    ]
    assert semantic_reasons != []
    for reason in result.reasons:
        assert fake_secret not in reason

    event = store.list_events()[0]
    for reason in event.reasons:
        assert fake_secret not in reason
    assert fake_secret not in (event.output_summary or "")
    assert fake_secret not in event.arguments_summary


def test_httpx_client_posts_openai_compatible_payload() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        return _chat_response(
            json.dumps(
                {
                    "risk_score": 65,
                    "decision": "require_approval",
                    "reason": "keep approval",
                }
            )
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LMStudioReviewClient(
            config=LMStudioReviewConfig(
                enabled=True,
                model="local-model",
                timeout_seconds=2,
            ),
            http_client=http_client,
        )

        output = client.review(
            LMStudioReviewInput(
                tool_name="run_command",
                arguments_summary="command=pytest",
                original_risk_score=50,
                original_decision="require_approval",
                original_reasons=["run_command_requires_approval"],
            )
        )

    assert output == LMStudioReviewOutput(
        risk_score=65,
        decision="require_approval",
        reason="keep approval",
    )
    assert requests[0]["model"] == "local-model"
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["temperature"] == 0
    assert isinstance(requests[0]["messages"], list)


def _medium_risk_result() -> RiskResult:
    return RiskResult(
        risk_score=50,
        decision="require_approval",
        reasons=["run_command_requires_approval"],
    )


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": content,
                    },
                }
            ]
        },
    )
