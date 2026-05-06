import json
import os
from typing import Protocol, Self

from pydantic import BaseModel, Field

from app.risk.models import RiskDecision, RiskResult, ToolCall
from app.risk.policy import ALLOW_MAX_SCORE, REQUIRE_APPROVAL_MAX_SCORE

LMSTUDIO_REVIEW_ENABLED_ENV = "LMSTUDIO_REVIEW_ENABLED"
LMSTUDIO_BASE_URL_ENV = "LMSTUDIO_BASE_URL"
LMSTUDIO_MODEL_ENV = "LMSTUDIO_MODEL"
LMSTUDIO_TIMEOUT_SECONDS_ENV = "LMSTUDIO_TIMEOUT_SECONDS"

DEFAULT_LMSTUDIO_BASE_URL = "http://localhost:1234/v1"
DEFAULT_LMSTUDIO_TIMEOUT_SECONDS = 5.0
SEMANTIC_REVIEW_REASON_PREFIX = "lmstudio_semantic_review"
TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})

SYSTEM_PROMPT = (
    "You are a conservative local security reviewer for SentryGate tool calls. "
    "Deterministic policy has already reviewed this call. You may not weaken "
    "that result. You may only keep the current decision, increase risk, or "
    "escalate require_approval to block. Return valid JSON only."
)


class LMStudioReviewConfig(BaseModel):
    enabled: bool = False
    base_url: str = DEFAULT_LMSTUDIO_BASE_URL
    model: str | None = None
    timeout_seconds: float = Field(default=DEFAULT_LMSTUDIO_TIMEOUT_SECONDS, gt=0)

    @classmethod
    def from_env(cls) -> Self:
        enabled = _env_enabled(os.getenv(LMSTUDIO_REVIEW_ENABLED_ENV))
        base_url = _env_text(
            os.getenv(LMSTUDIO_BASE_URL_ENV),
            default=DEFAULT_LMSTUDIO_BASE_URL,
        )
        model = _env_optional_text(os.getenv(LMSTUDIO_MODEL_ENV))
        timeout_seconds = _env_timeout(os.getenv(LMSTUDIO_TIMEOUT_SECONDS_ENV))
        return cls(
            enabled=enabled,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
        )


class LMStudioReviewInput(BaseModel):
    tool_name: str
    arguments_summary: str
    original_risk_score: int = Field(ge=0, le=100)
    original_decision: RiskDecision
    original_reasons: list[str]


class LMStudioReviewOutput(BaseModel):
    risk_score: int = Field(ge=0, le=100)
    decision: RiskDecision
    reason: str


class LMStudioReviewClientProtocol(Protocol):
    def review(
        self,
        review_input: LMStudioReviewInput,
    ) -> LMStudioReviewOutput | None:
        ...


class _HTTPResponse(Protocol):
    def raise_for_status(self) -> object:
        ...

    def json(self) -> object:
        ...


class _HTTPClient(Protocol):
    def post(
        self,
        url: str,
        *,
        json: object,
        timeout: float,
    ) -> _HTTPResponse:
        ...


class LMStudioReviewClient:
    def __init__(
        self,
        config: LMStudioReviewConfig | None = None,
        http_client: _HTTPClient | None = None,
    ) -> None:
        self.config = config or LMStudioReviewConfig.from_env()
        self._http_client = http_client

    def review(
        self,
        review_input: LMStudioReviewInput,
    ) -> LMStudioReviewOutput | None:
        if not self.config.enabled:
            return None

        payload = self._payload(review_input)
        try:
            response = self._post(payload)
            response.raise_for_status()
            return self._parse_response(response.json())
        except Exception:
            return None

    def _post(self, payload: dict[str, object]) -> _HTTPResponse:
        if self._http_client is not None:
            return self._http_client.post(
                self._chat_completions_url(),
                json=payload,
                timeout=self.config.timeout_seconds,
            )

        import httpx

        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            return client.post(
                self._chat_completions_url(),
                json=payload,
                timeout=self.config.timeout_seconds,
            )

    def _chat_completions_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/chat/completions"

    def _payload(self, review_input: LMStudioReviewInput) -> dict[str, object]:
        user_prompt = _user_prompt(review_input)
        payload: dict[str, object] = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        if self.config.model is not None:
            payload["model"] = self.config.model
        return payload

    @staticmethod
    def _parse_response(response_data: object) -> LMStudioReviewOutput | None:
        if not isinstance(response_data, dict):
            return None

        choices = response_data.get("choices")
        if not isinstance(choices, list) or choices == []:
            return None

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return None

        message = first_choice.get("message")
        if not isinstance(message, dict):
            return None

        content = message.get("content")
        if not isinstance(content, str):
            return None

        review_data = json.loads(content)
        if not isinstance(review_data, dict):
            return None

        return LMStudioReviewOutput.model_validate(review_data)


class LMStudioRiskReviewer:
    def __init__(
        self,
        config: LMStudioReviewConfig | None = None,
        client: LMStudioReviewClientProtocol | None = None,
    ) -> None:
        self.config = config or LMStudioReviewConfig.from_env()
        self.client = client or LMStudioReviewClient(config=self.config)

    @classmethod
    def from_env(cls) -> Self:
        return cls(config=LMStudioReviewConfig.from_env())

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def review_risk(
        self,
        tool_call: ToolCall,
        original_result: RiskResult,
        arguments_summary: str,
    ) -> RiskResult:
        if not self.config.enabled:
            return original_result
        if not is_review_eligible(original_result, arguments_summary):
            return original_result

        review_input = LMStudioReviewInput(
            tool_name=tool_call.tool_name,
            arguments_summary=arguments_summary,
            original_risk_score=original_result.risk_score,
            original_decision=original_result.decision,
            original_reasons=list(original_result.reasons),
        )
        review_output = self.client.review(review_input)
        return merge_review(original_result, review_output)


def is_review_eligible(
    original_result: RiskResult,
    arguments_summary: str,
) -> bool:
    return (
        original_result.decision == "require_approval"
        and ALLOW_MAX_SCORE < original_result.risk_score <= REQUIRE_APPROVAL_MAX_SCORE
        and arguments_summary.strip() != ""
    )


def merge_review(
    original_result: RiskResult,
    review_output: LMStudioReviewOutput | None,
) -> RiskResult:
    if review_output is None:
        return original_result
    if original_result.decision in {"allow", "block"}:
        return original_result

    final_score = max(original_result.risk_score, review_output.risk_score)
    final_decision: RiskDecision = original_result.decision
    if review_output.decision == "block" or final_score > REQUIRE_APPROVAL_MAX_SCORE:
        final_decision = "block"

    reason = review_output.reason.strip() or "semantic review completed"
    return RiskResult(
        risk_score=final_score,
        decision=final_decision,
        reasons=[
            *original_result.reasons,
            f"{SEMANTIC_REVIEW_REASON_PREFIX}: {reason}",
        ],
    )


def _user_prompt(review_input: LMStudioReviewInput) -> str:
    input_json = json.dumps(review_input.model_dump(), ensure_ascii=True, indent=2)
    return (
        "Review this tool call summary for semantic risk.\n\n"
        f"Input:\n{input_json}\n\n"
        "Return exactly this JSON object:\n"
        "{\n"
        '  "risk_score": 65,\n'
        '  "decision": "require_approval",\n'
        '  "reason": "short reason"\n'
        "}\n\n"
        "The risk_score must be 0-100. The decision must be one of allow, "
        "require_approval, or block. Do not include markdown. Even though "
        "allow is a valid schema value, the merge layer will ignore any model "
        "attempt to downgrade require_approval to allow."
    )


def _env_enabled(raw_value: str | None) -> bool:
    if raw_value is None:
        return False
    return raw_value.strip().lower() in TRUE_ENV_VALUES


def _env_text(raw_value: str | None, *, default: str) -> str:
    if raw_value is None or raw_value.strip() == "":
        return default
    return raw_value.strip()


def _env_optional_text(raw_value: str | None) -> str | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    return raw_value.strip()


def _env_timeout(raw_value: str | None) -> float:
    if raw_value is None or raw_value.strip() == "":
        return DEFAULT_LMSTUDIO_TIMEOUT_SECONDS

    try:
        timeout_seconds = float(raw_value)
    except ValueError:
        return DEFAULT_LMSTUDIO_TIMEOUT_SECONDS

    if timeout_seconds <= 0:
        return DEFAULT_LMSTUDIO_TIMEOUT_SECONDS
    return timeout_seconds
