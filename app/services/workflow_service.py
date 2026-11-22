"""Centralized editorial workflow state machine, audit history, editor assignment, and desk review."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models.journal import JournalMembership, JournalRole, JournalWorkflowConfig
from app.models.manuscript import (
    Manuscript,
    ManuscriptStatus,
    ManuscriptStatusHistory,
)
from app.models.user import User
from app.schemas.manuscript import ManuscriptStatusHistoryResponse
from app.services import journal_service, manuscript_service

_TERMINAL_STATUSES: frozenset[ManuscriptStatus] = frozenset(
    {
        ManuscriptStatus.REJECTED,
        ManuscriptStatus.WITHDRAWN,
        ManuscriptStatus.PUBLISHED,
    }
)

_BASE_TRANSITIONS: dict[ManuscriptStatus, frozenset[ManuscriptStatus]] = {
    ManuscriptStatus.DRAFT: frozenset({ManuscriptStatus.SUBMITTED, ManuscriptStatus.WITHDRAWN}),
    ManuscriptStatus.SUBMITTED: frozenset(
        {ManuscriptStatus.DESK_REVIEW, ManuscriptStatus.WITHDRAWN}
    ),
    ManuscriptStatus.DESK_REVIEW: frozenset(
        {ManuscriptStatus.UNDER_REVIEW, ManuscriptStatus.REJECTED, ManuscriptStatus.WITHDRAWN}
    ),
    ManuscriptStatus.UNDER_REVIEW: frozenset(
        {
            ManuscriptStatus.REVISION_REQUESTED,
            ManuscriptStatus.ACCEPTED,
            ManuscriptStatus.REJECTED,
            ManuscriptStatus.WITHDRAWN,
        }
    ),
    ManuscriptStatus.REVISION_REQUESTED: frozenset(
        {ManuscriptStatus.UNDER_REVIEW, ManuscriptStatus.WITHDRAWN}
    ),
    ManuscriptStatus.ACCEPTED: frozenset(
        {ManuscriptStatus.PRODUCTION, ManuscriptStatus.WITHDRAWN}
    ),
    ManuscriptStatus.PRODUCTION: frozenset({ManuscriptStatus.PUBLISHED}),
    ManuscriptStatus.REJECTED: frozenset(),
    ManuscriptStatus.WITHDRAWN: frozenset(),
    ManuscriptStatus.PUBLISHED: frozenset(),
}


def get_allowed_transitions(
    from_status: ManuscriptStatus,
    *,
    require_desk_review: bool,
) -> frozenset[ManuscriptStatus]:
    """Return all valid target states for a manuscript given its journal workflow config."""
    allowed = _BASE_TRANSITIONS[from_status]
    if from_status == ManuscriptStatus.SUBMITTED and not require_desk_review:
        return allowed | frozenset({ManuscriptStatus.UNDER_REVIEW})
    return allowed


def transition_manuscript_status(
    db: Session,
    *,
    manuscript: Manuscript,
    to_status: ManuscriptStatus,
    actor: User,
    note: str | None = None,
    workflow_config: JournalWorkflowConfig | None = None,
) -> ManuscriptStatusHistory:
    """Validate and apply a status transition, appending an immutable audit history entry."""
    config = workflow_config or journal_service.get_workflow_config(db, manuscript.journal_id)
    current_status = ManuscriptStatus(manuscript.status)
    allowed = get_allowed_transitions(
        current_status,
        require_desk_review=config.require_desk_review,
    )

    if to_status not in allowed:
        if (
            current_status == ManuscriptStatus.SUBMITTED
            and to_status == ManuscriptStatus.UNDER_REVIEW
            and config.require_desk_review
        ):
            raise ConflictError(
                "Journal policy requires desk review before advancing a submitted manuscript to peer review.",
                code="invalid_status_transition",
                details={
                    "manuscript_id": manuscript.id,
                    "from_status": current_status.value,
                    "to_status": to_status.value,
                    "allowed_transitions": sorted(s.value for s in allowed),
                },
            )
        raise ConflictError(
            f"Cannot transition manuscript from '{current_status.value}' to '{to_status.value}'.",
            code="invalid_status_transition",
            details={
                "manuscript_id": manuscript.id,
                "from_status": current_status.value,
                "to_status": to_status.value,
                "allowed_transitions": sorted(s.value for s in allowed),
            },
        )

    now = datetime.now(UTC)
    manuscript.status = to_status.value
    manuscript.stage_entered_at = now

    if to_status == ManuscriptStatus.SUBMITTED and manuscript.submitted_at is None:
        manuscript.submitted_at = now
    elif to_status == ManuscriptStatus.UNDER_REVIEW and manuscript.current_review_round == 0:
        manuscript.current_review_round = 1
    elif to_status in {ManuscriptStatus.ACCEPTED, ManuscriptStatus.REJECTED}:
        manuscript.decided_at = now
    elif to_status == ManuscriptStatus.PUBLISHED:
        manuscript.published_at = now

    cleaned_note = note.strip() if note and note.strip() else None
    history_entry = ManuscriptStatusHistory(
        manuscript_id=manuscript.id,
        from_status=current_status.value,
        to_status=to_status.value,
        changed_by_id=actor.id,
        note=cleaned_note,
        created_at=now,
    )
    db.add(manuscript)
    db.add(history_entry)
    return history_entry


def _require_chief_editor(db: Session, *, manuscript: Manuscript, user: User) -> None:
    if not journal_service.has_journal_role(
        db,
        user=user,
        journal_id=manuscript.journal_id,
        allowed_roles=[JournalRole.CHIEF_EDITOR],
    ):
        raise ForbiddenError(
            "Only a Chief Editor of this journal or a System Admin can perform this action.",
            code="chief_editor_required",
            details={"journal_id": manuscript.journal_id, "manuscript_id": manuscript.id},
        )


def _require_assigned_or_chief_editor(db: Session, *, manuscript: Manuscript, user: User) -> None:
    if user.is_system_admin:
        return
    if journal_service.has_journal_role(
        db,
        user=user,
        journal_id=manuscript.journal_id,
        allowed_roles=[JournalRole.CHIEF_EDITOR],
    ):
        return
    if manuscript.assigned_editor_id == user.id and journal_service.has_journal_role(
        db,
        user=user,
        journal_id=manuscript.journal_id,
        allowed_roles=[JournalRole.HANDLING_EDITOR, JournalRole.CHIEF_EDITOR],
    ):
        return
    raise ForbiddenError(
        "Only the assigned Handling Editor, journal Chief Editor, or System Admin can perform this action.",
        code="editorial_permission_required",
        details={"journal_id": manuscript.journal_id, "manuscript_id": manuscript.id},
    )


def submit_manuscript(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
    note: str | None = None,
) -> Manuscript:
    """Formally submit a draft manuscript once at least one PDF version has been uploaded."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    if manuscript.submitter_id != current_user.id:
        raise ForbiddenError(
            "Only the submitting author can submit this manuscript.",
            code="manuscript_submit_forbidden",
            details={"manuscript_id": manuscript_id},
        )

    if manuscript.status != ManuscriptStatus.DRAFT.value:
        # Delegate to state machine so invalid transitions consistently raise 409 Conflict.
        transition_manuscript_status(
            db,
            manuscript=manuscript,
            to_status=ManuscriptStatus.SUBMITTED,
            actor=current_user,
            note=note,
        )

    if manuscript.current_version_number < 1:
        raise BadRequestError(
            "At least one manuscript PDF version (v1) must be uploaded before submitting.",
            code="manuscript_version_required",
            details={"manuscript_id": manuscript_id},
        )

    transition_manuscript_status(
        db,
        manuscript=manuscript,
        to_status=ManuscriptStatus.SUBMITTED,
        actor=current_user,
        note=note,
    )
    db.commit()
    return manuscript_service.get_manuscript_or_404(db, manuscript.id)


def withdraw_manuscript(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
    note: str | None = None,
) -> Manuscript:
    """Withdraw a non-published, non-rejected manuscript by its submitting author."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    if manuscript.submitter_id != current_user.id:
        raise ForbiddenError(
            "Only the submitting author can withdraw this manuscript.",
            code="manuscript_withdraw_forbidden",
            details={"manuscript_id": manuscript_id},
        )

    transition_manuscript_status(
        db,
        manuscript=manuscript,
        to_status=ManuscriptStatus.WITHDRAWN,
        actor=current_user,
        note=note,
    )
    db.commit()
    return manuscript_service.get_manuscript_or_404(db, manuscript.id)


def list_status_history_responses_for_user(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
) -> list[ManuscriptStatusHistoryResponse]:
    """Return anonymity-enforced status transition audit history for an authorized user."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    if not manuscript_service.can_access_manuscript(db, manuscript=manuscript, user=current_user):
        raise ForbiddenError(
            "You do not have permission to view this manuscript's status history.",
            code="manuscript_access_forbidden",
            details={"manuscript_id": manuscript.id},
        )

    entries = list(
        db.scalars(
            select(ManuscriptStatusHistory)
            .where(ManuscriptStatusHistory.manuscript_id == manuscript.id)
            .order_by(ManuscriptStatusHistory.id.asc())
        ).all()
    )
    responses = [ManuscriptStatusHistoryResponse.model_validate(e) for e in entries]
    if manuscript_service.should_mask_author_identity(
        db,
        manuscript=manuscript,
        user=current_user,
    ):
        return [item.model_copy(update={"changed_by_id": None}) for item in responses]
    return responses


def list_journal_manuscripts_paginated(
    db: Session,
    *,
    journal_id: int,
    page: int,
    page_size: int,
    status_filter: ManuscriptStatus | None = None,
    assigned_editor_id: int | None = None,
) -> tuple[list[Manuscript], int]:
    """Return a journal's editorial manuscript queue (excluding private drafts)."""
    journal_service.get_journal_or_404(db, journal_id)

    query = select(Manuscript).where(
        Manuscript.journal_id == journal_id,
        Manuscript.status != ManuscriptStatus.DRAFT.value,
    )
    if status_filter is not None:
        query = query.where(Manuscript.status == status_filter.value)
    if assigned_editor_id is not None:
        query = query.where(Manuscript.assigned_editor_id == assigned_editor_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(
            query.options(selectinload(Manuscript.co_authors))
            .order_by(Manuscript.submitted_at.desc(), Manuscript.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, int(total)


def assign_handling_editor(
    db: Session,
    *,
    manuscript_id: int,
    editor_id: int,
    current_user: User,
) -> Manuscript:
    """Assign a user holding handling_editor or chief_editor role in the same journal."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    _require_chief_editor(db, manuscript=manuscript, user=current_user)

    current_status = ManuscriptStatus(manuscript.status)
    if current_status == ManuscriptStatus.DRAFT or current_status in _TERMINAL_STATUSES:
        raise ConflictError(
            f"Cannot assign a Handling Editor while manuscript is in '{current_status.value}' status.",
            code="manuscript_not_assignable",
            details={"manuscript_id": manuscript.id, "status": current_status.value},
        )

    candidate = db.get(User, editor_id)
    if candidate is None:
        raise NotFoundError(
            f"User {editor_id} was not found.",
            code="user_not_found",
            details={"user_id": editor_id},
        )
    if not candidate.is_active:
        raise BadRequestError(
            f"User {editor_id} is deactivated and cannot be assigned as Handling Editor.",
            code="editor_inactive",
            details={"editor_id": editor_id},
        )

    editor_membership = db.scalar(
        select(JournalMembership.id).where(
            JournalMembership.journal_id == manuscript.journal_id,
            JournalMembership.user_id == editor_id,
            JournalMembership.role.in_(
                [JournalRole.HANDLING_EDITOR.value, JournalRole.CHIEF_EDITOR.value]
            ),
        )
    )
    if editor_membership is None:
        raise BadRequestError(
            f"User {editor_id} does not hold a handling_editor or chief_editor role in journal {manuscript.journal_id}.",
            code="invalid_handling_editor",
            details={"journal_id": manuscript.journal_id, "editor_id": editor_id},
        )

    manuscript.assigned_editor_id = candidate.id
    db.add(manuscript)
    db.commit()
    return manuscript_service.get_manuscript_or_404(db, manuscript.id)


def start_desk_review(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
    note: str | None = None,
) -> Manuscript:
    """Move a submitted manuscript into desk_review."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    _require_assigned_or_chief_editor(db, manuscript=manuscript, user=current_user)

    transition_manuscript_status(
        db,
        manuscript=manuscript,
        to_status=ManuscriptStatus.DESK_REVIEW,
        actor=current_user,
        note=note,
    )
    db.commit()
    return manuscript_service.get_manuscript_or_404(db, manuscript.id)


def desk_reject_manuscript(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
    rationale: str,
) -> Manuscript:
    """Desk-reject a manuscript currently in desk_review with a documented rationale."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    _require_assigned_or_chief_editor(db, manuscript=manuscript, user=current_user)

    if manuscript.status != ManuscriptStatus.DESK_REVIEW.value:
        raise ConflictError(
            f"Desk rejection is only allowed from 'desk_review' status (current: '{manuscript.status}').",
            code="invalid_status_transition",
            details={
                "manuscript_id": manuscript.id,
                "from_status": manuscript.status,
                "to_status": ManuscriptStatus.REJECTED.value,
            },
        )

    transition_manuscript_status(
        db,
        manuscript=manuscript,
        to_status=ManuscriptStatus.REJECTED,
        actor=current_user,
        note=rationale,
    )
    db.commit()
    return manuscript_service.get_manuscript_or_404(db, manuscript.id)


def advance_to_under_review(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
    note: str | None = None,
) -> Manuscript:
    """Advance a manuscript into under_review (from desk_review, or submitted if desk review is disabled)."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    _require_assigned_or_chief_editor(db, manuscript=manuscript, user=current_user)

    transition_manuscript_status(
        db,
        manuscript=manuscript,
        to_status=ManuscriptStatus.UNDER_REVIEW,
        actor=current_user,
        note=note,
    )
    db.commit()
    return manuscript_service.get_manuscript_or_404(db, manuscript.id)
