"""Pydantic schemas for peer-review invitations and structured reviews."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.review import ReviewInvitationStatus, ReviewRecommendation


class ReviewInvitationCreateRequest(BaseModel):
    """Payload for inviting a journal reviewer to evaluate a manuscript."""

    reviewer_id: int = Field(..., ge=1)
    due_at: datetime | None = Field(
        default=None,
        description="Optional review deadline (UTC ISO-8601). Defaults to journal review_sla_days from now.",
    )


class ReviewInvitationDeclineRequest(BaseModel):
    """Optional decline reason provided by an invited reviewer."""

    decline_reason: str | None = Field(default=None, max_length=4000)

    @field_validator("decline_reason")
    @classmethod
    def _clean_decline_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ReviewInvitationResponse(BaseModel):
    """Peer-review invitation payload (never exposes author identities)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    manuscript_id: int
    manuscript_title: str
    journal_id: int
    reviewer_id: int
    reviewer_name: str | None = None
    reviewer_email: str | None = None
    review_round: int
    status: ReviewInvitationStatus
    invited_by_id: int | None
    due_at: datetime
    responded_at: datetime | None
    decline_reason: str | None
    created_at: datetime
    updated_at: datetime


class ReviewCreateRequest(BaseModel):
    """Structured peer-review evaluation payload submitted by an accepted reviewer."""

    originality_score: int = Field(..., ge=1, le=5)
    methodology_score: int = Field(..., ge=1, le=5)
    clarity_score: int = Field(..., ge=1, le=5)
    significance_score: int = Field(..., ge=1, le=5)
    recommendation: ReviewRecommendation
    comments_to_author: str = Field(..., min_length=1, max_length=20000)
    confidential_comments_to_editor: str | None = Field(default=None, max_length=20000)

    @field_validator("comments_to_author")
    @classmethod
    def _validate_comments_to_author(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("comments_to_author cannot be blank.")
        return stripped

    @field_validator("confidential_comments_to_editor")
    @classmethod
    def _clean_confidential_comments(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ReviewResponse(BaseModel):
    """Role- and anonymity-aware peer-review payload."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    invitation_id: int
    manuscript_id: int
    manuscript_version_id: int
    review_round: int
    reviewer_label: str
    reviewer_id: int | None = None
    reviewer_name: str | None = None
    reviewer_email: str | None = None
    reviewer_affiliation: str | None = None
    originality_score: int
    methodology_score: int
    clarity_score: int
    significance_score: int
    recommendation: ReviewRecommendation
    comments_to_author: str
    confidential_comments_to_editor: str | None = None
    submitted_at: datetime
