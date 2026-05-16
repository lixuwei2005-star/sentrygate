import asyncio
import json
from pathlib import Path
from typing import cast

import pytest

from app.audit.jsonl_store import JsonlAuditStore
from app.audit.store import InMemoryAuditStore
from app.mcp import server
from app.mcp.server import (
    AUDIT_LOG_PATH_ENV,
    MISSING_WORKSPACE_ROOT_ERROR,
    WORKSPACE_ROOT_ENV,
    WorkspaceRootError,
    create_mcp_server,
    create_service,
    main,
    resolve_audit_log_path,
    resolve_workspace_root,
    serialize_result,
)
from app.privacy.masker import MaskingFinding
from app.privacy.patterns import SecretKind
from app.tools.models import ToolExecutionResult
from app.tools.safe_tools import SafeToolService


class FakeSafeToolService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def sentry_read_file(self, path: str) -> ToolExecutionResult:
        self.calls.append(("sentry_read_file", {"path": path}))
        return ToolExecutionResult(
            ok=True,
            decision="allow",
            risk_score=0,
            reasons=["fake_allow"],
            output=f"read:{path}",
        )

    def sentry_write_file(self, path: str, content: str) -> ToolExecutionResult:
        self.calls.append(
            ("sentry_write_file", {"path": path, "content": content})
        )
        return ToolExecutionResult(
            ok=False,
            decision="require_approval",
            risk_score=50,
            reasons=["fake_require_approval"],
            error="operation_requires_approval",
        )

    def sentry_list_directory(self, path: str) -> ToolExecutionResult:
        self.calls.append(("sentry_list_directory", {"path": path}))
        return ToolExecutionResult(
            ok=True,
            decision="allow",
            risk_score=0,
            reasons=["fake_allow"],
            output=f"[file] {path}",
        )

    def sentry_run_command(self, command: str) -> ToolExecutionResult:
        self.calls.append(("sentry_run_command", {"command": command}))
        return ToolExecutionResult(
            ok=False,
            decision="require_approval",
            risk_score=50,
            reasons=["fake_require_approval"],
            error="operation_requires_approval",
        )


def test_resolve_workspace_root_uses_cli_before_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli_root = tmp_path / "cli"
    env_root = tmp_path / "env"
    cli_root.mkdir()
    env_root.mkdir()
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(env_root))

    assert resolve_workspace_root(str(cli_root)) == cli_root.resolve()


def test_resolve_workspace_root_uses_env_when_cli_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(tmp_path))

    assert resolve_workspace_root(None) == tmp_path.resolve()


def test_resolve_workspace_root_requires_explicit_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)

    with pytest.raises(WorkspaceRootError, match=MISSING_WORKSPACE_ROOT_ERROR):
        resolve_workspace_root(None)


def test_resolve_workspace_root_treats_blank_env_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, "   ")

    with pytest.raises(WorkspaceRootError, match=MISSING_WORKSPACE_ROOT_ERROR):
        resolve_workspace_root(None)


def test_resolve_workspace_root_rejects_invalid_path(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"

    with pytest.raises(WorkspaceRootError, match="workspace root does not exist"):
        resolve_workspace_root(str(missing_root))


def test_resolve_workspace_root_rejects_file(tmp_path: Path) -> None:
    file_root = tmp_path / "not-a-directory.txt"
    file_root.write_text("hello", encoding="utf-8")

    with pytest.raises(WorkspaceRootError, match="workspace root is not a directory"):
        resolve_workspace_root(str(file_root))


def test_resolve_audit_log_path_uses_cli_before_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli_path = tmp_path / "cli" / "audit.jsonl"
    env_path = tmp_path / "env" / "audit.jsonl"
    monkeypatch.setenv(AUDIT_LOG_PATH_ENV, str(env_path))

    assert resolve_audit_log_path(str(cli_path)) == cli_path.resolve()


def test_resolve_audit_log_path_uses_env_when_cli_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv(AUDIT_LOG_PATH_ENV, str(env_path))

    assert resolve_audit_log_path(None) == env_path.resolve()


def test_resolve_audit_log_path_treats_blank_values_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AUDIT_LOG_PATH_ENV, "   ")

    assert resolve_audit_log_path(" ") is None


def test_create_service_passes_explicit_workspace_root(tmp_path: Path) -> None:
    service = create_service(tmp_path)

    assert service.workspace_root == tmp_path.resolve()
    assert isinstance(service.audit_store, InMemoryAuditStore)


def test_create_service_uses_jsonl_audit_store_when_path_is_supplied(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "audit.jsonl"

    service = create_service(tmp_path, audit_log_path=log_path)

    assert isinstance(service.audit_store, JsonlAuditStore)
    assert service.audit_store.path == log_path


def test_serialize_result_returns_safe_json_compatible_data() -> None:
    raw_secret = "sk-test123"
    result = ToolExecutionResult(
        ok=True,
        decision="allow",
        risk_score=0,
        reasons=["test"],
        output="[API_KEY_001]",
        masked_findings=(
            MaskingFinding(kind=SecretKind.API_KEY, token="[API_KEY_001]"),
        ),
    )

    serialized = serialize_result(result)

    assert serialized == {
        "ok": True,
        "decision": "allow",
        "risk_score": 0,
        "reasons": ["test"],
        "output": "[API_KEY_001]",
        "error": None,
        "masked_findings": [
            {"kind": "API_KEY", "token": "[API_KEY_001]"},
        ],
    }
    assert raw_secret not in json.dumps(serialized)


def test_create_mcp_server_registers_expected_tools() -> None:
    fake_service = FakeSafeToolService()
    mcp = create_mcp_server(cast(SafeToolService, fake_service))

    tools = asyncio.run(mcp.list_tools())

    assert [tool.name for tool in tools] == [
        "sentry_read_file",
        "sentry_write_file",
        "sentry_list_directory",
        "sentry_run_command",
    ]


def test_mcp_tools_delegate_to_safe_tool_service() -> None:
    fake_service = FakeSafeToolService()
    mcp = create_mcp_server(cast(SafeToolService, fake_service))

    read_result = _call_tool(mcp, "sentry_read_file", {"path": "README.md"})
    write_result = _call_tool(
        mcp,
        "sentry_write_file",
        {"path": "notes.txt", "content": "hello"},
    )
    list_result = _call_tool(mcp, "sentry_list_directory", {"path": "."})
    command_result = _call_tool(
        mcp,
        "sentry_run_command",
        {"command": "pytest --version"},
    )

    assert fake_service.calls == [
        ("sentry_read_file", {"path": "README.md"}),
        ("sentry_write_file", {"path": "notes.txt", "content": "hello"}),
        ("sentry_list_directory", {"path": "."}),
        ("sentry_run_command", {"command": "pytest --version"}),
    ]
    assert read_result["output"] == "read:README.md"
    assert write_result["decision"] == "require_approval"
    assert list_result["output"] == "[file] ."
    assert command_result["error"] == "operation_requires_approval"


def test_main_missing_workspace_writes_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_create_service(workspace_root: Path) -> SafeToolService:
        raise AssertionError("SafeToolService should not be created")

    def fail_runner(mcp: object) -> None:
        raise AssertionError("MCP server should not start")

    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)
    monkeypatch.setattr(server, "create_service", fail_create_service)

    exit_code = main([], server_runner=fail_runner)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert MISSING_WORKSPACE_ROOT_ERROR in captured.err


def test_main_uses_injected_runner_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran_servers: list[object] = []
    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)

    exit_code = main(
        ["--workspace-root", str(tmp_path)],
        server_runner=ran_servers.append,
    )

    assert exit_code == 0
    assert len(ran_servers) == 1


def test_mcp_server_with_real_safe_tool_service_masks_secrets_and_blocks_env(
    tmp_path: Path,
) -> None:
    raw_secret = "sk-test123456"
    safe_file = tmp_path / "public.txt"
    safe_file.write_text(f"hello {raw_secret}", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(f"OPENAI_API_KEY={raw_secret}\n", encoding="utf-8")

    service = SafeToolService(workspace_root=tmp_path)
    mcp = create_mcp_server(service)

    safe_result = _call_tool(mcp, "sentry_read_file", {"path": "public.txt"})

    assert safe_result["decision"] == "allow"
    assert safe_result["ok"] is True
    safe_output = safe_result["output"]
    assert isinstance(safe_output, str)
    assert "[API_KEY_001]" in safe_output
    assert raw_secret not in json.dumps(safe_result)

    env_result = _call_tool(mcp, "sentry_read_file", {"path": ".env"})

    assert env_result["decision"] == "block"
    assert env_result["ok"] is False
    assert raw_secret not in json.dumps(env_result)


def _call_tool(
    mcp: object,
    name: str,
    arguments: dict[str, str],
) -> dict[str, object]:
    _, structured_result = asyncio.run(mcp.call_tool(name, arguments))
    return cast(dict[str, object], structured_result)
