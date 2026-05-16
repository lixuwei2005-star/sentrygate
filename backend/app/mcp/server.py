import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from mcp.server.fastmcp import FastMCP

from app.audit.jsonl_store import JsonlAuditStore
from app.tools.models import ToolExecutionResult
from app.tools.safe_tools import SafeToolService

WORKSPACE_ROOT_ENV = "SENTRYGATE_WORKSPACE_ROOT"
AUDIT_LOG_PATH_ENV = "SENTRYGATE_AUDIT_LOG_PATH"
MISSING_WORKSPACE_ROOT_ERROR = (
    "SENTRYGATE_WORKSPACE_ROOT or --workspace-root is required"
)


class WorkspaceRootError(ValueError):
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


def main(
    argv: Sequence[str] | None = None,
    server_runner: Callable[[FastMCP], None] = run_mcp_server,
) -> int:
    args = parse_args(argv)
    try:
        workspace_root = resolve_workspace_root(args.workspace_root)
        audit_log_path = resolve_audit_log_path(args.audit_log_path)
        service = create_service(workspace_root, audit_log_path=audit_log_path)
    except WorkspaceRootError as error:
        print(str(error), file=sys.stderr)
        return 1

    mcp = create_mcp_server(service)
    server_runner(mcp)
    return 0


def _first_nonblank(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    if stripped == "":
        return None
    return stripped


if __name__ == "__main__":
    raise SystemExit(main())
