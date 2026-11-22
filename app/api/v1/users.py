"""Current-user profile endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserProfileResponse, UserProfileUpdateRequest
from app.services import user_service

router = APIRouter(prefix="/users", tags=["User Profiles"])


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get the authenticated user's profile",
)
def get_my_profile(current_user: User = Depends(get_current_user)) -> UserProfileResponse:
    """Return profile details for the currently authenticated user."""
    return UserProfileResponse.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserProfileResponse,
    summary="Update the authenticated user's profile",
)
def update_my_profile(
    payload: UserProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    """Partially update profile fields for the currently authenticated user."""
    updated = user_service.update_own_profile(db, current_user, payload)
    return UserProfileResponse.model_validate(updated)
