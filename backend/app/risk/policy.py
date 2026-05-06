from typing import Final

SUPPORTED_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {"read_file", "write_file", "list_directory", "run_command"}
)

ALLOW_MAX_SCORE: Final[int] = 39
REQUIRE_APPROVAL_MAX_SCORE: Final[int] = 74

SAFE_READ_FILE_SCORE: Final[int] = 10
SAFE_LIST_DIRECTORY_SCORE: Final[int] = 10
WRITE_FILE_SCORE: Final[int] = 50
RUN_COMMAND_SCORE: Final[int] = 50
UNKNOWN_TOOL_SCORE: Final[int] = 80
INVALID_ARGUMENT_SCORE: Final[int] = 80
HARD_BLOCK_SCORE: Final[int] = 100

BEHAVIOR_WINDOW_SECONDS: Final[float] = 60.0
READ_FILE_WINDOW_LIMIT: Final[int] = 20
RUN_COMMAND_WINDOW_LIMIT: Final[int] = 10
READ_FILE_BEHAVIOR_SCORE_BUMP: Final[int] = 40
RUN_COMMAND_BEHAVIOR_SCORE_BUMP: Final[int] = 30

ANONYMOUS_SESSION_ID: Final[str] = "__anonymous__"

SENSITIVE_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {".env", ".env.local", "id_rsa", "id_ed25519", "secrets.json"}
)
SENSITIVE_EXTENSIONS: Final[frozenset[str]] = frozenset({".pem", ".key", ".p12"})
SENSITIVE_COMPONENT_PATHS: Final[tuple[tuple[str, ...], ...]] = (
    (".aws", "credentials"),
)
