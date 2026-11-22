"""Business logic for journals, per-journal RBAC memberships, and workflow configs."""

from collections.abc import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.models.journal import (
    Journal,
    JournalMembership,
    JournalRole,
    JournalWorkflowConfig,
)
from app.models.user import User
from app.schemas.journal import (
    JournalCreateRequest,
    JournalMemberAssignRequest,
    JournalUpdateRequest,
    JournalWorkflowConfigUpdateRequest,
)


def list_active_journals_paginated(
    db: Session,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
) -> tuple[list[Journal], int]:
    """Return a paginated directory of active journals with their workflow policies."""
    query = select(Journal).where(Journal.is_active.is_(True))
    if search and search.strip():
        pattern = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(Journal.title).like(pattern),
                func.lower(Journal.slug).like(pattern),
                func.lower(func.coalesce(Journal.description, "")).like(pattern),
            )
        )

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(
            query.options(selectinload(Journal.workflow_config))
            .order_by(Journal.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, int(total)


def get_journal_or_404(db: Session, journal_id: int) -> Journal:
    """Fetch a journal with its workflow config or raise 404."""
    journal = db.scalar(
        select(Journal)
        .options(selectinload(Journal.workflow_config))
        .where(Journal.id == journal_id)
    )
    if journal is None:
        raise NotFoundError(
            f"Journal {journal_id} was not found.",
            code="journal_not_found",
            details={"journal_id": journal_id},
        )
    return journal


def create_journal(db: Session, payload: JournalCreateRequest) -> Journal:
    """Create a new journal and automatically initialize its default workflow config."""
    existing = db.scalar(select(Journal).where(Journal.slug == payload.slug))
    if existing is not None:
        raise ConflictError(
            f"A journal with slug '{payload.slug}' already exists.",
            code="journal_slug_already_exists",
            details={"slug": payload.slug},
        )

    journal = Journal(
        title=payload.title.strip(),
        slug=payload.slug,
        issn=payload.issn.strip() if payload.issn else None,
        description=payload.description.strip() if payload.description else None,
        scope_keywords=payload.scope_keywords,
        publisher_name=payload.publisher_name.strip() if payload.publisher_name else None,
        doi_prefix=payload.doi_prefix.strip(),
        apc_enabled=payload.apc_enabled,
        apc_amount_cents=payload.apc_amount_cents,
        apc_currency=payload.apc_currency,
    )
    journal.workflow_config = JournalWorkflowConfig()

    db.add(journal)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"A journal with slug '{payload.slug}' already exists.",
            code="journal_slug_already_exists",
            details={"slug": payload.slug},
        ) from exc

    return get_journal_or_404(db, journal.id)


def update_journal(
    db: Session,
    journal_id: int,
    payload: JournalUpdateRequest,
) -> Journal:
    """Partially update journal metadata, APC settings, DOI prefix, or active flag."""
    journal = get_journal_or_404(db, journal_id)
    provided = payload.model_fields_set

    if "title" in provided:
        if payload.title is None or not payload.title.strip():
            raise BadRequestError("title cannot be empty or null.", code="invalid_title")
        journal.title = payload.title.strip()

    if "slug" in provided:
        if payload.slug is None:
            raise BadRequestError("slug cannot be null.", code="invalid_slug")
        if payload.slug != journal.slug:
            existing = db.scalar(select(Journal).where(Journal.slug == payload.slug))
            if existing is not None:
                raise ConflictError(
                    f"A journal with slug '{payload.slug}' already exists.",
                    code="journal_slug_already_exists",
                    details={"slug": payload.slug},
                )
            journal.slug = payload.slug

    if "issn" in provided:
        journal.issn = payload.issn.strip() if payload.issn else None

    if "description" in provided:
        journal.description = payload.description.strip() if payload.description else None

    if "scope_keywords" in provided:
        if payload.scope_keywords is None:
            raise BadRequestError(
                "scope_keywords cannot be null.",
                code="invalid_scope_keywords",
            )
        journal.scope_keywords = payload.scope_keywords

    if "publisher_name" in provided:
        journal.publisher_name = (
            payload.publisher_name.strip() if payload.publisher_name else None
        )

    if "doi_prefix" in provided:
        if payload.doi_prefix is None or not payload.doi_prefix.strip():
            raise BadRequestError("doi_prefix cannot be empty or null.", code="invalid_doi_prefix")
        journal.doi_prefix = payload.doi_prefix.strip()

    if "apc_enabled" in provided:
        if payload.apc_enabled is None:
            raise BadRequestError("apc_enabled cannot be null.", code="invalid_apc_enabled")
        journal.apc_enabled = payload.apc_enabled

    if "apc_amount_cents" in provided:
        if payload.apc_amount_cents is None:
            raise BadRequestError(
                "apc_amount_cents cannot be null.",
                code="invalid_apc_amount_cents",
            )
        journal.apc_amount_cents = payload.apc_amount_cents

    if "apc_currency" in provided:
        if payload.apc_currency is None:
            raise BadRequestError("apc_currency cannot be null.", code="invalid_apc_currency")
        journal.apc_currency = payload.apc_currency

    if "is_active" in provided:
        if payload.is_active is None:
            raise BadRequestError("is_active cannot be null.", code="invalid_is_active")
        journal.is_active = payload.is_active

    db.add(journal)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "Journal update conflicted with an existing unique constraint.",
            code="journal_conflict",
        ) from exc

    return get_journal_or_404(db, journal.id)


def get_workflow_config(db: Session, journal_id: int) -> JournalWorkflowConfig:
    """Return the workflow configuration for a journal."""
    journal = get_journal_or_404(db, journal_id)
    if journal.workflow_config is None:
        config = JournalWorkflowConfig(journal_id=journal.id)
        db.add(config)
        db.commit()
        db.refresh(config)
        return config
    return journal.workflow_config


def update_workflow_config(
    db: Session,
    journal_id: int,
    payload: JournalWorkflowConfigUpdateRequest,
) -> JournalWorkflowConfig:
    """Partially update a journal's editorial workflow rules and SLA thresholds."""
    config = get_workflow_config(db, journal_id)
    provided = payload.model_fields_set

    non_nullable_fields = (
        "anonymity_mode",
        "min_reviewers",
        "require_desk_review",
        "require_plagiarism_check",
        "desk_review_sla_days",
        "review_sla_days",
        "decision_sla_days",
        "revision_sla_days",
    )
    for field_name in non_nullable_fields:
        if field_name in provided:
            value = getattr(payload, field_name)
            if value is None:
                raise BadRequestError(
                    f"{field_name} cannot be null.",
                    code=f"invalid_{field_name}",
                )
            setattr(config, field_name, value.value if hasattr(value, "value") else value)

    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def has_journal_role(
    db: Session,
    *,
    user: User,
    journal_id: int,
    allowed_roles: Iterable[JournalRole],
) -> bool:
    """Return True if user is a System Admin or holds any allowed role in the journal."""
    if user.is_system_admin:
        return True

    role_values = [role.value for role in allowed_roles]
    if not role_values:
        return False

    membership = db.scalar(
        select(JournalMembership.id).where(
            JournalMembership.journal_id == journal_id,
            JournalMembership.user_id == user.id,
            JournalMembership.role.in_(role_values),
        )
    )
    return membership is not None


def assign_journal_member(
    db: Session,
    *,
    journal_id: int,
    payload: JournalMemberAssignRequest,
    acting_user: User,
) -> JournalMembership:
    """Assign a per-journal role to a user."""
    get_journal_or_404(db, journal_id)

    target_user = db.get(User, payload.user_id)
    if target_user is None:
        raise NotFoundError(
            f"User {payload.user_id} was not found.",
            code="user_not_found",
            details={"user_id": payload.user_id},
        )

    existing = db.scalar(
        select(JournalMembership).where(
            JournalMembership.journal_id == journal_id,
            JournalMembership.user_id == payload.user_id,
            JournalMembership.role == payload.role.value,
        )
    )
    if existing is not None:
        raise ConflictError(
            f"User {payload.user_id} already holds role '{payload.role.value}' in this journal.",
            code="membership_already_exists",
            details={
                "journal_id": journal_id,
                "user_id": payload.user_id,
                "role": payload.role.value,
            },
        )

    membership = JournalMembership(
        journal_id=journal_id,
        user_id=payload.user_id,
        role=payload.role.value,
        assigned_by_id=acting_user.id,
    )
    db.add(membership)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"User {payload.user_id} already holds role '{payload.role.value}' in this journal.",
            code="membership_already_exists",
        ) from exc

    loaded = db.scalar(
        select(JournalMembership)
        .options(selectinload(JournalMembership.user))
        .where(JournalMembership.id == membership.id)
    )
    assert loaded is not None
    return loaded


def list_journal_members_paginated(
    db: Session,
    *,
    journal_id: int,
    page: int,
    page_size: int,
    role: JournalRole | None = None,
) -> tuple[list[JournalMembership], int]:
    """Return a paginated list of role assignments in a journal, optionally filtered by role."""
    get_journal_or_404(db, journal_id)

    query = select(JournalMembership).where(JournalMembership.journal_id == journal_id)
    if role is not None:
        query = query.where(JournalMembership.role == role.value)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(
            query.options(selectinload(JournalMembership.user))
            .order_by(JournalMembership.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, int(total)


def revoke_journal_member(
    db: Session,
    *,
    journal_id: int,
    membership_id: int,
) -> None:
    """Revoke a per-journal role assignment belonging strictly to the target journal."""
    get_journal_or_404(db, journal_id)

    membership = db.scalar(
        select(JournalMembership).where(
            JournalMembership.id == membership_id,
            JournalMembership.journal_id == journal_id,
        )
    )
    if membership is None:
        raise NotFoundError(
            f"Membership {membership_id} was not found in journal {journal_id}.",
            code="membership_not_found",
            details={"journal_id": journal_id, "membership_id": membership_id},
        )

    db.delete(membership)
    db.commit()
