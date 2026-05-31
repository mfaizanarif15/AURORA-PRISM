import pytest

from app.core.config import Settings
from app.services.auth import (
    AuthError,
    authenticate_credentials,
    hash_password,
    issue_access_token,
    revoke_access_token,
    verify_access_token,
    verify_password,
)


def test_authenticates_configured_user_and_verifies_token() -> None:
    settings = Settings(
        auth_username="operator",
        auth_password="correct-password",
        auth_display_name="Operator One",
        auth_session_secret="test-secret",
    )

    user = authenticate_credentials("operator", "correct-password", settings)
    assert user is not None
    assert user.display_name == "Operator One"

    token, expires_at = issue_access_token(user, settings)
    verified = verify_access_token(token, settings)

    assert expires_at > 0
    assert verified.id == "configured-admin"
    assert verified.username == "operator"


def test_rejects_bad_credentials_and_tampered_token() -> None:
    settings = Settings(
        auth_username="operator",
        auth_password="correct-password",
        auth_session_secret="test-secret",
    )

    assert authenticate_credentials("operator", "wrong-password", settings) is None

    user = authenticate_credentials("operator", "correct-password", settings)
    assert user is not None
    token, _ = issue_access_token(user, settings)

    with pytest.raises(AuthError):
        verify_access_token(f"{token}tampered", settings)


def test_revoked_token_is_rejected() -> None:
    settings = Settings(
        auth_username="operator",
        auth_password="correct-password",
        auth_session_secret="revocation-secret",
    )
    user = authenticate_credentials("operator", "correct-password", settings)
    assert user is not None
    token, _ = issue_access_token(user, settings)

    revoked_user = revoke_access_token(token, settings)

    assert revoked_user.username == "operator"
    with pytest.raises(AuthError):
        verify_access_token(token, settings)


def test_hashes_and_verifies_password() -> None:
    password_hash = hash_password("correct-password")

    assert password_hash.startswith("pbkdf2_sha256$")
    assert verify_password("correct-password", password_hash)
    assert not verify_password("wrong-password", password_hash)
