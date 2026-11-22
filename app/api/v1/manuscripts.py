"""Manuscript draft, ordered co-author, and versioned PDF upload/download endpoints."""

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.adapters.storage import StorageAdapter
from app.api.deps import get_current_user, get_storage_adapter
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.pagination import PaginatedResponse
from app.models.manuscript import ManuscriptStatus
from app.models.user import User
from app.schemas.manuscript import (
    AssignEditorRequest,
    DeskRejectRequest,
    ManuscriptCreateRequest,
    ManuscriptResponse,
    ManuscriptStatusHistoryResponse,
    ManuscriptUpdateRequest,
    ManuscriptVersionResponse,
    WorkflowNoteRequest,
)
from app.services import manuscript_service, workflow_service

router = APIRouter(prefix="/manuscripts", tags=["Manuscripts & Files"])


@router.post(
    "",
    response_model=ManuscriptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new manuscript draft",
)
def create_manuscript_draft(
    payload: ManuscriptCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManuscriptResponse:
    """Create a manuscript draft with ordered co-authors in an active journal."""
    manuscript = manuscript_service.create_manuscript_draft(
        db,
        payload=payload,
        current_user=current_user,
    )
    return ManuscriptResponse.model_validate(manuscript)


@router.get(
    "",
    response_model=PaginatedResponse[ManuscriptResponse],
    summary="List the authenticated author's submissions",
)
def list_my_manuscripts(
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
    journal_id: int | None = Query(default=None, ge=1, description="Optional filter by journal."),
    status_filter: ManuscriptStatus | None = Query(
        default=None,
        alias="status",
        description="Optional filter by workflow status.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ManuscriptResponse]:
    """Return a paginated list of submissions created by the authenticated user."""
    items, total = manuscript_service.list_my_manuscripts_paginated(
        db,
        current_user=current_user,
        page=page,
        page_size=page_size,
        journal_id=journal_id,
        status_filter=status_filter,
    )
    return PaginatedResponse[ManuscriptResponse](
        page=page,
        page_size=page_size,
        total=total,
        items=[ManuscriptResponse.model_validate(m) for m in items],
    )


@router.get(
    "/{manuscript_id}",
    response_model=ManuscriptResponse,
    summary="Inspect manuscript details",
)
def get_manuscript(
    manuscript_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManuscriptResponse:
    """Return anonymity-enforced manuscript metadata and co-authors for authorized stakeholders."""
    return manuscript_service.get_manuscript_response_for_user(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
    )


@router.patch(
    "/{manuscript_id}",
    response_model=ManuscriptResponse,
    summary="Update a manuscript draft",
)
def update_manuscript_draft(
    manuscript_id: int,
    payload: ManuscriptUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManuscriptResponse:
    """Update metadata and ordered co-authors of a manuscript while in draft status."""
    manuscript = manuscript_service.update_manuscript_draft(
        db,
        manuscript_id=manuscript_id,
        payload=payload,
        current_user=current_user,
    )
    return ManuscriptResponse.model_validate(manuscript)


@router.post(
    "/{manuscript_id}/versions",
    response_model=ManuscriptVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a new manuscript PDF version",
)
def upload_manuscript_version(
    manuscript_id: int,
    file: UploadFile = File(..., description="Manuscript PDF file."),
    response_to_reviewers: str | None = Form(
        default=None,
        description="Optional response-to-reviewers letter for revised uploads.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageAdapter = Depends(get_storage_adapter),
    settings: Settings = Depends(get_settings),
) -> ManuscriptVersionResponse:
    """Upload a validated PDF as the next sequential version and extract text locally."""
    version = manuscript_service.upload_manuscript_version(
        db,
        manuscript_id=manuscript_id,
        file=file,
        current_user=current_user,
        storage=storage,
        settings=settings,
        response_to_reviewers=response_to_reviewers,
    )
    return ManuscriptVersionResponse.model_validate(version)


@router.get(
    "/{manuscript_id}/versions",
    response_model=list[ManuscriptVersionResponse],
    summary="List manuscript version history",
)
def list_manuscript_versions(
    manuscript_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ManuscriptVersionResponse]:
    """Return the ordered version history for an authorized manuscript."""
    return manuscript_service.list_manuscript_version_responses_for_user(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
    )


@router.get(
    "/{manuscript_id}/versions/{version_number}/download",
    summary="Download a specific manuscript version PDF",
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Raw PDF file stream for the requested manuscript version.",
        }
    },
)
def download_manuscript_version(
    manuscript_id: int,
    version_number: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageAdapter = Depends(get_storage_adapter),
) -> Response:
    """Stream a manuscript version PDF to authorized stakeholders only."""
    version, pdf_bytes = manuscript_service.download_manuscript_version_for_user(
        db,
        manuscript_id=manuscript_id,
        version_number=version_number,
        current_user=current_user,
        storage=storage,
    )
    safe_download_name = version.original_filename.replace('"', "")
    return Response(
        content=pdf_bytes,
        media_type=version.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_download_name}"',
        },
    )


@router.post(
    "/{manuscript_id}/submit",
    response_model=ManuscriptResponse,
    summary="Submit a completed draft manuscript into editorial workflow",
)
def submit_manuscript(
    manuscript_id: int,
    payload: WorkflowNoteRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManuscriptResponse:
    """Transition a draft manuscript with an uploaded PDF to submitted status."""
    manuscript = workflow_service.submit_manuscript(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
        note=payload.note if payload else None,
    )
    return ManuscriptResponse.model_validate(manuscript)


@router.post(
    "/{manuscript_id}/withdraw",
    response_model=ManuscriptResponse,
    summary="Withdraw own manuscript prior to publication",
)
def withdraw_manuscript(
    manuscript_id: int,
    payload: WorkflowNoteRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManuscriptResponse:
    """Transition an author's non-published, non-rejected manuscript to withdrawn."""
    manuscript = workflow_service.withdraw_manuscript(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
        note=payload.note if payload else None,
    )
    return ManuscriptResponse.model_validate(manuscript)


@router.get(
    "/{manuscript_id}/status-history",
    response_model=list[ManuscriptStatusHistoryResponse],
    summary="View immutable status transition audit history",
)
def list_manuscript_status_history(
    manuscript_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ManuscriptStatusHistoryResponse]:
    """Return chronological status transitions for an authorized manuscript."""
    return workflow_service.list_status_history_responses_for_user(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
    )


@router.post(
    "/{manuscript_id}/assign-editor",
    response_model=ManuscriptResponse,
    summary="Assign a Handling Editor (Chief Editor or System Admin)",
)
def assign_handling_editor(
    manuscript_id: int,
    payload: AssignEditorRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManuscriptResponse:
    """Assign a journal editor (handling_editor or chief_editor) to handle this manuscript."""
    manuscript = workflow_service.assign_handling_editor(
        db,
        manuscript_id=manuscript_id,
        editor_id=payload.editor_id,
        current_user=current_user,
    )
    return ManuscriptResponse.model_validate(manuscript)


@router.post(
    "/{manuscript_id}/desk-review",
    response_model=ManuscriptResponse,
    summary="Move submitted manuscript into desk review",
)
def start_desk_review(
    manuscript_id: int,
    payload: WorkflowNoteRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManuscriptResponse:
    """Transition a submitted manuscript to desk_review (assigned Handling Editor or Chief Editor)."""
    manuscript = workflow_service.start_desk_review(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
        note=payload.note if payload else None,
    )
    return ManuscriptResponse.model_validate(manuscript)


@router.post(
    "/{manuscript_id}/desk-reject",
    response_model=ManuscriptResponse,
    summary="Desk-reject a manuscript with a documented rationale",
)
def desk_reject_manuscript(
    manuscript_id: int,
    payload: DeskRejectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManuscriptResponse:
    """Transition a manuscript in desk_review to rejected with a logged rationale."""
    manuscript = workflow_service.desk_reject_manuscript(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
        rationale=payload.rationale,
    )
    return ManuscriptResponse.model_validate(manuscript)


@router.post(
    "/{manuscript_id}/advance-to-review",
    response_model=ManuscriptResponse,
    summary="Advance manuscript to peer review (under_review)",
)
def advance_to_under_review(
    manuscript_id: int,
    payload: WorkflowNoteRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ManuscriptResponse:
    """Advance manuscript into under_review and initialize review round 1."""
    manuscript = workflow_service.advance_to_under_review(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
        note=payload.note if payload else None,
    )
    return ManuscriptResponse.model_validate(manuscript)
