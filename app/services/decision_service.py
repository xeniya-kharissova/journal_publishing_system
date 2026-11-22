"""Business logic for formal editorial decisions, quality gates, and revision resubmission."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, ConflictError, ForbiddenError
from app.models.decision import EditorialDecision, EditorialDecisionType
from app.models.journal import JournalRole, JournalWorkflowConfig
from app.models.manuscript import Manuscript, ManuscriptStatus
from app.models.review import Review
from app.models.user import User
from app.schemas.decision import EditorialDecisionCreateRequest
from app.services import journal_service, manuscript_service, workflow_service

_DECISION_TARGET_STATUS: dict[EditorialDecisionType, ManuscriptStatus] = {
    EditorialDecisionType.ACCEPT: ManuscriptStatus.ACCEPTED,
    EditorialDecisionType.MINOR_REVISION: ManuscriptStatus.REVISION_REQUESTED,
    EditorialDecisionType.MAJOR_REVISION: ManuscriptStatus.REVISION_REQUESTED,
    EditorialDecisionType.REJECT: ManuscriptStatus.REJECTED,
}


def _is_chief_editor_or_admin(db: Session, *, manuscript: Manuscript, user: User) -> bool:
    if user.is_system_admin:
        return True
    return journal_service.has_journal_role(
        db,
        user=user,
        journal_id=manuscript.journal_id,
        allowed_roles=[JournalRole.CHIEF_EDITOR],
    )


def _check_plagiarism_gate(
    db: Session,
    *,
    manuscript: Manuscript,
    config: JournalWorkflowConfig,
) -> dict[str, Any] | None:
    """Extension hook for plagiarism-screening quality gate (implemented in ticket 09)."""
    _ = (db, manuscript, config)
    return None


def _evaluate_accept_quality_gates(
    db: Session,
    *,
    manuscript: Manuscript,
    config: JournalWorkflowConfig,
) -> list[dict[str, Any]]:
    """Evaluate all journal quality gates required before accepting a manuscript."""
    violations: list[dict[str, Any]] = []

    completed_reviews = (
        db.scalar(
            select(func.count(Review.id)).where(
                Review.manuscript_id == manuscript.id,
                Review.review_round == manuscript.current_review_round,
            )
        )
        or 0
    )
    if completed_reviews < config.min_reviewers:
        violations.append(
            {
                "gate": "min_reviewers",
                "required": config.min_reviewers,
                "actual": int(completed_reviews),
                "review_round": manuscript.current_review_round,
            }
        )

    plagiarism_violation = _check_plagiarism_gate(
        db,
        manuscript=manuscript,
        config=config,
    )
    if plagiarism_violation is not None:
        violations.append(plagiarism_violation)

    return violations


def issue_editorial_decision(
    db: Session,
    *,
    manuscript_id: int,
    payload: EditorialDecisionCreateRequest,
    current_user: User,
) -> EditorialDecision:
    """Issue a formal editorial decision, enforcing accept quality gates and Chief Editor overrides."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    if not manuscript_service.has_editorial_access(db, manuscript=manuscript, user=current_user):
        raise ForbiddenError(
            "Only the assigned Handling Editor, journal Chief Editor, or System Admin can issue editorial decisions.",
            code="editorial_permission_required",
            details={"journal_id": manuscript.journal_id, "manuscript_id": manuscript.id},
        )

    if (
        manuscript.status != ManuscriptStatus.UNDER_REVIEW.value
        or manuscript.current_review_round < 1
    ):
        raise ConflictError(
            f"Editorial decisions can only be issued while manuscript is in 'under_review' status (current: '{manuscript.status}').",
            code="manuscript_not_under_review",
            details={"manuscript_id": manuscript.id, "status": manuscript.status},
        )

    existing_decision = db.scalar(
        select(EditorialDecision.id).where(
            EditorialDecision.manuscript_id == manuscript.id,
            EditorialDecision.review_round == manuscript.current_review_round,
        )
    )
    if existing_decision is not None:
        raise ConflictError(
            f"An editorial decision has already been recorded for review round {manuscript.current_review_round}.",
            code="decision_already_recorded",
            details={
                "manuscript_id": manuscript.id,
                "review_round": manuscript.current_review_round,
            },
        )

    is_chief_or_admin = _is_chief_editor_or_admin(db, manuscript=manuscript, user=current_user)
    if payload.override_reason is not None and not is_chief_or_admin:
        raise ForbiddenError(
            "Only a journal Chief Editor or System Admin can override quality gates.",
            code="quality_gate_override_forbidden",
            details={"journal_id": manuscript.journal_id, "manuscript_id": manuscript.id},
        )

    config = journal_service.get_workflow_config(db, manuscript.journal_id)
    effective_override_reason: str | None = None

    if payload.decision == EditorialDecisionType.ACCEPT:
        violations = _evaluate_accept_quality_gates(
            db,
            manuscript=manuscript,
            config=config,
        )
        if violations:
            if payload.override_reason is None:
                raise ConflictError(
                    "Acceptance quality gates are not satisfied for the current review round.",
                    code="quality_gate_not_met",
                    details={"manuscript_id": manuscript.id, "violations": violations},
                )
            effective_override_reason = payload.override_reason

    target_status = _DECISION_TARGET_STATUS[payload.decision]
    if effective_override_reason is not None:
        history_note = (
            f"Editorial decision: {payload.decision.value} "
            f"(quality gate override: {effective_override_reason})"
        )
    else:
        history_note = f"Editorial decision: {payload.decision.value}"

    decision_record = EditorialDecision(
        manuscript_id=manuscript.id,
        review_round=manuscript.current_review_round,
        manuscript_version_number=manuscript.current_version_number,
        decided_by_id=current_user.id,
        decision=payload.decision.value,
        decision_letter=payload.decision_letter,
        override_reason=effective_override_reason,
    )

    workflow_service.transition_manuscript_status(
        db,
        manuscript=manuscript,
        to_status=target_status,
        actor=current_user,
        note=history_note,
        workflow_config=config,
    )
    db.add(decision_record)
    db.commit()
    db.refresh(decision_record)
    return decision_record


def list_manuscript_decisions_for_user(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
) -> list[EditorialDecision]:
    """List formal editorial decisions for a manuscript (submitting author, editors, System Admin)."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    if (
        manuscript.submitter_id != current_user.id
        and not manuscript_service.has_editorial_access(
            db,
            manuscript=manuscript,
            user=current_user,
        )
    ):
        raise ForbiddenError(
            "You do not have permission to view editorial decisions for this manuscript.",
            code="decisions_access_forbidden",
            details={"manuscript_id": manuscript.id},
        )

    return list(
        db.scalars(
            select(EditorialDecision)
            .where(EditorialDecision.manuscript_id == manuscript.id)
            .order_by(EditorialDecision.review_round.asc(), EditorialDecision.id.asc())
        ).all()
    )


def resubmit_revised_manuscript(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
    note: str | None = None,
) -> Manuscript:
    """Resubmit a revised manuscript after uploading a newer PDF version, starting the next review round."""
    manuscript = manuscript_service.get_manuscript_or_404(db, manuscript_id)
    if manuscript.submitter_id != current_user.id:
        raise ForbiddenError(
            "Only the submitting author can resubmit a revised manuscript.",
            code="manuscript_resubmit_forbidden",
            details={"manuscript_id": manuscript.id},
        )

    if manuscript.status != ManuscriptStatus.REVISION_REQUESTED.value:
        # Delegate to state machine for consistent 409 Conflict error payload.
        workflow_service.transition_manuscript_status(
            db,
            manuscript=manuscript,
            to_status=ManuscriptStatus.UNDER_REVIEW,
            actor=current_user,
            note=note,
        )

    latest_decision = db.scalar(
        select(EditorialDecision)
        .where(EditorialDecision.manuscript_id == manuscript.id)
        .order_by(EditorialDecision.review_round.desc(), EditorialDecision.id.desc())
    )
    previous_version = (
        latest_decision.manuscript_version_number
        if latest_decision is not None
        else manuscript.current_review_round
    )
    if manuscript.current_version_number <= previous_version:
        raise BadRequestError(
            "A newer revised manuscript PDF version must be uploaded before resubmitting.",
            code="revised_version_required",
            details={
                "manuscript_id": manuscript.id,
                "previous_round_version": previous_version,
                "current_version_number": manuscript.current_version_number,
            },
        )

    workflow_service.transition_manuscript_status(
        db,
        manuscript=manuscript,
        to_status=ManuscriptStatus.UNDER_REVIEW,
        actor=current_user,
        note=note or f"Author resubmitted revised version v{manuscript.current_version_number}.",
    )
    db.commit()
    return manuscript_service.get_manuscript_or_404(db, manuscript.id)
