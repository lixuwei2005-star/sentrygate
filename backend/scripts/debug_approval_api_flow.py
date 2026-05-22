import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.approvals.api import create_approval_api  # noqa: E402
from app.tools.safe_tools import SafeToolService  # noqa: E402

_LOCAL_BASE_URL = "http://127.0.0.1:8766"


def main() -> None:
    with TemporaryDirectory(prefix="sentrygate-approval-api-debug-") as temp_dir:
        workspace = Path(temp_dir)
        service = SafeToolService(workspace_root=workspace)
        client = TestClient(create_approval_api(service), base_url=_LOCAL_BASE_URL)

        target_name = "debug_approval_api_flow.txt"
        target_path = workspace / target_name
        initial_result = service.sentry_write_file(
            target_name,
            "hello from debug approval flow",
        )
        assert initial_result.decision == "require_approval"
        assert initial_result.approval_request_id is not None
        assert not target_path.exists()

        pending_response = client.get("/approvals/pending")
        assert pending_response.status_code == 200
        pending = pending_response.json()
        assert len(pending) == 1
        assert pending[0]["request_id"] == initial_result.approval_request_id
        assert pending[0]["tool_name"] == "write_file"

        approve_response = client.post(
            f"/approvals/{initial_result.approval_request_id}/approve"
        )
        assert approve_response.status_code == 200
        approved = approve_response.json()
        assert approved["ok"] is True
        assert target_path.read_text(encoding="utf-8") == (
            "hello from debug approval flow"
        )

        pending_after_approve = client.get("/approvals/pending")
        assert pending_after_approve.status_code == 200
        assert pending_after_approve.json() == []

        print(
            "debug approval API flow passed: "
            f"request_id={initial_result.approval_request_id}"
        )


if __name__ == "__main__":
    main()
