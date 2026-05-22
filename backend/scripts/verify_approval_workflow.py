import sys
from pathlib import Path
from tempfile import TemporaryDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.tools.safe_tools import SafeToolService  # noqa: E402


def main() -> None:
    with TemporaryDirectory(prefix="sentrygate-approval-verify-") as temp_dir:
        workspace = Path(temp_dir)
        service = SafeToolService(workspace_root=workspace)

        approved_path = workspace / "approved.txt"
        approved_result = service.sentry_write_file(
            "approved.txt",
            "hello approved workflow",
        )
        print(
            "Scenario 1 initial:",
            f"decision={approved_result.decision}",
            f"risk_score={approved_result.risk_score}",
            f"approval_request_id={approved_result.approval_request_id}",
        )
        assert approved_result.decision == "require_approval"
        assert approved_result.approval_request_id is not None
        assert not approved_path.exists()

        approved_execution = service.approve_request(
            approved_result.approval_request_id
        )
        assert approved_execution.ok is True
        assert approved_path.exists()
        print("Scenario 1 approved content:", approved_path.read_text(encoding="utf-8"))

        rejected_path = workspace / "rejected.txt"
        rejected_result = service.sentry_write_file(
            "rejected.txt",
            "hello rejected workflow",
        )
        assert rejected_result.decision == "require_approval"
        assert rejected_result.approval_request_id is not None

        rejected_request = service.reject_request(rejected_result.approval_request_id)
        assert not rejected_path.exists()
        print("Scenario 2 rejected status:", rejected_request.status)

        env_path = workspace / ".env"
        env_path.write_text("FAKE_TOKEN=not-a-real-secret\n", encoding="utf-8")
        blocked_result = service.sentry_read_file(".env")
        assert blocked_result.decision == "block"
        assert blocked_result.approval_request_id is None
        print(
            "Scenario 3 blocked:",
            f"decision={blocked_result.decision}",
            f"risk_score={blocked_result.risk_score}",
            f"approval_request_id={blocked_result.approval_request_id}",
        )

    print("Approval workflow verification passed")


if __name__ == "__main__":
    main()
