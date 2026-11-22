"""Authentication and token lifecycle business logic."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, ForbiddenError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse


def register_user(db: Session, payload: RegisterRequest) -> User:
    """Register a new user account with a unique email and hashed password."""
    normalized_email = payload.email.strip().lower()
    existing = db.scalar(select(User).where(User.email == normalized_email))
    if existing is not None:
        raise ConflictError(
            "A user with this email address is already registered.",
            code="email_already_registered",
            details={"email": normalized_email},
        )

    user = User(
        email=normalized_email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        affiliation=payload.affiliation.strip() if payload.affiliation else None,
        expertise_keywords=[],
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "A user with this email address is already registered.",
            code="email_already_registered",
            details={"email": normalized_email},
        ) from exc

    db.refresh(user)
    return user


def authenticate_user(db: Session, payload: LoginRequest, settings: Settings) -> TokenResponse:
    """Verify credentials for an active user and issue JWT access and refresh tokens."""
    normalized_email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise UnauthorizedError(
            "Invalid email or password.",
            code="invalid_credentials",
        )

    if not user.is_active:
        raise ForbiddenError(
            "This user account has been deactivated.",
            code="account_deactivated",
        )

    access_token, expires_in = create_access_token(user.id, settings)
    refresh_token = create_refresh_token(user.id, settings)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


def refresh_tokens(db: Session, payload: RefreshRequest, settings: Settings) -> TokenResponse:
    """Validate a refresh token for an active user and issue a fresh token pair."""
    user_id = decode_token(
        payload.refresh_token,
        expected_type="refresh",
        settings=settings,
    )
    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError(
            "Invalid authentication token.",
            code="invalid_token",
        )

    if not user.is_active:
        raise ForbiddenError(
            "This user account has been deactivated.",
            code="account_deactivated",
        )

    access_token, expires_in = create_access_token(user.id, settings)
    refresh_token = create_refresh_token(user.id, settings)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )
