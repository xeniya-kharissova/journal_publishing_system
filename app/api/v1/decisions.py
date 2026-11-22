"""Editorial decision and revision resubmission endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.decision import (
    EditorialDecisionCreateRequest,
    EditorialDecisionResponse,
)
from app.schemas.manuscript import ManuscriptResponse, WorkflowNoteRequest
from app.services import decision_service

router = APIRouter(tags=["Editorial Decisions & Revisions"])


@router.post(
    "/manuscripts/{manuscript_id}/decisions",
    response_model=EditorialDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a formal editorial decision for the current review round",
)
def issue_editorial_decision(
    manuscript_id: int,
    payload: EditorialDecisionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EditorialDecisionResponse:
    """Record accept, minor_revision, major_revision, or reject with quality-gate enforcement."""
    decision = decision_service.issue_editorial_decision(
        db,
        manuscript_id=manuscript_id,
        payload=payload,
        current_user=current_user,
    )
    return EditorialDecisionResponse.model_validate(decision)


@router.get(
    "/manuscripts/{manuscript_id}/decisions",
    response_model=list[EditorialDecisionResponse],
    summary="List editorial decisions for a manuscript across review rounds",
)
def list_manuscript_decisions(
    manuscript_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EditorialDecisionResponse]:
    """Return chronological editorial decision records for the author, editors, or System Admin."""
    decisions = decision_service.list_manuscript_decisions_for_user(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
    )
    return [EditorialDecisionResponse.model_validate(d) for d in decisions]


@router.post(
    "/manuscripts/{manuscript_id}/resubmit",
    response_model=ManuscriptResponse,
    summary="Resubmit a revised manuscript into the next peer-review round",
)
def resubmit_revised_manuscript(
    manuscript_id: int,
    payload: WorkflowNoteRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManuscriptResponse:
    """Transition a revision_requested manuscript with a newly uploaded PDF back to under_review."""
    manuscript = decision_service.resubmit_revised_manuscript(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
        note=payload.note if payload else None,
    )
    return ManuscriptResponse.model_validate(manuscript)
