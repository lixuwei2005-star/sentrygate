from datetime import UTC, datetime

from app.approvals.models import ApprovalRequest


class ApprovalStoreError(ValueError):
    pass


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._execution_payloads: dict[str, object] = {}

    def create(self, request: ApprovalRequest) -> ApprovalRequest:
        if request.status != "pending":
            raise ApprovalStoreError("approval_request_must_start_pending")
        if request.request_id in self._requests:
            raise ApprovalStoreError("approval_request_already_exists")

        stored_request = request.model_copy(deep=True)
        self._requests[stored_request.request_id] = stored_request
        return stored_request.model_copy(deep=True)

    def get(self, request_id: str) -> ApprovalRequest | None:
        request = self._refresh_expiry(request_id)
        if request is None:
            return None
        return request.model_copy(deep=True)

    def list_pending(
        self,
        session_id: str | None = None,
    ) -> list[ApprovalRequest]:
        for request_id in list(self._requests):
            self._refresh_expiry(request_id)

        pending = [
            request
            for request in self._requests.values()
            if request.status == "pending"
            and (session_id is None or request.session_id == session_id)
        ]
        return [request.model_copy(deep=True) for request in pending]

    def approve(self, request_id: str) -> ApprovalRequest:
        request = self._pending_request_or_raise(request_id)
        approved_request = request.model_copy(update={"status": "approved"}, deep=True)
        self._requests[request_id] = approved_request
        return approved_request.model_copy(deep=True)

    def reject(self, request_id: str) -> ApprovalRequest:
        request = self._pending_request_or_raise(request_id)
        rejected_request = request.model_copy(update={"status": "rejected"}, deep=True)
        self._requests[request_id] = rejected_request
        self.discard_execution_payload(request_id)
        return rejected_request.model_copy(deep=True)

    def mark_executed(self, request_id: str) -> ApprovalRequest:
        request = self._refresh_expiry(request_id)
        if request is None:
            raise ApprovalStoreError("approval_request_not_found")
        if request.status not in {"approved", "executed"}:
            raise ApprovalStoreError(f"approval_request_not_approved:{request.status}")

        executed_request = request.model_copy(update={"status": "executed"}, deep=True)
        self._requests[request_id] = executed_request
        self.discard_execution_payload(request_id)
        return executed_request.model_copy(deep=True)

    def attach_execution_payload(self, request_id: str, payload: object) -> None:
        if request_id not in self._requests:
            raise ApprovalStoreError("approval_request_not_found")
        if request_id in self._execution_payloads:
            raise ApprovalStoreError("approval_execution_payload_already_exists")
        self._execution_payloads[request_id] = payload

    def get_execution_payload(self, request_id: str) -> object | None:
        self._refresh_expiry(request_id)
        return self._execution_payloads.get(request_id)

    def discard_execution_payload(self, request_id: str) -> None:
        self._execution_payloads.pop(request_id, None)

    def _pending_request_or_raise(self, request_id: str) -> ApprovalRequest:
        request = self._refresh_expiry(request_id)
        if request is None:
            raise ApprovalStoreError("approval_request_not_found")
        if request.status != "pending":
            raise ApprovalStoreError(f"approval_request_not_pending:{request.status}")
        return request

    def _refresh_expiry(self, request_id: str) -> ApprovalRequest | None:
        request = self._requests.get(request_id)
        if request is None:
            return None
        if (
            request.status == "pending"
            and request.expires_at is not None
            and request.expires_at <= datetime.now(UTC)
        ):
            request = request.model_copy(update={"status": "expired"}, deep=True)
            self._requests[request_id] = request
            self.discard_execution_payload(request_id)
        return request
