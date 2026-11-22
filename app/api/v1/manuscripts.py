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
    ManuscriptCreateRequest,
    ManuscriptResponse,
    ManuscriptUpdateRequest,
    ManuscriptVersionResponse,
)
from app.services import manuscript_service

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
    """Return manuscript metadata and co-authors for authorized stakeholders."""
    manuscript = manuscript_service.get_manuscript_for_user(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
    )
    return ManuscriptResponse.model_validate(manuscript)


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
    versions = manuscript_service.list_manuscript_versions_for_user(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
    )
    return [ManuscriptVersionResponse.model_validate(v) for v in versions]


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
