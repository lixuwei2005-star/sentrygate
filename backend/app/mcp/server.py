import argparse
import os
import socket
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from time import monotonic, sleep
from typing import Protocol, cast

from mcp.server.fastmcp import FastMCP

from app.approvals.api import create_approval_api
from app.audit.jsonl_store import JsonlAuditStore
from app.tools.models import ToolExecutionResult
from app.tools.safe_tools import SafeToolService

WORKSPACE_ROOT_ENV = "SENTRYGATE_WORKSPACE_ROOT"
AUDIT_LOG_PATH_ENV = "SENTRYGATE_AUDIT_LOG_PATH"
APPROVAL_API_PORT_ENV = "SENTRYGATE_APPROVAL_API_PORT"
APPROVAL_API_HOST = "127.0.0.1"
APPROVAL_API_STARTUP_TIMEOUT_SECONDS = 5.0
MISSING_WORKSPACE_ROOT_ERROR = (
    "SENTRYGATE_WORKSPACE_ROOT or --workspace-root is required"
)
INVALID_APPROVAL_API_PORT_ERROR = (
    "SENTRYGATE_APPROVAL_API_PORT or --approval-api-port must be an integer "
    "between 1 and 65535"
)


class WorkspaceRootError(ValueError):
    pass


class ApprovalApiPortError(ValueError):
    pass


class ApprovalApiStartupError(RuntimeError):
    pass


class _ApprovalApiConfig(Protocol):
    port: int


class _ApprovalApiServer(Protocol):
    config: _ApprovalApiConfig
    started: bool

    def run(self) -> None:
        pass


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the SentryGate MCP server.")
    parser.add_argument(
        "--workspace-root",
        help="Explicit workspace root protected by SentryGate.",
    )
    parser.add_argument(
        "--audit-log-path",
        help="Optional local JSONL audit log path for persistent observability.",
    )
    parser.add_argument(
        "--approval-api-port",
        help="Optional localhost port for the local approval API.",
    )
    return parser.parse_args(argv)


def resolve_workspace_root(cli_workspace_root: str | None = None) -> Path:
    workspace_root = _first_nonblank(cli_workspace_root)
    if workspace_root is None:
        workspace_root = _first_nonblank(os.environ.get(WORKSPACE_ROOT_ENV))

    if workspace_root is None:
        raise WorkspaceRootError(MISSING_WORKSPACE_ROOT_ERROR)

    resolved_workspace_root = Path(workspace_root).expanduser().resolve(strict=False)
    if not resolved_workspace_root.exists():
        raise WorkspaceRootError(
            f"workspace root does not exist: {resolved_workspace_root}"
        )
    if not resolved_workspace_root.is_dir():
        raise WorkspaceRootError(
            f"workspace root is not a directory: {resolved_workspace_root}"
        )

    return resolved_workspace_root


def resolve_audit_log_path(cli_audit_log_path: str | None = None) -> Path | None:
    audit_log_path = _first_nonblank(cli_audit_log_path)
    if audit_log_path is None:
        audit_log_path = _first_nonblank(os.environ.get(AUDIT_LOG_PATH_ENV))

    if audit_log_path is None:
        return None

    return Path(audit_log_path).expanduser().resolve(strict=False)


def resolve_approval_api_port(
    cli_approval_api_port: str | None = None,
) -> int | None:
    approval_api_port = _first_nonblank(cli_approval_api_port)
    if approval_api_port is None:
        approval_api_port = _first_nonblank(os.environ.get(APPROVAL_API_PORT_ENV))

    if approval_api_port is None:
        return None

    try:
        port = int(approval_api_port)
    except ValueError:
        raise ApprovalApiPortError(INVALID_APPROVAL_API_PORT_ERROR) from None

    if port < 1 or port > 65535:
        raise ApprovalApiPortError(INVALID_APPROVAL_API_PORT_ERROR)

    return port


def create_service(
    workspace_root: Path,
    audit_log_path: str | Path | None = None,
) -> SafeToolService:
    audit_store = None
    if audit_log_path is not None:
        audit_store = JsonlAuditStore(audit_log_path)

    return SafeToolService(workspace_root=workspace_root, audit_store=audit_store)


def serialize_result(result: ToolExecutionResult) -> dict[str, object]:
    return cast(dict[str, object], result.model_dump(mode="json"))


def create_mcp_server(service: SafeToolService) -> FastMCP:
    mcp = FastMCP("SentryGate")

    @mcp.tool(structured_output=True)
    def sentry_read_file(
        path: str,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """Read a file through SentryGate policy, masking, and audit controls."""
        return serialize_result(
            service.sentry_read_file(path=path, session_id=session_id)
        )

    @mcp.tool(structured_output=True)
    def sentry_write_file(
        path: str,
        content: str,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """Write a file through SentryGate policy, masking, and audit controls."""
        return serialize_result(
            service.sentry_write_file(
                path=path,
                content=content,
                session_id=session_id,
            )
        )

    @mcp.tool(structured_output=True)
    def sentry_list_directory(
        path: str,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """List a directory through SentryGate policy, masking, and audit controls."""
        return serialize_result(
            service.sentry_list_directory(path=path, session_id=session_id)
        )

    @mcp.tool(structured_output=True)
    def sentry_run_command(
        command: str,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """Run a command through SentryGate policy, masking, and audit controls."""
        return serialize_result(
            service.sentry_run_command(command=command, session_id=session_id)
        )

    return mcp


def run_mcp_server(mcp: FastMCP) -> None:
    mcp.run()


def ensure_approval_api_port_available(
    port: int,
    host: str = APPROVAL_API_HOST,
) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
    except OSError as error:
        raise ApprovalApiStartupError(
            f"approval API port unavailable on {host}:{port}: "
            f"{_safe_exception_summary(error)}"
        ) from None


def start_approval_api_server(
    service: SafeToolService,
    port: int,
) -> threading.Thread:
    import uvicorn

    _log_stderr(f"approval API start attempted on {APPROVAL_API_HOST}:{port}")
    ensure_approval_api_port_available(port)

    app = create_approval_api(service)
    config = uvicorn.Config(
        app,
        host=APPROVAL_API_HOST,
        port=port,
        access_log=False,
    )
    api_server = cast(_ApprovalApiServer, uvicorn.Server(config))
    startup_errors: list[BaseException] = []
    thread = threading.Thread(
        target=_run_approval_api_server,
        args=(api_server, startup_errors),
        name=f"sentrygate-approval-api-{port}",
        daemon=True,
    )
    thread.start()
    _wait_for_approval_api_start(api_server, thread, startup_errors)
    _log_stderr(f"approval API started on {APPROVAL_API_HOST}:{port}")
    return thread


def main(
    argv: Sequence[str] | None = None,
    server_runner: Callable[[FastMCP], None] = run_mcp_server,
) -> int:
    args = parse_args(argv)
    try:
        workspace_root = resolve_workspace_root(args.workspace_root)
        _log_stderr(f"workspace root resolved: {workspace_root}")
        audit_log_path = resolve_audit_log_path(args.audit_log_path)
        _log_stderr(f"audit log path resolved: {_optional_path(audit_log_path)}")
        approval_api_port = resolve_approval_api_port(args.approval_api_port)
        _log_stderr(
            f"approval API port resolved: {_optional_port(approval_api_port)}"
        )
        service = create_service(workspace_root, audit_log_path=audit_log_path)
    except (WorkspaceRootError, ApprovalApiPortError) as error:
        print(str(error), file=sys.stderr)
        return 1

    try:
        if approval_api_port is not None:
            start_approval_api_server(service, approval_api_port)
    except ApprovalApiStartupError as error:
        print(str(error), file=sys.stderr)
        return 1

    mcp = create_mcp_server(service)
    _log_stderr("FastMCP server run starting")
    server_runner(mcp)
    return 0


def _first_nonblank(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    if stripped == "":
        return None
    return stripped


def _run_approval_api_server(
    api_server: _ApprovalApiServer,
    startup_errors: list[BaseException],
) -> None:
    try:
        api_server.run()
    except (Exception, SystemExit) as error:
        startup_errors.append(error)
        _log_stderr(f"approval API thread failed: {_safe_exception_summary(error)}")


def _wait_for_approval_api_start(
    api_server: _ApprovalApiServer,
    thread: threading.Thread,
    startup_errors: list[BaseException],
    timeout_seconds: float = APPROVAL_API_STARTUP_TIMEOUT_SECONDS,
) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if api_server.started:
            return
        if startup_errors:
            error = startup_errors[0]
            port = _approval_api_server_port(api_server)
            raise ApprovalApiStartupError(
                f"approval API failed to start on {APPROVAL_API_HOST}:"
                f"{port}: {_safe_exception_summary(error)}"
            ) from None
        if not thread.is_alive():
            port = _approval_api_server_port(api_server)
            raise ApprovalApiStartupError(
                f"approval API stopped before startup on {APPROVAL_API_HOST}:"
                f"{port}"
            )
        sleep(0.01)

    raise ApprovalApiStartupError(
        f"approval API did not report startup within {timeout_seconds:.1f}s on "
        f"{APPROVAL_API_HOST}:{_approval_api_server_port(api_server)}"
    )


def _safe_exception_summary(error: BaseException) -> str:
    if isinstance(error, SystemExit):
        return f"SystemExit: code={error.code}"
    if isinstance(error, OSError):
        message = error.strerror or str(error)
        return f"{type(error).__name__}: {message}"
    return type(error).__name__


def _approval_api_server_port(api_server: _ApprovalApiServer) -> int:
    return api_server.config.port


def _log_stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _optional_path(path: Path | None) -> str:
    if path is None:
        return "<disabled>"
    return str(path)


def _optional_port(port: int | None) -> str:
    if port is None:
        return "<disabled>"
    return str(port)


if __name__ == "__main__":
    raise SystemExit(main())
