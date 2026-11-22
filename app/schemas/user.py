"""User profile and System Admin user management schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserProfileResponse(BaseModel):
    """Public/authenticated representation of a user profile (excludes password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    affiliation: str | None
    bio: str | None
    orcid: str | None
    expertise_keywords: list[str]
    max_active_reviews: int
    is_system_admin: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserProfileUpdateRequest(BaseModel):
    """Fields an authenticated user may update on their own profile."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    affiliation: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=4000)
    orcid: str | None = Field(default=None, max_length=32)
    expertise_keywords: list[str] | None = Field(default=None, max_length=50)
    max_active_reviews: int | None = Field(default=None, ge=0, le=50)

    @field_validator("expertise_keywords")
    @classmethod
    def _clean_keywords(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw_item in value:
            item = raw_item.strip()
            if not item:
                continue
            key = item.lower()
            if key not in seen:
                seen.add(key)
                cleaned.append(item)
        return cleaned


class AdminUserStatusUpdateRequest(BaseModel):
    """Payload for System Admin account activation/deactivation."""

    is_active: bool
