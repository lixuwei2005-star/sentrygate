import shlex
import time
from collections.abc import Callable
from pathlib import Path

from app.risk.models import RiskDecision, RiskResult, ToolCall
from app.risk.policy import (
    ALLOW_MAX_SCORE,
    ANONYMOUS_SESSION_ID,
    BEHAVIOR_WINDOW_SECONDS,
    HARD_BLOCK_SCORE,
    INVALID_ARGUMENT_SCORE,
    POWERSHELL_FORCE_FLAGS,
    POWERSHELL_RECURSE_FLAGS,
    READ_FILE_BEHAVIOR_SCORE_BUMP,
    READ_FILE_WINDOW_LIMIT,
    REMOVE_ITEM_ALIASES,
    REQUIRE_APPROVAL_MAX_SCORE,
    RUN_COMMAND_BEHAVIOR_SCORE_BUMP,
    RUN_COMMAND_SCORE,
    RUN_COMMAND_WINDOW_LIMIT,
    SAFE_LIST_DIRECTORY_SCORE,
    SAFE_READ_FILE_SCORE,
    SENSITIVE_COMPONENT_PATHS,
    SENSITIVE_EXTENSIONS,
    SENSITIVE_FILE_NAMES,
    SUPPORTED_TOOL_NAMES,
    UNKNOWN_TOOL_SCORE,
    WRITE_FILE_SCORE,
)


class BehaviorTracker:
    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._events_by_session: dict[str, list[tuple[float, str]]] = {}

    def record_and_count(
        self,
        session_id: str | None,
        tool_name: str,
    ) -> dict[str, int]:
        session_key = session_id or ANONYMOUS_SESSION_ID
        now = self._clock()
        cutoff = now - BEHAVIOR_WINDOW_SECONDS
        events = self._events_by_session.setdefault(session_key, [])
        events[:] = [
            (event_time, name)
            for event_time, name in events
            if event_time >= cutoff
        ]
        events.append((now, tool_name))

        return {
            "read_file": sum(1 for _, name in events if name == "read_file"),
            "run_command": sum(1 for _, name in events if name == "run_command"),
        }


class RiskScorer:
    def __init__(
        self,
        workspace_root: str | Path,
        behavior_tracker: BehaviorTracker | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root).resolve(strict=False)
        self._behavior_tracker = behavior_tracker or BehaviorTracker()

    def score(self, tool_call: ToolCall) -> RiskResult:
        if tool_call.tool_name not in SUPPORTED_TOOL_NAMES:
            return self._result(
                UNKNOWN_TOOL_SCORE,
                ["unknown_tool_not_covered_by_policy"],
            )

        if tool_call.tool_name == "run_command":
            return self._score_run_command(tool_call)

        return self._score_path_tool(tool_call)

    def score_tool_call(self, tool_call: ToolCall) -> RiskResult:
        return self.score(tool_call)

    def _score_path_tool(self, tool_call: ToolCall) -> RiskResult:
        path_value = tool_call.arguments.get("path")
        if not isinstance(path_value, str):
            return self._result(
                INVALID_ARGUMENT_SCORE,
                ["invalid_or_missing_path_argument"],
            )

        target_path = self._resolve_workspace_path(path_value)
        if not target_path.is_relative_to(self._workspace_root):
            return self._result(HARD_BLOCK_SCORE, ["path_outside_workspace"])

        if self._is_sensitive_path(target_path):
            return self._result(HARD_BLOCK_SCORE, ["sensitive_path"])

        if tool_call.tool_name == "read_file":
            score = SAFE_READ_FILE_SCORE
            reasons = ["safe_file_read"]
        elif tool_call.tool_name == "list_directory":
            score = SAFE_LIST_DIRECTORY_SCORE
            reasons = ["safe_directory_list"]
        else:
            score = WRITE_FILE_SCORE
            reasons = ["write_file_requires_approval"]

        behavior_score, behavior_reasons = self._record_behavior(tool_call)
        return self._result(score + behavior_score, [*reasons, *behavior_reasons])

    def _score_run_command(self, tool_call: ToolCall) -> RiskResult:
        command_value = tool_call.arguments.get("command")
        if not isinstance(command_value, str):
            return self._result(
                INVALID_ARGUMENT_SCORE,
                ["invalid_or_missing_command_argument"],
            )

        behavior_score, behavior_reasons = self._record_behavior(tool_call)
        command_risk = self._detect_command_risk(command_value)
        if command_risk is not None:
            return self._result(
                HARD_BLOCK_SCORE,
                [command_risk, *behavior_reasons],
            )

        score = RUN_COMMAND_SCORE + behavior_score
        reasons = ["run_command_requires_approval", *behavior_reasons]
        return self._result(score, reasons)

    def _record_behavior(self, tool_call: ToolCall) -> tuple[int, list[str]]:
        counts = self._behavior_tracker.record_and_count(
            tool_call.session_id,
            tool_call.tool_name,
        )
        score = 0
        reasons: list[str] = []

        if counts["read_file"] > READ_FILE_WINDOW_LIMIT:
            score += READ_FILE_BEHAVIOR_SCORE_BUMP
            reasons.append("many_recent_read_file_calls")

        if counts["run_command"] > RUN_COMMAND_WINDOW_LIMIT:
            score += RUN_COMMAND_BEHAVIOR_SCORE_BUMP
            reasons.append("excessive_recent_run_command_calls")

        return score, reasons

    def _resolve_workspace_path(self, path_value: str) -> Path:
        input_path = Path(path_value)
        if input_path.is_absolute():
            return input_path.resolve(strict=False)
        return (self._workspace_root / input_path).resolve(strict=False)

    def _is_sensitive_path(self, target_path: Path) -> bool:
        relative_parts = tuple(
            part.lower() for part in target_path.relative_to(self._workspace_root).parts
        )
        file_name = target_path.name.lower()
        suffix = target_path.suffix.lower()

        if file_name in SENSITIVE_FILE_NAMES:
            return True
        if suffix in SENSITIVE_EXTENSIONS:
            return True
        if any(part in SENSITIVE_FILE_NAMES for part in relative_parts):
            return True
        return any(
            self._contains_component_path(relative_parts, sensitive_path)
            for sensitive_path in SENSITIVE_COMPONENT_PATHS
        )

    @staticmethod
    def _contains_component_path(
        parts: tuple[str, ...],
        sensitive_path: tuple[str, ...],
    ) -> bool:
        if len(sensitive_path) > len(parts):
            return False
        return any(
            parts[index : index + len(sensitive_path)] == sensitive_path
            for index in range(len(parts) - len(sensitive_path) + 1)
        )

    def _detect_command_risk(self, command: str) -> str | None:
        powershell_risk = self._detect_powershell_risk(command)
        if powershell_risk is not None:
            return powershell_risk

        posix_risk = self._detect_posix_risk(command)
        if posix_risk is not None:
            return posix_risk

        return None

    def _detect_posix_risk(self, command: str) -> str | None:
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            return "command_parse_failed"

        if tokens == []:
            return None

        if self._has_download_pipe_to_shell(command, {"curl", "wget"}, {"bash", "sh"}):
            return "download_pipe_to_shell"

        for index, token in enumerate(tokens):
            name = self._command_basename(token)
            following = tokens[index + 1 :]
            if name == "sudo":
                return "sudo_command"
            if name.startswith("mkfs"):
                return "filesystem_format_command"
            if name == "rm" and self._has_recursive_force_flags(following):
                return "dangerous_rm_recursive_force"
            if name == "chmod" and "777" in following:
                return "world_writable_chmod"
            if name == "dd" and any(
                arg.lower().startswith("if=") for arg in following
            ):
                return "raw_disk_copy_command"

        return None

    def _detect_powershell_risk(self, command: str) -> str | None:
        if self._has_download_pipe_to_shell(
            command,
            {"invoke-webrequest", "iwr"},
            {"invoke-expression", "iex"},
        ):
            return "download_pipe_to_powershell_execution"

        try:
            tokens = shlex.split(command, posix=False)
        except ValueError:
            return None

        normalized_tokens = [token.lower() for token in tokens]
        for index, name in enumerate(normalized_tokens):
            following = normalized_tokens[index + 1 :]
            if name in REMOVE_ITEM_ALIASES and self._has_powershell_recurse_force(
                following
            ):
                return "dangerous_remove_item_recursive_force"
            if name == "start-process":
                return "start_process_command"
            if name == "format-volume":
                return "format_volume_command"
            if name == "set-executionpolicy" and "bypass" in following:
                return "execution_policy_bypass"

        return None

    @staticmethod
    def _has_powershell_recurse_force(following: list[str]) -> bool:
        following_set = set(following)
        has_recurse = bool(POWERSHELL_RECURSE_FLAGS & following_set)
        has_force = bool(POWERSHELL_FORCE_FLAGS & following_set)
        return has_recurse and has_force

    @staticmethod
    def _command_basename(token: str) -> str:
        lowered = token.lower()
        for separator in ("/", "\\"):
            if separator in lowered:
                lowered = lowered.rsplit(separator, 1)[-1]
        return lowered

    @staticmethod
    def _has_recursive_force_flags(tokens: list[str]) -> bool:
        has_recursive = False
        has_force = False

        for token in tokens:
            lowered = token.lower()
            if lowered in {"--recursive", "-r"}:
                has_recursive = True
            if lowered in {"--force", "-f"}:
                has_force = True
            if lowered.startswith("-") and not lowered.startswith("--"):
                flag_chars = lowered[1:]
                has_recursive = has_recursive or "r" in flag_chars
                has_force = has_force or "f" in flag_chars

        return has_recursive and has_force

    @staticmethod
    def _has_download_pipe_to_shell(
        command: str,
        download_commands: set[str],
        shell_commands: set[str],
    ) -> bool:
        pipeline_parts = [part.strip() for part in command.split("|")]
        if len(pipeline_parts) < 2:
            return False

        for left, right in zip(pipeline_parts, pipeline_parts[1:], strict=False):
            left_command = RiskScorer._first_token(left)
            right_command = RiskScorer._first_token(right)
            if left_command in download_commands and right_command in shell_commands:
                return True

        return False

    @staticmethod
    def _first_token(command_part: str) -> str | None:
        try:
            tokens = shlex.split(command_part, posix=False)
        except ValueError:
            return None
        if tokens == []:
            return None
        return tokens[0].lower()

    @staticmethod
    def _result(score: int, reasons: list[str]) -> RiskResult:
        clamped_score = max(0, min(100, score))
        return RiskResult(
            risk_score=clamped_score,
            decision=RiskScorer._decision_for_score(clamped_score),
            reasons=reasons,
        )

    @staticmethod
    def _decision_for_score(score: int) -> RiskDecision:
        if score <= ALLOW_MAX_SCORE:
            return "allow"
        if score <= REQUIRE_APPROVAL_MAX_SCORE:
            return "require_approval"
        return "block"
