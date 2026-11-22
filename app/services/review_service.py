"""Business logic for peer-review invitations, structured reviews, and anonymity masking."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models.decision import EditorialDecision
from app.models.journal import AnonymityMode, JournalMembership, JournalRole
from app.models.manuscript import Manuscript, ManuscriptStatus, ManuscriptVersion
from app.models.review import (
    Review,
    ReviewInvitation,
    ReviewInvitationStatus,
    ReviewRecommendation,
)
from app.models.user import User
from app.schemas.review import (
    ReviewCreateRequest,
    ReviewInvitationCreateRequest,
    ReviewInvitationResponse,
    ReviewResponse,
)
from app.services import journal_service, manuscript_service

_ACTIVE_INVITATION_STATUSES = (
    ReviewInvitationStatus.PENDING.value,
    ReviewInvitationStatus.ACCEPTED.value,
    ReviewInvitationStatus.COMPLETED.value,
)


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _get_invitation_or_404(db: Session, invitation_id: int) -> ReviewInvitation:
    invitation = db.scalar(
        select(ReviewInvitation)
        .options(
            selectinload(ReviewInvitation.manuscript),
            selectinload(ReviewInvitation.reviewer),
            selectinload(ReviewInvitation.review),
        )
        .where(ReviewInvitation.id == invitation_id)
    )
    if invitation is None:
        raise NotFoundError(
            f"Review invitation {invitation_id} was not found.",
            code="review_invitation_not_found",
            details={"invitation_id": invitation_id},
        )
    return invitation


def _to_invitation_response(invitation: ReviewInvitation) -> ReviewInvitationResponse:
    """Serialize a ReviewInvitation without ever exposing manuscript author identities."""
    return ReviewInvitationResponse(
        id=invitation.id,
        manuscript_id=invitation.manuscript_id,
        manuscript_title=invitation.manuscript.title,
        journal_id=invitation.manuscript.journal_id,
        reviewer_id=invitation.reviewer_id,
        reviewer_name=invitation.reviewer.full_name if invitation.reviewer else None,
        reviewer_email=invitation.reviewer.email if invitation.reviewer else None,
        review_round=invitation.review_round,
        status=ReviewInvitationStatus(invitation.status),
        invited_by_id=invitation.invited_by_id,
        due_at=invitation.due_at,
        responded_at=invitation.responded_at,
        decline_reason=invitation.decline_reason,
        created_at=invitation.created_at,
        updated_at=invitation.updated_at,
    )


def _build_reviewer_labels(db: Session, manuscript_id: int) -> dict[int, str]:
    """Assign deterministic 1-based anonymous labels ('Reviewer #1', ...) per manuscript."""
    reviewer_ids = list(
        db.scalars(
            select(Review.reviewer_id)
            .where(Review.manuscript_id == manuscript_id)
            .order_by(Review.id.asc())
        ).all()
    )
    labels: dict[int, str] = {}
    for reviewer_id in reviewer_ids:
        if reviewer_id not in labels:
            labels[reviewer_id] = f"Reviewer #{len(labels) + 1}"
    return labels


def project_review_for_viewer(
    review: Review,
    *,
    reviewer_label: str,
    viewer_role: Literal["editor", "author", "reviewer"],
    anonymity_mode: AnonymityMode,
) -> ReviewResponse:
    """Project a Review ORM entity with strict server-side anonymity and confidentiality rules."""
    expose_reviewer_identity = (
        viewer_role in ("editor", "reviewer") or anonymity_mode == AnonymityMode.OPEN
    )
    expose_confidential = viewer_role in ("editor", "reviewer")

    return ReviewResponse(
        id=review.id,
        invitation_id=review.invitation_id,
        manuscript_id=review.manuscript_id,
        manuscript_version_id=review.manuscript_version_id,
        review_round=review.review_round,
        reviewer_label=reviewer_label,
        reviewer_id=review.reviewer_id if expose_reviewer_identity else None,
        reviewer_name=(
            review.reviewer.full_name if expose_reviewer_identity and review.reviewer else None
        ),
        reviewer_email=(
            review.reviewer.email if expose_reviewer_identity and review.reviewer else None
        ),
        reviewer_affiliation=(
            review.reviewer.affiliation if expose_reviewer_identity and review.reviewer else None
        ),
        originality_score=review.originality_score,
        methodology_score=review.methodology_score,
        clarity_score=review.clarity_score,
        significance_score=review.significance_score,
        recommendation=ReviewRecommendation(review.recommendation),
        comments_to_author=review.comments_to_author,
        confidential_comments_to_editor=(
            review.confidential_comments_to_editor if expose_confidential else None
        ),
        submitted_at=review.submitted_at,
    )


def _require_editorial_access(db: Session, *, manuscript: Manuscript, user: User) -> None:
    if not manuscript_service.has_editorial_access(db, manuscript=manuscript, user=user):
        raise ForbiddenError(
            "Only the assigned Handling Editor, journal Chief Editor, or System Admin can perform this action.",
            code="editorial_permission_required",
            details={"journal_id": manuscript.journal_id, "manuscript_id": manuscript.id},
        )


def invite_reviewer(
    db: Session,
    *,
    manuscript_id: int,
    payload: ReviewInvitationCreateRequest,
    current_user: User,
) -> ReviewInvitationResponse:
    """Invite an eligible journal reviewer to evaluate a manuscript in under_review."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    _require_editorial_access(db, manuscript=manuscript, user=current_user)

    if (
        manuscript.status != ManuscriptStatus.UNDER_REVIEW.value
        or manuscript.current_review_round < 1
    ):
        raise ConflictError(
            f"Reviewers can only be invited when manuscript is in 'under_review' status (current: '{manuscript.status}').",
            code="manuscript_not_under_review",
            details={"manuscript_id": manuscript.id, "status": manuscript.status},
        )

    reviewer = db.get(User, payload.reviewer_id)
    if reviewer is None:
        raise NotFoundError(
            f"User {payload.reviewer_id} was not found.",
            code="user_not_found",
            details={"user_id": payload.reviewer_id},
        )
    if not reviewer.is_active:
        raise BadRequestError(
            f"User {payload.reviewer_id} is deactivated and cannot be invited to review.",
            code="reviewer_inactive",
            details={"reviewer_id": payload.reviewer_id},
        )

    reviewer_membership = db.scalar(
        select(JournalMembership.id).where(
            JournalMembership.journal_id == manuscript.journal_id,
            JournalMembership.user_id == reviewer.id,
            JournalMembership.role == JournalRole.REVIEWER.value,
        )
    )
    if reviewer_membership is None:
        raise BadRequestError(
            f"User {reviewer.id} does not hold the 'reviewer' role in journal {manuscript.journal_id}.",
            code="invalid_reviewer",
            details={"journal_id": manuscript.journal_id, "reviewer_id": reviewer.id},
        )

    if manuscript.submitter_id == reviewer.id:
        raise ConflictError(
            "Cannot invite the submitting author to review their own manuscript.",
            code="reviewer_conflict_of_interest",
            details={"manuscript_id": manuscript.id, "reviewer_id": reviewer.id},
        )

    reviewer_email_lower = reviewer.email.strip().lower()
    for co_author in manuscript.co_authors:
        if (
            co_author.user_id == reviewer.id
            or co_author.email.strip().lower() == reviewer_email_lower
        ):
            raise ConflictError(
                "Cannot invite a co-author of this manuscript as a reviewer.",
                code="reviewer_conflict_of_interest",
                details={"manuscript_id": manuscript.id, "reviewer_id": reviewer.id},
            )

    existing_active = db.scalar(
        select(ReviewInvitation.id).where(
            ReviewInvitation.manuscript_id == manuscript.id,
            ReviewInvitation.reviewer_id == reviewer.id,
            ReviewInvitation.review_round == manuscript.current_review_round,
            ReviewInvitation.status.in_(_ACTIVE_INVITATION_STATUSES),
        )
    )
    if existing_active is not None:
        raise ConflictError(
            f"Reviewer {reviewer.id} already has an active review invitation for round {manuscript.current_review_round}.",
            code="duplicate_review_invitation",
            details={
                "manuscript_id": manuscript.id,
                "reviewer_id": reviewer.id,
                "review_round": manuscript.current_review_round,
            },
        )

    now = datetime.now(UTC)
    if payload.due_at is None:
        config = journal_service.get_workflow_config(db, manuscript.journal_id)
        due_at = now + timedelta(days=config.review_sla_days)
    else:
        due_at = _normalize_utc(payload.due_at)
        if due_at <= now:
            raise BadRequestError(
                "Review invitation due_at must be in the future.",
                code="invalid_due_date",
                details={"due_at": due_at.isoformat()},
            )

    invitation = ReviewInvitation(
        manuscript_id=manuscript.id,
        reviewer_id=reviewer.id,
        review_round=manuscript.current_review_round,
        status=ReviewInvitationStatus.PENDING.value,
        invited_by_id=current_user.id,
        due_at=due_at,
    )
    db.add(invitation)
    db.commit()

    loaded = _get_invitation_or_404(db, invitation.id)
    return _to_invitation_response(loaded)


def list_manuscript_invitations(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
    review_round: int | None = None,
    status_filter: ReviewInvitationStatus | None = None,
) -> list[ReviewInvitationResponse]:
    """List all review invitations for a manuscript across rounds (editors and System Admin only)."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    _require_editorial_access(db, manuscript=manuscript, user=current_user)

    query = (
        select(ReviewInvitation)
        .options(
            selectinload(ReviewInvitation.manuscript),
            selectinload(ReviewInvitation.reviewer),
        )
        .where(ReviewInvitation.manuscript_id == manuscript.id)
    )
    if review_round is not None:
        query = query.where(ReviewInvitation.review_round == review_round)
    if status_filter is not None:
        query = query.where(ReviewInvitation.status == status_filter.value)

    invitations = list(
        db.scalars(
            query.order_by(ReviewInvitation.review_round.asc(), ReviewInvitation.id.asc())
        ).all()
    )
    return [_to_invitation_response(inv) for inv in invitations]


def list_my_invitations_paginated(
    db: Session,
    *,
    current_user: User,
    page: int,
    page_size: int,
    status_filter: ReviewInvitationStatus | None = None,
    manuscript_id: int | None = None,
) -> tuple[list[ReviewInvitationResponse], int]:
    """List paginated review invitations addressed to the authenticated reviewer."""
    query = select(ReviewInvitation).where(ReviewInvitation.reviewer_id == current_user.id)
    if status_filter is not None:
        query = query.where(ReviewInvitation.status == status_filter.value)
    if manuscript_id is not None:
        query = query.where(ReviewInvitation.manuscript_id == manuscript_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    invitations = list(
        db.scalars(
            query.options(
                selectinload(ReviewInvitation.manuscript),
                selectinload(ReviewInvitation.reviewer),
            )
            .order_by(ReviewInvitation.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return [_to_invitation_response(inv) for inv in invitations], int(total)


def get_invitation_for_user(
    db: Session,
    *,
    invitation_id: int,
    current_user: User,
) -> ReviewInvitationResponse:
    """Inspect a single review invitation (invited reviewer, editors, or System Admin)."""
    invitation = _get_invitation_or_404(db, invitation_id)
    if invitation.reviewer_id != current_user.id and not manuscript_service.has_editorial_access(
        db,
        manuscript=invitation.manuscript,
        user=current_user,
    ):
        raise ForbiddenError(
            "You do not have permission to view this review invitation.",
            code="invitation_access_forbidden",
            details={"invitation_id": invitation_id},
        )
    return _to_invitation_response(invitation)


def accept_invitation(
    db: Session,
    *,
    invitation_id: int,
    current_user: User,
) -> ReviewInvitationResponse:
    """Accept a pending review invitation as the invited reviewer."""
    invitation = _get_invitation_or_404(db, invitation_id)
    if invitation.reviewer_id != current_user.id:
        raise ForbiddenError(
            "Only the invited reviewer can respond to this invitation.",
            code="invitation_response_forbidden",
            details={"invitation_id": invitation_id},
        )
    if invitation.status != ReviewInvitationStatus.PENDING.value:
        raise ConflictError(
            f"Review invitation cannot be accepted while in '{invitation.status}' status.",
            code="invitation_not_pending",
            details={"invitation_id": invitation_id, "status": invitation.status},
        )
    if invitation.manuscript.status != ManuscriptStatus.UNDER_REVIEW.value:
        raise ConflictError(
            f"Cannot accept review invitation because manuscript is in '{invitation.manuscript.status}' status.",
            code="manuscript_not_under_review",
            details={
                "manuscript_id": invitation.manuscript_id,
                "status": invitation.manuscript.status,
            },
        )

    invitation.status = ReviewInvitationStatus.ACCEPTED.value
    invitation.responded_at = datetime.now(UTC)
    db.add(invitation)
    db.commit()

    loaded = _get_invitation_or_404(db, invitation.id)
    return _to_invitation_response(loaded)


def decline_invitation(
    db: Session,
    *,
    invitation_id: int,
    decline_reason: str | None,
    current_user: User,
) -> ReviewInvitationResponse:
    """Decline a pending review invitation with an optional reason."""
    invitation = _get_invitation_or_404(db, invitation_id)
    if invitation.reviewer_id != current_user.id:
        raise ForbiddenError(
            "Only the invited reviewer can respond to this invitation.",
            code="invitation_response_forbidden",
            details={"invitation_id": invitation_id},
        )
    if invitation.status != ReviewInvitationStatus.PENDING.value:
        raise ConflictError(
            f"Review invitation cannot be declined while in '{invitation.status}' status.",
            code="invitation_not_pending",
            details={"invitation_id": invitation_id, "status": invitation.status},
        )

    invitation.status = ReviewInvitationStatus.DECLINED.value
    invitation.responded_at = datetime.now(UTC)
    invitation.decline_reason = decline_reason
    db.add(invitation)
    db.commit()

    loaded = _get_invitation_or_404(db, invitation.id)
    return _to_invitation_response(loaded)


def submit_review(
    db: Session,
    *,
    invitation_id: int,
    payload: ReviewCreateRequest,
    current_user: User,
) -> ReviewResponse:
    """Submit a structured peer review once for an accepted invitation."""
    invitation = _get_invitation_or_404(db, invitation_id)
    if invitation.reviewer_id != current_user.id:
        raise ForbiddenError(
            "Only the invited reviewer can submit a review for this invitation.",
            code="review_submit_forbidden",
            details={"invitation_id": invitation_id},
        )

    if invitation.status == ReviewInvitationStatus.COMPLETED.value or invitation.review is not None:
        raise ConflictError(
            "A review has already been submitted for this invitation.",
            code="review_already_submitted",
            details={"invitation_id": invitation_id},
        )

    if invitation.status != ReviewInvitationStatus.ACCEPTED.value:
        raise ConflictError(
            f"Review can only be submitted for an accepted invitation (current: '{invitation.status}').",
            code="invitation_not_accepted",
            details={"invitation_id": invitation_id, "status": invitation.status},
        )

    manuscript = invitation.manuscript
    if manuscript.status != ManuscriptStatus.UNDER_REVIEW.value:
        raise ConflictError(
            f"Cannot submit a review while manuscript is in '{manuscript.status}' status.",
            code="manuscript_not_under_review",
            details={"manuscript_id": manuscript.id, "status": manuscript.status},
        )

    version = db.scalar(
        select(ManuscriptVersion).where(
            ManuscriptVersion.manuscript_id == manuscript.id,
            ManuscriptVersion.version_number == manuscript.current_version_number,
        )
    )
    if version is None:
        raise ConflictError(
            f"No uploaded PDF version found for manuscript {manuscript.id}.",
            code="manuscript_version_required",
            details={"manuscript_id": manuscript.id},
        )

    review = Review(
        invitation_id=invitation.id,
        manuscript_id=manuscript.id,
        manuscript_version_id=version.id,
        reviewer_id=current_user.id,
        review_round=invitation.review_round,
        originality_score=payload.originality_score,
        methodology_score=payload.methodology_score,
        clarity_score=payload.clarity_score,
        significance_score=payload.significance_score,
        recommendation=payload.recommendation.value,
        comments_to_author=payload.comments_to_author,
        confidential_comments_to_editor=payload.confidential_comments_to_editor,
    )
    invitation.status = ReviewInvitationStatus.COMPLETED.value
    db.add(review)
    db.add(invitation)
    db.commit()

    loaded_review = db.scalar(
        select(Review)
        .options(selectinload(Review.reviewer))
        .where(Review.id == review.id)
    )
    assert loaded_review is not None
    labels = _build_reviewer_labels(db, manuscript.id)
    config = journal_service.get_workflow_config(db, manuscript.journal_id)
    return project_review_for_viewer(
        loaded_review,
        reviewer_label=labels[loaded_review.reviewer_id],
        viewer_role="reviewer",
        anonymity_mode=AnonymityMode(config.anonymity_mode),
    )


def list_manuscript_reviews_for_user(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
    review_round: int | None = None,
) -> list[ReviewResponse]:
    """List reviews for a manuscript with strict role- and anonymity-mode masking."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)

    viewer_role: Literal["editor", "author", "reviewer"]
    if manuscript_service.has_editorial_access(db, manuscript=manuscript, user=current_user):
        viewer_role = "editor"
    elif manuscript.submitter_id == current_user.id:
        viewer_role = "author"
    elif manuscript_service.is_accepted_reviewer(
        db,
        manuscript_id=manuscript.id,
        user_id=current_user.id,
    ):
        viewer_role = "reviewer"
    else:
        raise ForbiddenError(
            "You do not have permission to view reviews for this manuscript.",
            code="reviews_access_forbidden",
            details={"manuscript_id": manuscript.id},
        )

    labels = _build_reviewer_labels(db, manuscript.id)
    config = journal_service.get_workflow_config(db, manuscript.journal_id)
    anonymity_mode = AnonymityMode(config.anonymity_mode)

    query = (
        select(Review)
        .options(selectinload(Review.reviewer))
        .where(Review.manuscript_id == manuscript.id)
    )
    if review_round is not None:
        query = query.where(Review.review_round == review_round)
    if viewer_role == "reviewer":
        query = query.where(Review.reviewer_id == current_user.id)
    elif viewer_role == "author":
        decided_rounds = set(
            db.scalars(
                select(EditorialDecision.review_round).where(
                    EditorialDecision.manuscript_id == manuscript.id
                )
            ).all()
        )
        if not decided_rounds:
            return []
        query = query.where(Review.review_round.in_(decided_rounds))

    reviews = list(
        db.scalars(query.order_by(Review.review_round.asc(), Review.id.asc())).all()
    )
    return [
        project_review_for_viewer(
            review,
            reviewer_label=labels[review.reviewer_id],
            viewer_role=viewer_role,
            anonymity_mode=anonymity_mode,
        )
        for review in reviews
    ]
