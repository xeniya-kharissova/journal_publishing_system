"""Multi-journal directory, administration, per-journal RBAC, and workflow config endpoints."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import require_journal_roles, require_system_admin
from app.core.database import get_db
from app.core.pagination import PaginatedResponse
from app.models.journal import JournalRole
from app.models.manuscript import ManuscriptStatus
from app.models.user import User
from app.schemas.journal import (
    JournalCreateRequest,
    JournalMemberAssignRequest,
    JournalMemberResponse,
    JournalResponse,
    JournalUpdateRequest,
    JournalWorkflowConfigResponse,
    JournalWorkflowConfigUpdateRequest,
)
from app.schemas.manuscript import ManuscriptResponse
from app.services import journal_service, workflow_service

router = APIRouter(prefix="/journals", tags=["Journals & RBAC"])


@router.get(
    "",
    response_model=PaginatedResponse[JournalResponse],
    summary="Browse active journals (public directory)",
)
def list_journals(
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
    search: str | None = Query(
        default=None,
        description="Optional case-insensitive filter by title, slug, or description.",
    ),
    db: Session = Depends(get_db),
) -> PaginatedResponse[JournalResponse]:
    """Return a paginated directory of active scholarly journals and their policies."""
    items, total = journal_service.list_active_journals_paginated(
        db,
        page=page,
        page_size=page_size,
        search=search,
    )
    return PaginatedResponse[JournalResponse](
        page=page,
        page_size=page_size,
        total=total,
        items=[JournalResponse.model_validate(j) for j in items],
    )


@router.get(
    "/{journal_id}",
    response_model=JournalResponse,
    summary="Inspect a journal's public metadata and policies",
)
def get_journal(
    journal_id: int,
    db: Session = Depends(get_db),
) -> JournalResponse:
    """Return public metadata and editorial workflow policies for a journal."""
    journal = journal_service.get_journal_or_404(db, journal_id)
    return JournalResponse.model_validate(journal)


@router.post(
    "",
    response_model=JournalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new journal (System Admin only)",
)
def create_journal(
    payload: JournalCreateRequest,
    _admin: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> JournalResponse:
    """Create a scholarly journal and initialize its default workflow configuration."""
    journal = journal_service.create_journal(db, payload)
    return JournalResponse.model_validate(journal)


@router.patch(
    "/{journal_id}",
    response_model=JournalResponse,
    summary="Update or deactivate a journal (System Admin only)",
)
def update_journal(
    journal_id: int,
    payload: JournalUpdateRequest,
    _admin: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> JournalResponse:
    """Update journal metadata, APC settings, DOI prefix, or active status."""
    journal = journal_service.update_journal(db, journal_id, payload)
    return JournalResponse.model_validate(journal)


@router.get(
    "/{journal_id}/workflow-config",
    response_model=JournalWorkflowConfigResponse,
    summary="View journal workflow configuration (Chief Editor or System Admin)",
)
def get_workflow_config(
    journal_id: int,
    _actor: User = Depends(require_journal_roles(JournalRole.CHIEF_EDITOR)),
    db: Session = Depends(get_db),
) -> JournalWorkflowConfigResponse:
    """Retrieve a journal's editorial workflow rules and SLA deadlines."""
    config = journal_service.get_workflow_config(db, journal_id)
    return JournalWorkflowConfigResponse.model_validate(config)


@router.patch(
    "/{journal_id}/workflow-config",
    response_model=JournalWorkflowConfigResponse,
    summary="Update journal workflow configuration (Chief Editor or System Admin)",
)
def update_workflow_config(
    journal_id: int,
    payload: JournalWorkflowConfigUpdateRequest,
    _actor: User = Depends(require_journal_roles(JournalRole.CHIEF_EDITOR)),
    db: Session = Depends(get_db),
) -> JournalWorkflowConfigResponse:
    """Update anonymity mode, minimum reviewers, stage gates, and SLA deadlines."""
    config = journal_service.update_workflow_config(db, journal_id, payload)
    return JournalWorkflowConfigResponse.model_validate(config)


@router.get(
    "/{journal_id}/members",
    response_model=PaginatedResponse[JournalMemberResponse],
    summary="List journal members (Chief Editor or System Admin)",
)
def list_journal_members(
    journal_id: int,
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
    role: JournalRole | None = Query(
        default=None,
        description="Optional filter by per-journal role.",
    ),
    _actor: User = Depends(require_journal_roles(JournalRole.CHIEF_EDITOR)),
    db: Session = Depends(get_db),
) -> PaginatedResponse[JournalMemberResponse]:
    """List role assignments for a specific journal, optionally filtered by role."""
    items, total = journal_service.list_journal_members_paginated(
        db,
        journal_id=journal_id,
        page=page,
        page_size=page_size,
        role=role,
    )
    return PaginatedResponse[JournalMemberResponse](
        page=page,
        page_size=page_size,
        total=total,
        items=[JournalMemberResponse.model_validate(m) for m in items],
    )


@router.post(
    "/{journal_id}/members",
    response_model=JournalMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a per-journal role (Chief Editor or System Admin)",
)
def assign_journal_member(
    journal_id: int,
    payload: JournalMemberAssignRequest,
    actor: User = Depends(require_journal_roles(JournalRole.CHIEF_EDITOR)),
    db: Session = Depends(get_db),
) -> JournalMemberResponse:
    """Grant a user a role within this specific journal."""
    membership = journal_service.assign_journal_member(
        db,
        journal_id=journal_id,
        payload=payload,
        acting_user=actor,
    )
    return JournalMemberResponse.model_validate(membership)


@router.delete(
    "/{journal_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a per-journal role (Chief Editor or System Admin)",
)
def revoke_journal_member(
    journal_id: int,
    membership_id: int,
    _actor: User = Depends(require_journal_roles(JournalRole.CHIEF_EDITOR)),
    db: Session = Depends(get_db),
) -> Response:
    """Revoke a specific role assignment within this journal."""
    journal_service.revoke_journal_member(
        db,
        journal_id=journal_id,
        membership_id=membership_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{journal_id}/manuscripts",
    response_model=PaginatedResponse[ManuscriptResponse],
    summary="View journal editorial manuscript queue (Chief Editor, Handling Editor, or System Admin)",
)
def list_journal_manuscripts(
    journal_id: int,
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
    status_filter: ManuscriptStatus | None = Query(
        default=None,
        alias="status",
        description="Optional filter by workflow status.",
    ),
    assigned_editor_id: int | None = Query(
        default=None,
        ge=1,
        description="Optional filter by assigned Handling Editor ID (Chief Editor / System Admin only).",
    ),
    actor: User = Depends(
        require_journal_roles(JournalRole.CHIEF_EDITOR, JournalRole.HANDLING_EDITOR)
    ),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ManuscriptResponse]:
    """Return a paginated editorial queue of submitted manuscripts in this journal.

    Chief Editors and System Admins see all non-draft manuscripts in the journal;
    Handling Editors automatically see only manuscripts assigned to themselves.
    """
    items, total = workflow_service.list_journal_manuscripts_paginated(
        db,
        journal_id=journal_id,
        current_user=actor,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        assigned_editor_id=assigned_editor_id,
    )
    return PaginatedResponse[ManuscriptResponse](
        page=page,
        page_size=page_size,
        total=total,
        items=[ManuscriptResponse.model_validate(m) for m in items],
    )
