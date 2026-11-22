"""User profile management and System Admin user administration business logic."""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, NotFoundError
from app.models.user import User
from app.schemas.user import UserProfileUpdateRequest


def update_own_profile(
    db: Session,
    user: User,
    payload: UserProfileUpdateRequest,
) -> User:
    """Apply partial profile updates for the currently authenticated user."""
    provided = payload.model_fields_set

    if "full_name" in provided:
        if payload.full_name is None or not payload.full_name.strip():
            raise BadRequestError(
                "full_name cannot be empty or null.",
                code="invalid_full_name",
            )
        user.full_name = payload.full_name.strip()

    if "affiliation" in provided:
        user.affiliation = payload.affiliation.strip() if payload.affiliation else None

    if "bio" in provided:
        user.bio = payload.bio.strip() if payload.bio else None

    if "orcid" in provided:
        user.orcid = payload.orcid.strip() if payload.orcid else None

    if "expertise_keywords" in provided:
        if payload.expertise_keywords is None:
            raise BadRequestError(
                "expertise_keywords cannot be null.",
                code="invalid_expertise_keywords",
            )
        user.expertise_keywords = payload.expertise_keywords

    if "max_active_reviews" in provided:
        if payload.max_active_reviews is None:
            raise BadRequestError(
                "max_active_reviews cannot be null.",
                code="invalid_max_active_reviews",
            )
        user.max_active_reviews = payload.max_active_reviews

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_users_paginated(
    db: Session,
    *,
    page: int,
    page_size: int,
    is_active: bool | None = None,
    search: str | None = None,
) -> tuple[list[User], int]:
    """Return a paginated slice of platform users and total matching count."""
    query = select(User)
    if is_active is not None:
        query = query.where(User.is_active == is_active)

    if search and search.strip():
        pattern = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(User.email).like(pattern),
                func.lower(User.full_name).like(pattern),
                func.lower(func.coalesce(User.affiliation, "")).like(pattern),
            )
        )

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(
            query.order_by(User.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, int(total)


def get_user_by_id(db: Session, user_id: int) -> User:
    """Retrieve a single user by primary key or raise 404."""
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError(
            f"User {user_id} was not found.",
            code="user_not_found",
            details={"user_id": user_id},
        )
    return user


def set_user_active_status(
    db: Session,
    *,
    target_user_id: int,
    is_active: bool,
    acting_admin: User,
) -> User:
    """Activate or deactivate a target user account on behalf of a System Admin."""
    user = get_user_by_id(db, target_user_id)
    if user.id == acting_admin.id and not is_active:
        raise BadRequestError(
            "System administrators cannot deactivate their own account.",
            code="cannot_deactivate_self",
        )

    user.is_active = is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
