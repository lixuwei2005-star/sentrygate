import logging
from collections.abc import Awaitable, Callable
from typing import cast
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from app.approvals.models import ApprovalRequest
from app.approvals.store import ApprovalStoreError
from app.tools.safe_tools import SafeToolService

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
_NON_LOCAL_REJECT_DETAIL = "non_local_request_rejected"

_logger = logging.getLogger("sentrygate.approval_api")


def create_approval_api(service: SafeToolService) -> FastAPI:
    app = FastAPI(
        title="SentryGate Local Approval API",
        description="Local prototype API for approving pending SentryGate requests.",
    )

    @app.middleware("http")
    async def _enforce_local_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        host_header = request.headers.get("host")
        if not _is_local_host_header(host_header):
            return _non_local_response()
        origin_header = request.headers.get("origin")
        if origin_header is not None and not _is_local_origin(origin_header):
            return _non_local_response()
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "service": "sentrygate-approval-api"}

    @app.get("/approvals/pending", response_model=list[ApprovalRequest])
    def list_pending_approvals() -> list[ApprovalRequest]:
        try:
            return service.approval_store.list_pending()
        except Exception as error:
            _log_safe_exception("approval_pending_failed", error)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="approval_pending_failed",
            ) from None

    @app.post("/approvals/{request_id}/approve")
    def approve_request(request_id: str) -> dict[str, object]:
        try:
            result = service.approve_request(request_id)
        except Exception as error:
            _log_safe_exception("approval_approve_failed", error)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="approval_approve_failed",
            ) from None
        return cast(dict[str, object], result.model_dump(mode="json"))

    @app.post("/approvals/{request_id}/reject", response_model=ApprovalRequest)
    def reject_request(request_id: str) -> ApprovalRequest:
        try:
            return service.reject_request(request_id)
        except ApprovalStoreError as error:
            status_code, detail = _safe_store_error_response(error)
            raise HTTPException(status_code=status_code, detail=detail) from None
        except Exception as error:
            _log_safe_exception("approval_reject_failed", error)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="approval_reject_failed",
            ) from None

    return app


def _safe_store_error_response(error: ApprovalStoreError) -> tuple[int, str]:
    message = str(error)
    if message == "approval_request_not_found":
        return status.HTTP_404_NOT_FOUND, "approval_request_not_found"
    if message.startswith("approval_request_not_pending"):
        return status.HTTP_409_CONFLICT, "approval_request_not_pending"
    return status.HTTP_400_BAD_REQUEST, "approval_request_invalid"


def _non_local_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": _NON_LOCAL_REJECT_DETAIL},
    )


def _is_local_host_header(host_header: str | None) -> bool:
    if host_header is None:
        return False

    candidate = host_header.strip()
    if candidate == "":
        return False

    if ":" in candidate:
        hostname, _, port = candidate.rpartition(":")
        if port == "" or not port.isdigit():
            return False
    else:
        hostname = candidate

    return hostname.lower() in _LOCAL_HOSTS


def _is_local_origin(origin: str) -> bool:
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False

    hostname = parsed.hostname
    if hostname is None:
        return False
    return hostname.lower() in _LOCAL_HOSTS


def _log_safe_exception(safe_detail: str, error: BaseException) -> None:
    _logger.warning("%s: %s", safe_detail, type(error).__name__)
