"""Shared FastAPI dependencies for authentication and per-journal RBAC."""

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.adapters.storage import LocalFilesystemStorageAdapter, StorageAdapter
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.models.journal import JournalRole
from app.models.user import User
from app.services import journal_service

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Authenticate a Bearer JWT access token and return the active User."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError(
            "Missing or invalid Authorization header.",
            code="unauthorized",
        )

    user_id = decode_token(
        credentials.credentials,
        expected_type="access",
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

    return user


def require_system_admin(current_user: User = Depends(get_current_user)) -> User:
    """Ensure the authenticated user holds System Administrator privileges."""
    if not current_user.is_system_admin:
        raise ForbiddenError(
            "System administrator privileges are required.",
            code="admin_required",
        )
    return current_user


def require_journal_roles(*allowed_roles: JournalRole) -> Callable[..., User]:
    """Dependency factory enforcing per-journal RBAC (System Admins are always permitted)."""

    def _checker(
        journal_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        journal_service.get_journal_or_404(db, journal_id)
        if not journal_service.has_journal_role(
            db,
            user=current_user,
            journal_id=journal_id,
            allowed_roles=allowed_roles,
        ):
            raise ForbiddenError(
                "You do not hold the required role in this journal.",
                code="journal_role_required",
                details={
                    "journal_id": journal_id,
                    "required_roles": [role.value for role in allowed_roles],
                },
            )
        return current_user

    return _checker


def get_storage_adapter(
    settings: Settings = Depends(get_settings),
) -> StorageAdapter:
    """Return the configured file storage adapter (local filesystem by default)."""
    return LocalFilesystemStorageAdapter(settings.storage_dir)
