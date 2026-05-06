from app.privacy import MaskingResult, PrivacyMasker, SecretKind


def test_masks_email_addresses() -> None:
    result = PrivacyMasker().mask_text("Contact admin@example.com for access.")

    assert result.masked_text == "Contact [EMAIL_001] for access."
    assert result.findings[0].kind is SecretKind.EMAIL
    assert result.findings[0].token == "[EMAIL_001]"


def test_masks_openai_api_key() -> None:
    result = PrivacyMasker().mask_text("key=sk-test123")

    assert result.masked_text == "key=[API_KEY_001]"
    assert result.findings[0].kind is SecretKind.API_KEY
    assert result.findings[0].token == "[API_KEY_001]"


def test_masks_github_token_variants() -> None:
    text = "one ghp_abcdefgh12345678 two github_pat_abcdefgh12345678"

    result = PrivacyMasker().mask_text(text)

    assert result.masked_text == "one [GITHUB_TOKEN_001] two [GITHUB_TOKEN_002]"
    assert [finding.kind for finding in result.findings] == [
        SecretKind.GITHUB_TOKEN,
        SecretKind.GITHUB_TOKEN,
    ]


def test_masks_jwt_like_token() -> None:
    jwt = "aaaaaaaaaa.bbbbbbbbbb.cccccccccc"

    result = PrivacyMasker().mask_text(f"token {jwt}")

    assert result.masked_text == "token [JWT_001]"
    assert result.findings[0].kind is SecretKind.JWT


def test_masks_database_urls() -> None:
    text = (
        "postgres://user:pass@localhost:5432/app "
        "postgresql://user:pass@localhost/app "
        "mysql://user:pass@localhost/app"
    )

    result = PrivacyMasker().mask_text(text)

    assert result.masked_text == (
        "[DATABASE_URL_001] [DATABASE_URL_002] [DATABASE_URL_003]"
    )
    assert [finding.kind for finding in result.findings] == [
        SecretKind.DATABASE_URL,
        SecretKind.DATABASE_URL,
        SecretKind.DATABASE_URL,
    ]


def test_masks_private_key_block() -> None:
    private_key = (
        "-----BEGIN PRIVATE KEY-----\n"
        "abc123\n"
        "-----END PRIVATE KEY-----"
    )

    result = PrivacyMasker().mask_text(f"before\n{private_key}\nafter")

    assert result.masked_text == "before\n[PRIVATE_KEY_001]\nafter"
    assert result.findings[0].kind is SecretKind.PRIVATE_KEY


def test_env_preserves_key_and_masks_openai_value_without_quotes() -> None:
    result = PrivacyMasker().mask_text('API_KEY="sk-test123"')

    assert result.masked_text == "API_KEY=[API_KEY_001]"
    assert result.findings[0].kind is SecretKind.API_KEY


def test_env_preserves_prefix_and_masks_database_url() -> None:
    result = PrivacyMasker().mask_text(
        "export DATABASE_URL = postgres://user:pass@localhost:5432/app"
    )

    assert result.masked_text == "export DATABASE_URL = [DATABASE_URL_001]"
    assert result.findings[0].kind is SecretKind.DATABASE_URL


def test_env_masks_generic_secret_value() -> None:
    result = PrivacyMasker().mask_text("SECRET_KEY=plain-secret")

    assert result.masked_text == "SECRET_KEY=[ENV_SECRET_001]"
    assert result.findings[0].kind is SecretKind.ENV_SECRET


def test_empty_env_values_are_not_masked() -> None:
    result = PrivacyMasker().mask_text("SECRET_KEY=")

    assert result.masked_text == "SECRET_KEY="
    assert result.findings == ()


def test_same_secret_uses_same_token_within_one_input() -> None:
    result = PrivacyMasker().mask_text("a@b.com and a@b.com")

    assert result.masked_text == "[EMAIL_001] and [EMAIL_001]"
    assert len(result.findings) == 1


def test_same_secret_uses_same_token_across_calls_in_one_session() -> None:
    masker = PrivacyMasker()

    first = masker.mask_text("admin@example.com")
    second = masker.mask_text("again admin@example.com")

    assert first.masked_text == "[EMAIL_001]"
    assert second.masked_text == "again [EMAIL_001]"
    assert second.findings[0].token == "[EMAIL_001]"


def test_different_secrets_get_different_tokens() -> None:
    result = PrivacyMasker().mask_text("one@example.com two@example.com")

    assert result.masked_text == "[EMAIL_001] [EMAIL_002]"
    assert [finding.token for finding in result.findings] == [
        "[EMAIL_001]",
        "[EMAIL_002]",
    ]


def test_non_sensitive_text_is_unchanged() -> None:
    text = "hello world with no secrets"

    result = PrivacyMasker().mask_text(text)

    assert result.masked_text == text
    assert result.findings == ()


def test_public_result_does_not_expose_raw_secret_values() -> None:
    secret = "admin@example.com"

    result = PrivacyMasker().mask_text(secret)
    serialized = result.model_dump_json()

    assert isinstance(result, MaskingResult)
    assert secret not in result.masked_text
    assert secret not in serialized
