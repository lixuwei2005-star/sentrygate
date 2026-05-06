import re

from pydantic import BaseModel

from app.privacy.patterns import (
    DATABASE_URL_PATTERN,
    ENV_ASSIGNMENT_PATTERN,
    ENV_SECRET_KEY_PATTERN,
    GENERAL_PATTERNS,
    GITHUB_TOKEN_PATTERN,
    JWT_PATTERN,
    MASK_TOKEN_PATTERN,
    OPENAI_API_KEY_PATTERN,
    SecretKind,
    SensitivePattern,
)


class MaskingFinding(BaseModel):
    kind: SecretKind
    token: str


class MaskingResult(BaseModel):
    masked_text: str
    findings: tuple[MaskingFinding, ...] = ()


class PrivacyMasker:
    def __init__(self) -> None:
        self._tokens_by_secret: dict[tuple[SecretKind, str], str] = {}
        self._counts_by_kind: dict[SecretKind, int] = {}

    def mask_text(self, text: str) -> MaskingResult:
        findings_by_token: dict[str, MaskingFinding] = {}

        masked_text = self._mask_env_assignments(text, findings_by_token)
        for pattern in GENERAL_PATTERNS:
            masked_text = self._mask_pattern(masked_text, pattern, findings_by_token)

        return MaskingResult(
            masked_text=masked_text,
            findings=tuple(findings_by_token.values()),
        )

    def _mask_env_assignments(
        self,
        text: str,
        findings_by_token: dict[str, MaskingFinding],
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            key = match.group("key")
            if ENV_SECRET_KEY_PATTERN.search(key) is None:
                return match.group(0)

            value = self._env_value(match.group("raw_value"))
            if value == "" or MASK_TOKEN_PATTERN.fullmatch(value) is not None:
                return match.group(0)

            kind = self._classify_env_value(value)
            token = self._token_for(value, kind)
            self._remember_finding(findings_by_token, kind, token)
            return f"{match.group('prefix')}{token}"

        return ENV_ASSIGNMENT_PATTERN.sub(replace, text)

    def _mask_pattern(
        self,
        text: str,
        pattern: SensitivePattern,
        findings_by_token: dict[str, MaskingFinding],
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            raw_secret = match.group(0)
            token = self._token_for(raw_secret, pattern.kind)
            self._remember_finding(findings_by_token, pattern.kind, token)
            return token

        return pattern.regex.sub(replace, text)

    def _token_for(self, raw_secret: str, kind: SecretKind) -> str:
        key = (kind, raw_secret)
        existing_token = self._tokens_by_secret.get(key)
        if existing_token is not None:
            return existing_token

        next_count = self._counts_by_kind.get(kind, 0) + 1
        self._counts_by_kind[kind] = next_count
        token = f"[{kind.value}_{next_count:03d}]"
        self._tokens_by_secret[key] = token
        return token

    @staticmethod
    def _remember_finding(
        findings_by_token: dict[str, MaskingFinding],
        kind: SecretKind,
        token: str,
    ) -> None:
        if token not in findings_by_token:
            findings_by_token[token] = MaskingFinding(kind=kind, token=token)

    @staticmethod
    def _env_value(raw_value: str) -> str:
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1]
        return value

    @staticmethod
    def _classify_env_value(value: str) -> SecretKind:
        if DATABASE_URL_PATTERN.fullmatch(value) is not None:
            return SecretKind.DATABASE_URL
        if OPENAI_API_KEY_PATTERN.fullmatch(value) is not None:
            return SecretKind.API_KEY
        if GITHUB_TOKEN_PATTERN.fullmatch(value) is not None:
            return SecretKind.GITHUB_TOKEN
        if JWT_PATTERN.fullmatch(value) is not None:
            return SecretKind.JWT
        return SecretKind.ENV_SECRET
