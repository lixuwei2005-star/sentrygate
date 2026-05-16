import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from app.audit.models import AuditEvent
from app.audit.store import AuditStore, InMemoryAuditStore
from app.privacy.masker import MaskingFinding, PrivacyMasker
from app.risk.models import RiskResult, ToolCall
from app.risk.policy import ALLOW_MAX_SCORE, REQUIRE_APPROVAL_MAX_SCORE
from app.risk.scorer import RiskScorer
from app.tools.models import ToolExecutionResult

MAX_AUDIT_SUMMARY_CHARS = 2_000
DEFAULT_COMMAND_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class _AuditSpanContext:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    started_at: datetime
    started_perf_counter: float


class RiskReviewProvider(Protocol):
    def review_risk(
        self,
        tool_call: ToolCall,
        original_result: RiskResult,
        arguments_summary: str,
    ) -> RiskResult:
        ...


class SafeToolService:
    def __init__(
        self,
        workspace_root: str | Path,
        risk_scorer: RiskScorer | None = None,
        masker: PrivacyMasker | None = None,
        audit_store: AuditStore | None = None,
        command_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        risk_reviewer: RiskReviewProvider | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve(strict=False)
        self.risk_scorer = risk_scorer or RiskScorer(self.workspace_root)
        self.masker = masker or PrivacyMasker()
        self.audit_store = audit_store or InMemoryAuditStore()
        self.command_timeout_seconds = command_timeout_seconds
        self.risk_reviewer = risk_reviewer or self._default_risk_reviewer()

    def sentry_read_file(
        self,
        path: str,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        audit_context = self._start_audit_span(session_id)
        tool_call = ToolCall(
            tool_name="read_file",
            arguments={"path": path},
            session_id=session_id,
        )
        risk_result = self.risk_scorer.score_tool_call(tool_call)
        argument_summary, argument_findings = self._mask_text(
            f"path={self._safe_relative_display(path)}"
        )
        risk_result = self._review_risk_result(
            tool_call,
            risk_result,
            argument_summary,
        )

        if risk_result.decision != "allow":
            return self._denied_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                findings=argument_findings,
                audit_context=audit_context,
            )

        try:
            target_path = self._resolve_workspace_path(path)
        except PermissionError as error:
            return self._setup_error_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                raw_error=f"path_outside_workspace: {error}",
                findings=argument_findings,
                audit_context=audit_context,
            )

        try:
            content = target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            return self._execution_error_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                raw_error=f"binary_file_not_supported: {error}",
                findings=argument_findings,
                audit_context=audit_context,
            )
        except OSError as error:
            return self._execution_error_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                raw_error=f"read_file_failed: {error}",
                findings=argument_findings,
                audit_context=audit_context,
            )

        masked_content, output_findings = self._mask_text(content)
        findings = self._merge_findings(argument_findings, output_findings)
        output_summary = self._file_content_summary(
            action="read_file",
            char_count=len(content),
            finding_count=len(output_findings),
        )
        self._append_audit_event(
            tool_call=tool_call,
            risk_result=risk_result,
            arguments_summary=argument_summary,
            output_summary=output_summary,
            findings=findings,
            executed=True,
            audit_context=audit_context,
        )
        return ToolExecutionResult(
            ok=True,
            decision=risk_result.decision,
            risk_score=risk_result.risk_score,
            reasons=risk_result.reasons,
            output=masked_content,
            masked_findings=findings,
        )

    def sentry_write_file(
        self,
        path: str,
        content: str,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        audit_context = self._start_audit_span(session_id)
        tool_call = ToolCall(
            tool_name="write_file",
            arguments={"path": path, "content": content},
            session_id=session_id,
        )
        risk_result = self.risk_scorer.score_tool_call(tool_call)
        masked_path, path_findings = self._mask_text(self._safe_relative_display(path))
        _, content_findings = self._mask_text(content)
        argument_summary = self._bounded_summary(
            f"path={masked_path}; content_chars={len(content)}"
        )
        findings = self._merge_findings(path_findings, content_findings)
        risk_result = self._review_risk_result(
            tool_call,
            risk_result,
            argument_summary,
        )

        if risk_result.decision != "allow":
            return self._denied_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                findings=findings,
                audit_context=audit_context,
            )

        try:
            target_path = self._resolve_workspace_path(path)
        except PermissionError as error:
            return self._setup_error_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                raw_error=f"path_outside_workspace: {error}",
                findings=findings,
                audit_context=audit_context,
            )

        try:
            target_path.write_text(content, encoding="utf-8")
        except OSError as error:
            return self._execution_error_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                raw_error=f"write_file_failed: {error}",
                findings=findings,
                audit_context=audit_context,
            )

        output, output_findings = self._mask_text(
            f"write_file succeeded; chars={len(content)}"
        )
        findings = self._merge_findings(findings, output_findings)
        self._append_audit_event(
            tool_call=tool_call,
            risk_result=risk_result,
            arguments_summary=argument_summary,
            output_summary=self._bounded_summary(output),
            findings=findings,
            executed=True,
            audit_context=audit_context,
        )
        return ToolExecutionResult(
            ok=True,
            decision=risk_result.decision,
            risk_score=risk_result.risk_score,
            reasons=risk_result.reasons,
            output=output,
            masked_findings=findings,
        )

    def sentry_list_directory(
        self,
        path: str,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        audit_context = self._start_audit_span(session_id)
        tool_call = ToolCall(
            tool_name="list_directory",
            arguments={"path": path},
            session_id=session_id,
        )
        risk_result = self.risk_scorer.score_tool_call(tool_call)
        argument_summary, argument_findings = self._mask_text(
            f"path={self._safe_relative_display(path)}"
        )
        risk_result = self._review_risk_result(
            tool_call,
            risk_result,
            argument_summary,
        )

        if risk_result.decision != "allow":
            return self._denied_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                findings=argument_findings,
                audit_context=audit_context,
            )

        try:
            target_path = self._resolve_workspace_path(path)
        except PermissionError as error:
            return self._setup_error_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                raw_error=f"path_outside_workspace: {error}",
                findings=argument_findings,
                audit_context=audit_context,
            )

        try:
            entries = self._directory_listing(target_path)
        except OSError as error:
            return self._execution_error_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                raw_error=f"list_directory_failed: {error}",
                findings=argument_findings,
                audit_context=audit_context,
            )

        output = "\n".join(entries)
        masked_output, output_findings = self._mask_text(output)
        findings = self._merge_findings(argument_findings, output_findings)
        output_summary = self._bounded_summary(
            f"list_directory succeeded; entries={len(entries)}; "
            f"listing={masked_output}"
        )
        self._append_audit_event(
            tool_call=tool_call,
            risk_result=risk_result,
            arguments_summary=argument_summary,
            output_summary=output_summary,
            findings=findings,
            executed=True,
            audit_context=audit_context,
        )
        return ToolExecutionResult(
            ok=True,
            decision=risk_result.decision,
            risk_score=risk_result.risk_score,
            reasons=risk_result.reasons,
            output=masked_output,
            masked_findings=findings,
        )

    def sentry_run_command(
        self,
        command: str,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        audit_context = self._start_audit_span(session_id)
        tool_call = ToolCall(
            tool_name="run_command",
            arguments={"command": command},
            session_id=session_id,
        )
        risk_result = self.risk_scorer.score_tool_call(tool_call)
        argument_summary, argument_findings = self._mask_text(
            self._bounded_summary(f"command={command}")
        )
        risk_result = self._review_risk_result(
            tool_call,
            risk_result,
            argument_summary,
        )

        if risk_result.decision != "allow":
            return self._denied_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                findings=argument_findings,
                audit_context=audit_context,
            )

        try:
            argv = self._command_argv(command)
        except ValueError as error:
            return self._setup_error_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                raw_error=f"empty_command: {error}",
                findings=argument_findings,
                audit_context=audit_context,
            )

        try:
            completed = subprocess.run(
                argv,
                cwd=self.workspace_root,
                timeout=self.command_timeout_seconds,
                capture_output=True,
                text=True,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return self._execution_error_result(
                tool_call=tool_call,
                risk_result=risk_result,
                arguments_summary=argument_summary,
                raw_error=f"run_command_failed: {error}",
                findings=argument_findings,
                audit_context=audit_context,
            )

        raw_output = (
            f"exit_code={completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
        masked_output, output_findings = self._mask_text(raw_output)
        findings = self._merge_findings(argument_findings, output_findings)
        self._append_audit_event(
            tool_call=tool_call,
            risk_result=risk_result,
            arguments_summary=argument_summary,
            output_summary=self._bounded_summary(masked_output),
            findings=findings,
            executed=True,
            audit_context=audit_context,
        )
        return ToolExecutionResult(
            ok=completed.returncode == 0,
            decision=risk_result.decision,
            risk_score=risk_result.risk_score,
            reasons=risk_result.reasons,
            output=masked_output,
            masked_findings=findings,
        )

    def _denied_result(
        self,
        tool_call: ToolCall,
        risk_result: RiskResult,
        arguments_summary: str,
        findings: tuple[MaskingFinding, ...],
        audit_context: _AuditSpanContext,
    ) -> ToolExecutionResult:
        raw_error = (
            "operation_blocked"
            if risk_result.decision == "block"
            else "operation_requires_approval"
        )
        error, error_findings = self._mask_text(raw_error)
        findings = self._merge_findings(findings, error_findings)
        self._append_audit_event(
            tool_call=tool_call,
            risk_result=risk_result,
            arguments_summary=arguments_summary,
            output_summary=error,
            findings=findings,
            executed=False,
            audit_context=audit_context,
        )
        return ToolExecutionResult(
            ok=False,
            decision=risk_result.decision,
            risk_score=risk_result.risk_score,
            reasons=risk_result.reasons,
            error=error,
            masked_findings=findings,
        )

    def _setup_error_result(
        self,
        tool_call: ToolCall,
        risk_result: RiskResult,
        arguments_summary: str,
        raw_error: str,
        findings: tuple[MaskingFinding, ...],
        audit_context: _AuditSpanContext,
    ) -> ToolExecutionResult:
        error, error_findings = self._mask_text(raw_error)
        findings = self._merge_findings(findings, error_findings)
        self._append_audit_event(
            tool_call=tool_call,
            risk_result=risk_result,
            arguments_summary=arguments_summary,
            output_summary=self._bounded_summary(error),
            findings=findings,
            executed=False,
            audit_context=audit_context,
        )
        return ToolExecutionResult(
            ok=False,
            decision=risk_result.decision,
            risk_score=risk_result.risk_score,
            reasons=risk_result.reasons,
            error=error,
            masked_findings=findings,
        )

    def _execution_error_result(
        self,
        tool_call: ToolCall,
        risk_result: RiskResult,
        arguments_summary: str,
        raw_error: str,
        findings: tuple[MaskingFinding, ...],
        audit_context: _AuditSpanContext,
    ) -> ToolExecutionResult:
        error, error_findings = self._mask_text(raw_error)
        findings = self._merge_findings(findings, error_findings)
        self._append_audit_event(
            tool_call=tool_call,
            risk_result=risk_result,
            arguments_summary=arguments_summary,
            output_summary=self._bounded_summary(error),
            findings=findings,
            executed=True,
            audit_context=audit_context,
        )
        return ToolExecutionResult(
            ok=False,
            decision=risk_result.decision,
            risk_score=risk_result.risk_score,
            reasons=risk_result.reasons,
            error=error,
            masked_findings=findings,
        )

    def _append_audit_event(
        self,
        tool_call: ToolCall,
        risk_result: RiskResult,
        arguments_summary: str,
        output_summary: str | None,
        findings: tuple[MaskingFinding, ...],
        executed: bool,
        audit_context: _AuditSpanContext,
    ) -> None:
        ended_at = datetime.now(UTC)
        latency_ms = max(
            (perf_counter() - audit_context.started_perf_counter) * 1000,
            0.0,
        )
        self.audit_store.append(
            AuditEvent(
                session_id=tool_call.session_id,
                trace_id=audit_context.trace_id,
                span_id=audit_context.span_id,
                parent_span_id=audit_context.parent_span_id,
                started_at=audit_context.started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                tool_name=tool_call.tool_name,
                decision=risk_result.decision,
                risk_score=risk_result.risk_score,
                reasons=risk_result.reasons,
                arguments_summary=self._bounded_summary(arguments_summary),
                output_summary=(
                    None
                    if output_summary is None
                    else self._bounded_summary(output_summary)
                ),
                masked_findings=findings,
                executed=executed,
            )
        )

    @staticmethod
    def _start_audit_span(session_id: str | None) -> _AuditSpanContext:
        return _AuditSpanContext(
            trace_id=session_id or str(uuid4()),
            span_id=str(uuid4()),
            parent_span_id=None,
            started_at=datetime.now(UTC),
            started_perf_counter=perf_counter(),
        )

    def _review_risk_result(
        self,
        tool_call: ToolCall,
        risk_result: RiskResult,
        arguments_summary: str,
    ) -> RiskResult:
        if self.risk_reviewer is None:
            return risk_result
        if not self._is_review_candidate(risk_result, arguments_summary):
            return risk_result

        try:
            reviewed_result = self.risk_reviewer.review_risk(
                tool_call,
                risk_result,
                arguments_summary,
            )
        except Exception:
            return risk_result

        merged_result = self._conservative_review_result(risk_result, reviewed_result)
        return self._mask_added_reasons(risk_result, merged_result)

    def _mask_added_reasons(
        self,
        original_result: RiskResult,
        merged_result: RiskResult,
    ) -> RiskResult:
        original_reasons = set(original_result.reasons)
        masked_reasons: list[str] = []
        changed = False
        for reason in merged_result.reasons:
            if reason in original_reasons:
                masked_reasons.append(reason)
                continue
            masked_reason, _ = self._mask_text(reason)
            if masked_reason != reason:
                changed = True
            masked_reasons.append(masked_reason)

        if not changed:
            return merged_result

        return RiskResult(
            risk_score=merged_result.risk_score,
            decision=merged_result.decision,
            reasons=masked_reasons,
        )

    @staticmethod
    def _is_review_candidate(
        risk_result: RiskResult,
        arguments_summary: str,
    ) -> bool:
        return (
            risk_result.decision == "require_approval"
            and ALLOW_MAX_SCORE < risk_result.risk_score <= REQUIRE_APPROVAL_MAX_SCORE
            and arguments_summary.strip() != ""
        )

    @staticmethod
    def _conservative_review_result(
        original_result: RiskResult,
        reviewed_result: RiskResult,
    ) -> RiskResult:
        if original_result.decision in {"allow", "block"}:
            return original_result
        if reviewed_result == original_result:
            return original_result

        final_score = max(original_result.risk_score, reviewed_result.risk_score)
        final_decision = original_result.decision
        if (
            reviewed_result.decision == "block"
            or final_score > REQUIRE_APPROVAL_MAX_SCORE
        ):
            final_decision = "block"

        reasons = list(original_result.reasons)
        for reason in reviewed_result.reasons:
            if reason not in reasons:
                reasons.append(reason)

        return RiskResult(
            risk_score=final_score,
            decision=final_decision,
            reasons=reasons,
        )

    @staticmethod
    def _default_risk_reviewer() -> RiskReviewProvider | None:
        from app.risk.lmstudio_client import LMStudioRiskReviewer

        reviewer = LMStudioRiskReviewer.from_env()
        if not reviewer.enabled:
            return None
        return reviewer

    def _resolve_workspace_path(self, path: str) -> Path:
        input_path = Path(path)
        if input_path.is_absolute():
            target_path = input_path.resolve(strict=False)
        else:
            target_path = (self.workspace_root / input_path).resolve(strict=False)

        if not target_path.is_relative_to(self.workspace_root):
            raise PermissionError("path_outside_workspace")

        return target_path

    def _safe_relative_display(self, path: str) -> str:
        try:
            target_path = self._resolve_workspace_path(path)
        except OSError:
            return path

        try:
            return target_path.relative_to(self.workspace_root).as_posix()
        except ValueError:
            return path

    @staticmethod
    def _directory_listing(path: Path) -> list[str]:
        entries: list[str] = []
        for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
            prefix = "[dir]" if child.is_dir() else "[file]"
            entries.append(f"{prefix} {child.name}")
        return entries

    def _mask_text(self, text: str) -> tuple[str, tuple[MaskingFinding, ...]]:
        result = self.masker.mask_text(text)
        return result.masked_text, result.findings

    @staticmethod
    def _merge_findings(
        *finding_groups: tuple[MaskingFinding, ...],
    ) -> tuple[MaskingFinding, ...]:
        findings_by_token: dict[str, MaskingFinding] = {}
        for finding_group in finding_groups:
            for finding in finding_group:
                findings_by_token.setdefault(finding.token, finding)
        return tuple(findings_by_token.values())

    @staticmethod
    def _bounded_summary(text: str) -> str:
        if len(text) <= MAX_AUDIT_SUMMARY_CHARS:
            return text
        return f"{text[: MAX_AUDIT_SUMMARY_CHARS - 3]}..."

    @staticmethod
    def _file_content_summary(
        action: str,
        char_count: int,
        finding_count: int,
    ) -> str:
        return (
            f"{action} succeeded; chars={char_count}; "
            f"masked_findings={finding_count}"
        )

    @staticmethod
    def _command_argv(command: str) -> list[str]:
        argv = shlex.split(command, posix=os.name != "nt")
        if argv == []:
            raise ValueError("empty_command")
        return argv


_default_service: SafeToolService | None = None


def configure_default_service(
    workspace_root: str | Path,
    risk_scorer: RiskScorer | None = None,
    masker: PrivacyMasker | None = None,
    audit_store: AuditStore | None = None,
    command_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    risk_reviewer: RiskReviewProvider | None = None,
) -> None:
    global _default_service
    _default_service = SafeToolService(
        workspace_root=workspace_root,
        risk_scorer=risk_scorer,
        masker=masker,
        audit_store=audit_store,
        command_timeout_seconds=command_timeout_seconds,
        risk_reviewer=risk_reviewer,
    )


def reset_default_service() -> None:
    global _default_service
    _default_service = None


def _get_default_service() -> SafeToolService:
    if _default_service is None:
        raise RuntimeError(
            "SafeToolService is not configured. "
            "Call configure_default_service() before using public wrappers."
        )
    return _default_service


def sentry_read_file(
    path: str,
    session_id: str | None = None,
) -> ToolExecutionResult:
    return _get_default_service().sentry_read_file(path, session_id=session_id)


def sentry_write_file(
    path: str,
    content: str,
    session_id: str | None = None,
) -> ToolExecutionResult:
    return _get_default_service().sentry_write_file(
        path,
        content,
        session_id=session_id,
    )


def sentry_list_directory(
    path: str,
    session_id: str | None = None,
) -> ToolExecutionResult:
    return _get_default_service().sentry_list_directory(path, session_id=session_id)


def sentry_run_command(
    command: str,
    session_id: str | None = None,
) -> ToolExecutionResult:
    return _get_default_service().sentry_run_command(command, session_id=session_id)
