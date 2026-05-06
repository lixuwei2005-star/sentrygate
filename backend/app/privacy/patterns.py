import re
from dataclasses import dataclass
from enum import Enum


class SecretKind(str, Enum):  # noqa: UP042
    EMAIL = "EMAIL"
    API_KEY = "API_KEY"
    GITHUB_TOKEN = "GITHUB_TOKEN"
    JWT = "JWT"
    DATABASE_URL = "DATABASE_URL"
    PRIVATE_KEY = "PRIVATE_KEY"
    ENV_SECRET = "ENV_SECRET"


@dataclass(frozen=True)
class SensitivePattern:
    kind: SecretKind
    regex: re.Pattern[str]


EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])"
)
OPENAI_API_KEY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{6,}(?![A-Za-z0-9_-])"
)
GITHUB_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:ghp_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,})(?![A-Za-z0-9_])"
)
JWT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:[A-Za-z0-9_-]{10,}\.){2}[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
)
DATABASE_URL_PATTERN = re.compile(
    r"\b(?:postgres(?:ql)?|mysql)://[^\s'\"<>]+",
    re.IGNORECASE,
)
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
)
ENV_ASSIGNMENT_PATTERN = re.compile(
    r"(?m)^(?P<prefix>\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*)"
    r"(?P<raw_value>[^\r\n]*)$"
)
ENV_SECRET_KEY_PATTERN = re.compile(
    r"(?:^|_)(?:API_KEY|DATABASE_URL|SECRET_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY|ACCESS_KEY)(?:_|$)",
    re.IGNORECASE,
)
MASK_TOKEN_PATTERN = re.compile(r"^\[[A-Z_]+_\d{3}\]$")


GENERAL_PATTERNS: tuple[SensitivePattern, ...] = (
    SensitivePattern(SecretKind.PRIVATE_KEY, PRIVATE_KEY_PATTERN),
    SensitivePattern(SecretKind.DATABASE_URL, DATABASE_URL_PATTERN),
    SensitivePattern(SecretKind.API_KEY, OPENAI_API_KEY_PATTERN),
    SensitivePattern(SecretKind.GITHUB_TOKEN, GITHUB_TOKEN_PATTERN),
    SensitivePattern(SecretKind.JWT, JWT_PATTERN),
    SensitivePattern(SecretKind.EMAIL, EMAIL_PATTERN),
)
