"""Password hashing (Argon2) and JWT token creation/verification utilities."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings
from app.core.errors import UnauthorizedError

_password_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2 hash."""
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def create_access_token(user_id: int, settings: Settings) -> tuple[str, int]:
    """Create a signed JWT access token and return (token, expires_in_seconds)."""
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": str(uuid4()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def create_refresh_token(user_id: int, settings: Settings) -> str:
    """Create a signed JWT refresh token."""
    expires_delta = timedelta(days=settings.refresh_token_expire_days)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, *, expected_type: str, settings: Settings) -> int:
    """Decode and validate a JWT token, returning the authenticated user_id."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "type", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError(
            "Token has expired.",
            code="token_expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError(
            "Invalid authentication token.",
            code="invalid_token",
        ) from exc

    if payload.get("type") != expected_type:
        raise UnauthorizedError(
            f"Expected a {expected_type} token.",
            code="invalid_token_type",
        )

    try:
        return int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise UnauthorizedError(
            "Invalid token subject.",
            code="invalid_token",
        ) from exc
