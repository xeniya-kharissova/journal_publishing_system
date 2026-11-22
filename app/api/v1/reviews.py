"""Peer-review invitation and structured review submission/inspection endpoints."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.pagination import PaginatedResponse
from app.models.review import ReviewInvitationStatus
from app.models.user import User
from app.schemas.review import (
    ReviewCreateRequest,
    ReviewInvitationCreateRequest,
    ReviewInvitationDeclineRequest,
    ReviewInvitationResponse,
    ReviewResponse,
)
from app.services import review_service

router = APIRouter(tags=["Peer Review"])


@router.post(
    "/manuscripts/{manuscript_id}/invitations",
    response_model=ReviewInvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a journal reviewer for the current review round",
)
def invite_reviewer(
    manuscript_id: int,
    payload: ReviewInvitationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewInvitationResponse:
    """Invite an eligible reviewer to evaluate a manuscript currently in under_review."""
    return review_service.invite_reviewer(
        db,
        manuscript_id=manuscript_id,
        payload=payload,
        current_user=current_user,
    )


@router.get(
    "/manuscripts/{manuscript_id}/invitations",
    response_model=list[ReviewInvitationResponse],
    summary="List all review invitations for a manuscript (editors and System Admin)",
)
def list_manuscript_invitations(
    manuscript_id: int,
    review_round: int | None = Query(
        default=None,
        ge=1,
        description="Optional filter by review round.",
    ),
    status_filter: ReviewInvitationStatus | None = Query(
        default=None,
        alias="status",
        description="Optional filter by invitation status.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReviewInvitationResponse]:
    """Return all review invitations across rounds for assigned/chief editors and System Admins."""
    return review_service.list_manuscript_invitations(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
        review_round=review_round,
        status_filter=status_filter,
    )


@router.get(
    "/manuscripts/{manuscript_id}/reviews",
    response_model=list[ReviewResponse],
    summary="List reviews for a manuscript with server-side anonymity enforcement",
)
def list_manuscript_reviews(
    manuscript_id: int,
    review_round: int | None = Query(
        default=None,
        ge=1,
        description="Optional filter by review round.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReviewResponse]:
    """Return role- and anonymity-aware peer reviews for authorized stakeholders."""
    return review_service.list_manuscript_reviews_for_user(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
        review_round=review_round,
    )


@router.get(
    "/review-invitations",
    response_model=PaginatedResponse[ReviewInvitationResponse],
    summary="List the authenticated reviewer's own review invitations",
)
def list_my_review_invitations(
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
    status_filter: ReviewInvitationStatus | None = Query(
        default=None,
        alias="status",
        description="Optional filter by invitation status.",
    ),
    manuscript_id: int | None = Query(
        default=None,
        ge=1,
        description="Optional filter by manuscript ID.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ReviewInvitationResponse]:
    """Return paginated peer-review invitations addressed to the current user."""
    items, total = review_service.list_my_invitations_paginated(
        db,
        current_user=current_user,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        manuscript_id=manuscript_id,
    )
    return PaginatedResponse[ReviewInvitationResponse](
        page=page,
        page_size=page_size,
        total=total,
        items=items,
    )


@router.get(
    "/review-invitations/{invitation_id}",
    response_model=ReviewInvitationResponse,
    summary="Inspect a single review invitation",
)
def get_review_invitation(
    invitation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewInvitationResponse:
    """Return details of a review invitation for the invited reviewer, editors, or System Admin."""
    return review_service.get_invitation_for_user(
        db,
        invitation_id=invitation_id,
        current_user=current_user,
    )


@router.post(
    "/review-invitations/{invitation_id}/accept",
    response_model=ReviewInvitationResponse,
    summary="Accept a pending review invitation",
)
def accept_review_invitation(
    invitation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewInvitationResponse:
    """Accept a pending peer-review invitation (invited reviewer only)."""
    return review_service.accept_invitation(
        db,
        invitation_id=invitation_id,
        current_user=current_user,
    )


@router.post(
    "/review-invitations/{invitation_id}/decline",
    response_model=ReviewInvitationResponse,
    summary="Decline a pending review invitation",
)
def decline_review_invitation(
    invitation_id: int,
    payload: ReviewInvitationDeclineRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewInvitationResponse:
    """Decline a pending peer-review invitation with an optional reason (invited reviewer only)."""
    return review_service.decline_invitation(
        db,
        invitation_id=invitation_id,
        decline_reason=payload.decline_reason if payload else None,
        current_user=current_user,
    )


@router.post(
    "/review-invitations/{invitation_id}/review",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a structured peer review for an accepted invitation",
)
def submit_review(
    invitation_id: int,
    payload: ReviewCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewResponse:
    """Submit numeric scores, recommendation, and comments once per accepted invitation."""
    return review_service.submit_review(
        db,
        invitation_id=invitation_id,
        payload=payload,
        current_user=current_user,
    )
