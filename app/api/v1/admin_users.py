"""System Administrator user management endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_system_admin
from app.core.database import get_db
from app.core.pagination import PaginatedResponse
from app.models.user import User
from app.schemas.user import AdminUserStatusUpdateRequest, UserProfileResponse
from app.services import user_service

router = APIRouter(prefix="/admin/users", tags=["Admin: Users"])


@router.get(
    "",
    response_model=PaginatedResponse[UserProfileResponse],
    summary="List all users (paginated)",
)
def list_users(
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
    is_active: bool | None = Query(default=None, description="Optional filter by active status."),
    search: str | None = Query(
        default=None,
        description="Optional case-insensitive filter by email, full name, or affiliation.",
    ),
    _admin: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> PaginatedResponse[UserProfileResponse]:
    """Return a paginated directory of platform users for System Administrators."""
    items, total = user_service.list_users_paginated(
        db,
        page=page,
        page_size=page_size,
        is_active=is_active,
        search=search,
    )
    return PaginatedResponse[UserProfileResponse](
        page=page,
        page_size=page_size,
        total=total,
        items=[UserProfileResponse.model_validate(u) for u in items],
    )


@router.get(
    "/{user_id}",
    response_model=UserProfileResponse,
    summary="Inspect a user account",
)
def get_user(
    user_id: int,
    _admin: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    """Retrieve full profile details for a specific user."""
    user = user_service.get_user_by_id(db, user_id)
    return UserProfileResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserProfileResponse,
    summary="Activate or deactivate a user account",
)
def update_user_status(
    user_id: int,
    payload: AdminUserStatusUpdateRequest,
    admin: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    """Set the active status of a target user account."""
    user = user_service.set_user_active_status(
        db,
        target_user_id=user_id,
        is_active=payload.is_active,
        acting_admin=admin,
    )
    return UserProfileResponse.model_validate(user)
