import asyncio
import json
import socket
from pathlib import Path
from typing import cast

import pytest

from app.audit.jsonl_store import JsonlAuditStore
from app.audit.store import InMemoryAuditStore
from app.mcp import server
from app.mcp.server import (
    APPROVAL_API_HOST,
    APPROVAL_API_PORT_ENV,
    AUDIT_LOG_PATH_ENV,
    INVALID_APPROVAL_API_PORT_ERROR,
    MISSING_WORKSPACE_ROOT_ERROR,
    WORKSPACE_ROOT_ENV,
    ApprovalApiPortError,
    ApprovalApiStartupError,
    WorkspaceRootError,
    create_mcp_server,
    create_service,
    ensure_approval_api_port_available,
    main,
    resolve_approval_api_port,
    resolve_audit_log_path,
    resolve_workspace_root,
    serialize_result,
    start_approval_api_server,
)
from app.privacy.masker import MaskingFinding
from app.privacy.patterns import SecretKind
from app.tools.models import ToolExecutionResult
from app.tools.safe_tools import SafeToolService


class FakeSafeToolService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def sentry_read_file(
        self,
        path: str,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        self.calls.append(
            ("sentry_read_file", {"path": path, "session_id": session_id})
        )
        return ToolExecutionResult(
            ok=True,
            decision="allow",
            risk_score=0,
            reasons=["fake_allow"],
            output=f"read:{path}",
        )

    def sentry_write_file(
        self,
        path: str,
        content: str,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        self.calls.append(
            (
                "sentry_write_file",
                {"path": path, "content": content, "session_id": session_id},
            )
        )
        return ToolExecutionResult(
            ok=False,
            decision="require_approval",
            risk_score=50,
            reasons=["fake_require_approval"],
            error="operation_requires_approval",
        )

    def sentry_list_directory(
        self,
        path: str,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        self.calls.append(
            ("sentry_list_directory", {"path": path, "session_id": session_id})
        )
        return ToolExecutionResult(
            ok=True,
            decision="allow",
            risk_score=0,
            reasons=["fake_allow"],
            output=f"[file] {path}",
        )

    def sentry_run_command(
        self,
        command: str,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        self.calls.append(
            (
                "sentry_run_command",
                {"command": command, "session_id": session_id},
            )
        )
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


def test_resolve_approval_api_port_uses_cli_before_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(APPROVAL_API_PORT_ENV, "8767")

    assert resolve_approval_api_port("8766") == 8766


def test_resolve_approval_api_port_uses_env_when_cli_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(APPROVAL_API_PORT_ENV, "8766")

    assert resolve_approval_api_port(None) == 8766


def test_resolve_approval_api_port_treats_blank_values_as_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(APPROVAL_API_PORT_ENV, "   ")

    assert resolve_approval_api_port(" ") is None


@pytest.mark.parametrize("value", ["0", "65536", "abc"])
def test_resolve_approval_api_port_rejects_invalid_values(
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(APPROVAL_API_PORT_ENV, raising=False)

    with pytest.raises(ApprovalApiPortError, match=INVALID_APPROVAL_API_PORT_ERROR):
        resolve_approval_api_port(value)


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
        "approval_request_id": None,
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
        ("sentry_read_file", {"path": "README.md", "session_id": None}),
        (
            "sentry_write_file",
            {"path": "notes.txt", "content": "hello", "session_id": None},
        ),
        ("sentry_list_directory", {"path": ".", "session_id": None}),
        (
            "sentry_run_command",
            {"command": "pytest --version", "session_id": None},
        ),
    ]
    assert read_result["output"] == "read:README.md"
    assert write_result["decision"] == "require_approval"
    assert list_result["output"] == "[file] ."
    assert command_result["error"] == "operation_requires_approval"


def test_mcp_sentry_read_file_forwards_session_id() -> None:
    fake_service = FakeSafeToolService()
    mcp = create_mcp_server(cast(SafeToolService, fake_service))

    _call_tool(
        mcp,
        "sentry_read_file",
        {"path": "README.md", "session_id": "session-1"},
    )

    assert fake_service.calls == [
        (
            "sentry_read_file",
            {"path": "README.md", "session_id": "session-1"},
        ),
    ]


def test_mcp_sentry_write_file_forwards_session_id() -> None:
    fake_service = FakeSafeToolService()
    mcp = create_mcp_server(cast(SafeToolService, fake_service))

    _call_tool(
        mcp,
        "sentry_write_file",
        {"path": "notes.txt", "content": "hello", "session_id": "session-2"},
    )

    assert fake_service.calls == [
        (
            "sentry_write_file",
            {
                "path": "notes.txt",
                "content": "hello",
                "session_id": "session-2",
            },
        ),
    ]


def test_mcp_sentry_list_directory_forwards_session_id() -> None:
    fake_service = FakeSafeToolService()
    mcp = create_mcp_server(cast(SafeToolService, fake_service))

    _call_tool(
        mcp,
        "sentry_list_directory",
        {"path": ".", "session_id": "session-3"},
    )

    assert fake_service.calls == [
        (
            "sentry_list_directory",
            {"path": ".", "session_id": "session-3"},
        ),
    ]


def test_mcp_sentry_run_command_forwards_session_id() -> None:
    fake_service = FakeSafeToolService()
    mcp = create_mcp_server(cast(SafeToolService, fake_service))

    _call_tool(
        mcp,
        "sentry_run_command",
        {"command": "pytest --version", "session_id": "session-4"},
    )

    assert fake_service.calls == [
        (
            "sentry_run_command",
            {"command": "pytest --version", "session_id": "session-4"},
        ),
    ]


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
    capsys: pytest.CaptureFixture[str],
) -> None:
    ran_servers: list[object] = []
    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)

    exit_code = main(
        ["--workspace-root", str(tmp_path)],
        server_runner=ran_servers.append,
    )

    assert exit_code == 0
    assert len(ran_servers) == 1
    captured = capsys.readouterr()
    assert "workspace root resolved:" in captured.err
    assert "audit log path resolved: <disabled>" in captured.err
    assert "approval API port resolved: <disabled>" in captured.err
    assert "FastMCP server run starting" in captured.err


def test_main_does_not_start_approval_api_without_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran_servers: list[object] = []
    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)
    monkeypatch.delenv(APPROVAL_API_PORT_ENV, raising=False)

    def fail_start_approval_api(service: SafeToolService, port: int) -> object:
        raise AssertionError("approval API should be disabled by default")

    monkeypatch.setattr(
        server,
        "start_approval_api_server",
        fail_start_approval_api,
    )

    exit_code = main(
        ["--workspace-root", str(tmp_path)],
        server_runner=ran_servers.append,
    )

    assert exit_code == 0
    assert len(ran_servers) == 1


def test_main_starts_approval_api_with_same_safe_tool_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran_servers: list[object] = []
    started: list[tuple[SafeToolService, int]] = []
    service = SafeToolService(workspace_root=tmp_path)
    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)

    def fake_create_service(
        workspace_root: Path,
        audit_log_path: str | Path | None = None,
    ) -> SafeToolService:
        assert workspace_root == tmp_path.resolve()
        assert audit_log_path is None
        return service

    def fake_start_approval_api(
        safe_tool_service: SafeToolService,
        port: int,
    ) -> object:
        started.append((safe_tool_service, port))
        return object()

    monkeypatch.setattr(server, "create_service", fake_create_service)
    monkeypatch.setattr(server, "start_approval_api_server", fake_start_approval_api)

    exit_code = main(
        ["--workspace-root", str(tmp_path), "--approval-api-port", "8766"],
        server_runner=ran_servers.append,
    )

    assert exit_code == 0
    assert started == [(service, 8766)]
    assert len(ran_servers) == 1


def test_main_rejects_invalid_approval_api_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)

    exit_code = main(
        ["--workspace-root", str(tmp_path), "--approval-api-port", "70000"],
        server_runner=lambda mcp: None,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert INVALID_APPROVAL_API_PORT_ERROR in captured.err


def test_ensure_approval_api_port_available_rejects_bound_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((APPROVAL_API_HOST, 0))
        sock.listen(1)
        port = sock.getsockname()[1]

        with pytest.raises(
            ApprovalApiStartupError,
            match=f"approval API port unavailable on {APPROVAL_API_HOST}:{port}",
        ):
            ensure_approval_api_port_available(port)


def test_main_rejects_unavailable_approval_api_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)
    ran_servers: list[object] = []

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((APPROVAL_API_HOST, 0))
        sock.listen(1)
        port = sock.getsockname()[1]

        exit_code = main(
            [
                "--workspace-root",
                str(tmp_path),
                "--approval-api-port",
                str(port),
            ],
            server_runner=ran_servers.append,
        )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert ran_servers == []
    assert (
        f"approval API port unavailable on {APPROVAL_API_HOST}:{port}"
        in captured.err
    )
    assert "FastMCP server run starting" not in captured.err


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


def test_start_approval_api_server_binds_only_to_localhost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uvicorn

    captured: dict[str, object] = {}

    class _RecordingConfig:
        def __init__(
            self,
            app: object,
            host: str,
            port: int,
            access_log: bool,
        ) -> None:
            captured["app"] = app
            captured["host"] = host
            captured["port"] = port
            captured["access_log"] = access_log
            self.host = host
            self.port = port

    class _RecordingServer:
        def __init__(self, config: _RecordingConfig) -> None:
            self.config = config
            self.started = False
            captured["server_host"] = config.host
            captured["server_port"] = config.port

        def run(self) -> None:
            captured["ran"] = True
            self.started = True

    monkeypatch.setattr(uvicorn, "Config", _RecordingConfig)
    monkeypatch.setattr(uvicorn, "Server", _RecordingServer)

    service = SafeToolService(workspace_root=tmp_path)
    port = _free_local_port()
    thread = start_approval_api_server(service, port=port)
    thread.join(timeout=2.0)

    assert thread.is_alive() is False
    assert APPROVAL_API_HOST == "127.0.0.1"
    assert captured["host"] == "127.0.0.1"
    assert captured["server_host"] == "127.0.0.1"
    assert captured["port"] == port
    assert captured["access_log"] is False
    assert captured.get("ran") is True


def test_start_approval_api_server_logs_thread_startup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import uvicorn

    raw_private_text = "private approval payload"

    class _RecordingConfig:
        def __init__(
            self,
            app: object,
            host: str,
            port: int,
            access_log: bool,
        ) -> None:
            self.host = host
            self.port = port

    class _FailingServer:
        def __init__(self, config: _RecordingConfig) -> None:
            self.config = config
            self.started = False

        def run(self) -> None:
            raise RuntimeError(f"boom {raw_private_text}")

    monkeypatch.setattr(uvicorn, "Config", _RecordingConfig)
    monkeypatch.setattr(uvicorn, "Server", _FailingServer)

    service = SafeToolService(workspace_root=tmp_path)
    port = _free_local_port()

    with pytest.raises(ApprovalApiStartupError):
        start_approval_api_server(service, port=port)

    captured = capsys.readouterr()
    assert "approval API start attempted" in captured.err
    assert "approval API thread failed: RuntimeError" in captured.err
    assert raw_private_text not in captured.err


def _call_tool(
    mcp: object,
    name: str,
    arguments: dict[str, str],
) -> dict[str, object]:
    _, structured_result = asyncio.run(mcp.call_tool(name, arguments))
    return cast(dict[str, object], structured_result)


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((APPROVAL_API_HOST, 0))
        return int(sock.getsockname()[1])
