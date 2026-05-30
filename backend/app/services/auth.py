from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.core.config import Settings


class AuthError(ValueError):
    pass


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    display_name: str
    role: str


PASSWORD_HASH_ITERATIONS = 210_000
_revoked_tokens: dict[str, int] = {}


def authenticate_credentials(username: str, password: str, settings: Settings) -> AuthUser | None:
    username_match = hmac.compare_digest(username.strip(), settings.auth_username)
    password_match = hmac.compare_digest(password, settings.auth_password)
    if not username_match or not password_match:
        return None
    return configured_user(settings)


def configured_user(settings: Settings) -> AuthUser:
    return AuthUser(
        id="configured-admin",
        username=settings.auth_username,
        display_name=settings.auth_display_name,
        role=settings.auth_role,
    )


def normalize_username(username: str) -> str:
    return username.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return "$".join(
        [
            "pbkdf2_sha256",
            str(PASSWORD_HASH_ITERATIONS),
            _base64_url_encode(salt),
            _base64_url_encode(digest),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, expected_raw = password_hash.split("$", 3)
        iterations = int(iterations_raw)
        salt = _base64_url_decode(salt_raw)
        expected = _base64_url_decode(expected_raw)
    except (ValueError, TypeError):
        return False
    if algorithm != "pbkdf2_sha256" or iterations < 1:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def issue_access_token(user: AuthUser, settings: Settings) -> tuple[str, int]:
    issued_at = int(time.time())
    expires_at = issued_at + settings.auth_token_ttl_minutes * 60
    payload = {
        "sub": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "iat": issued_at,
        "exp": expires_at,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_part = _base64_url_encode(payload_bytes)
    signature = _sign(payload_part, settings)
    return f"{payload_part}.{signature}", expires_at


def authenticate_request(request: Request, settings: Settings) -> AuthUser:
    token = request_token(request)
    if not token:
        raise AuthError("Missing authentication token")
    return verify_access_token(token, settings)


def request_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    query_token = request.query_params.get("token")
    return query_token.strip() if query_token else None


def revoke_access_token(token: str, settings: Settings) -> AuthUser:
    user, expires_at = _verified_token_payload(token, settings)
    _collect_expired_revocations()
    _revoked_tokens[_token_digest(token)] = expires_at
    return user


def verify_access_token(token: str, settings: Settings) -> AuthUser:
    user, _ = _verified_token_payload(token, settings)
    return user


def _verified_token_payload(token: str, settings: Settings) -> tuple[AuthUser, int]:
    try:
        payload_part, signature = token.split(".", 1)
    except ValueError as exc:
        raise AuthError("Invalid authentication token") from exc

    expected_signature = _sign(payload_part, settings)
    if not hmac.compare_digest(signature, expected_signature):
        raise AuthError("Invalid authentication token")

    try:
        payload = json.loads(_base64_url_decode(payload_part))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthError("Invalid authentication token") from exc

    expires_at = _int_payload_value(payload, "exp")
    if expires_at <= int(time.time()):
        raise AuthError("Authentication token expired")
    if _is_revoked(token):
        raise AuthError("Authentication token revoked")

    user_id = str(payload.get("sub") or "")
    username = str(payload.get("username") or "")
    if not user_id or not username:
        raise AuthError("Invalid authentication token")

    return (
        AuthUser(
            id=user_id,
            username=username,
            display_name=str(payload.get("display_name") or settings.auth_display_name),
            role=str(payload.get("role") or settings.auth_role),
        ),
        expires_at,
    )


def _is_revoked(token: str) -> bool:
    _collect_expired_revocations()
    return _token_digest(token) in _revoked_tokens


def _collect_expired_revocations() -> None:
    now = int(time.time())
    expired = [digest for digest, expires_at in _revoked_tokens.items() if expires_at <= now]
    for digest in expired:
        _revoked_tokens.pop(digest, None)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sign(payload_part: str, settings: Settings) -> str:
    digest = hmac.new(
        settings.auth_session_secret.encode("utf-8"),
        payload_part.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _base64_url_encode(digest)


def _base64_url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64_url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _int_payload_value(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise AuthError("Invalid authentication token")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AuthError("Invalid authentication token") from exc
