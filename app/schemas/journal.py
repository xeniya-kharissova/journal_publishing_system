"""Pydantic schemas for journals, workflow configuration, and per-journal RBAC."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.journal import AnonymityMode, JournalRole

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


def _clean_keywords(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item = raw.strip()
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


class JournalWorkflowConfigResponse(BaseModel):
    """Editorial workflow configuration and SLA policy for a journal."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    journal_id: int
    anonymity_mode: AnonymityMode
    min_reviewers: int
    require_desk_review: bool
    require_plagiarism_check: bool
    desk_review_sla_days: int
    review_sla_days: int
    decision_sla_days: int
    revision_sla_days: int
    created_at: datetime
    updated_at: datetime


class JournalWorkflowConfigUpdateRequest(BaseModel):
    """Partial update payload for a journal's workflow configuration."""

    anonymity_mode: AnonymityMode | None = None
    min_reviewers: int | None = Field(default=None, ge=1, le=20)
    require_desk_review: bool | None = None
    require_plagiarism_check: bool | None = None
    desk_review_sla_days: int | None = Field(default=None, ge=1, le=365)
    review_sla_days: int | None = Field(default=None, ge=1, le=365)
    decision_sla_days: int | None = Field(default=None, ge=1, le=365)
    revision_sla_days: int | None = Field(default=None, ge=1, le=365)


class JournalCreateRequest(BaseModel):
    """Payload for creating a new scholarly journal (System Admin only)."""

    title: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100)
    issn: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=4000)
    scope_keywords: list[str] = Field(default_factory=list, max_length=50)
    publisher_name: str | None = Field(default=None, max_length=255)
    doi_prefix: str = Field(default="10.9999", min_length=4, max_length=64)
    apc_enabled: bool = False
    apc_amount_cents: int = Field(default=0, ge=0, le=100_000_000)
    apc_currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SLUG_PATTERN.match(normalized):
            raise ValueError(
                "Slug must contain only lowercase letters, numbers, and single hyphens."
            )
        return normalized

    @field_validator("apc_currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _CURRENCY_PATTERN.match(normalized):
            raise ValueError("apc_currency must be a 3-letter ISO currency code (e.g., USD).")
        return normalized

    @field_validator("scope_keywords")
    @classmethod
    def _validate_keywords(cls, value: list[str]) -> list[str]:
        return _clean_keywords(value) or []


class JournalUpdateRequest(BaseModel):
    """Payload for updating or deactivating a journal (System Admin only)."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=100)
    issn: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=4000)
    scope_keywords: list[str] | None = Field(default=None, max_length=50)
    publisher_name: str | None = Field(default=None, max_length=255)
    doi_prefix: str | None = Field(default=None, min_length=4, max_length=64)
    apc_enabled: bool | None = None
    apc_amount_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    apc_currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = None

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _SLUG_PATTERN.match(normalized):
            raise ValueError(
                "Slug must contain only lowercase letters, numbers, and single hyphens."
            )
        return normalized

    @field_validator("apc_currency")
    @classmethod
    def _validate_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not _CURRENCY_PATTERN.match(normalized):
            raise ValueError("apc_currency must be a 3-letter ISO currency code (e.g., USD).")
        return normalized

    @field_validator("scope_keywords")
    @classmethod
    def _validate_keywords(cls, value: list[str] | None) -> list[str] | None:
        return _clean_keywords(value)


class JournalResponse(BaseModel):
    """Public and administrative representation of a scholarly journal."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    issn: str | None
    description: str | None
    scope_keywords: list[str]
    publisher_name: str | None
    doi_prefix: str
    apc_enabled: bool
    apc_amount_cents: int
    apc_currency: str
    is_active: bool
    workflow_config: JournalWorkflowConfigResponse
    created_at: datetime
    updated_at: datetime


class JournalMemberAssignRequest(BaseModel):
    """Payload for assigning a per-journal role to a user."""

    user_id: int = Field(..., ge=1)
    role: JournalRole


class JournalMemberUserSummary(BaseModel):
    """Minimal user metadata embedded in journal membership listings."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    affiliation: str | None
    is_active: bool


class JournalMemberResponse(BaseModel):
    """Per-journal role assignment details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    journal_id: int
    user_id: int
    role: JournalRole
    assigned_by_id: int | None
    created_at: datetime
    user: JournalMemberUserSummary
