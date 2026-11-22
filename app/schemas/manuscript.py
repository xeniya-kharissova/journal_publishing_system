"""Pydantic schemas for manuscript drafts, ordered co-authors, and PDF versions."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.manuscript import ManuscriptStatus


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


class ManuscriptAuthorInput(BaseModel):
    """Input payload for a single ordered co-author on a manuscript."""

    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    affiliation: str | None = Field(default=None, max_length=255)
    orcid: str | None = Field(default=None, max_length=32)
    is_corresponding: bool = False
    user_id: int | None = Field(default=None, ge=1)

    @field_validator("full_name")
    @classmethod
    def _validate_full_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Co-author full_name cannot be blank.")
        return stripped

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("affiliation", "orcid")
    @classmethod
    def _clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ManuscriptAuthorResponse(BaseModel):
    """Ordered co-author entry returned with manuscript details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    author_order: int
    full_name: str
    email: str
    affiliation: str | None
    orcid: str | None
    is_corresponding: bool
    user_id: int | None
    created_at: datetime


class ManuscriptCreateRequest(BaseModel):
    """Payload for creating a new manuscript draft in an active journal."""

    journal_id: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=500)
    abstract: str = Field(..., min_length=1, max_length=20000)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    subject_area: str | None = Field(default=None, max_length=255)
    co_authors: list[ManuscriptAuthorInput] = Field(default_factory=list, max_length=100)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title cannot be blank.")
        return stripped

    @field_validator("abstract")
    @classmethod
    def _validate_abstract(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("abstract cannot be blank.")
        return stripped

    @field_validator("keywords")
    @classmethod
    def _validate_keywords(cls, value: list[str]) -> list[str]:
        cleaned = _clean_keywords(value)
        return cleaned if cleaned is not None else []

    @field_validator("subject_area")
    @classmethod
    def _clean_subject_area(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ManuscriptUpdateRequest(BaseModel):
    """Partial update payload for a manuscript currently in draft status."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    abstract: str | None = Field(default=None, min_length=1, max_length=20000)
    keywords: list[str] | None = Field(default=None, max_length=50)
    subject_area: str | None = Field(default=None, max_length=255)
    co_authors: list[ManuscriptAuthorInput] | None = Field(default=None, max_length=100)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("title cannot be blank.")
        return stripped

    @field_validator("abstract")
    @classmethod
    def _validate_abstract(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("abstract cannot be blank.")
        return stripped

    @field_validator("keywords")
    @classmethod
    def _validate_keywords(cls, value: list[str] | None) -> list[str] | None:
        return _clean_keywords(value)

    @field_validator("subject_area")
    @classmethod
    def _clean_subject_area(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ManuscriptVersionResponse(BaseModel):
    """Metadata for an uploaded immutable manuscript PDF version."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    manuscript_id: int
    version_number: int
    original_filename: str
    content_type: str
    file_size_bytes: int
    extracted_text_length: int
    response_to_reviewers: str | None
    uploaded_by_id: int | None
    created_at: datetime


class ManuscriptResponse(BaseModel):
    """Full manuscript representation with ordered co-authors."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    journal_id: int
    submitter_id: int
    assigned_editor_id: int | None
    title: str
    abstract: str
    keywords: list[str]
    subject_area: str | None
    status: ManuscriptStatus
    current_version_number: int
    current_review_round: int
    stage_entered_at: datetime
    submitted_at: datetime | None
    decided_at: datetime | None
    published_at: datetime | None
    doi: str | None
    page_range: str | None
    co_authors: list[ManuscriptAuthorResponse]
    created_at: datetime
    updated_at: datetime


class ManuscriptStatusHistoryResponse(BaseModel):
    """Immutable audit record of a single manuscript workflow transition."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    manuscript_id: int
    from_status: ManuscriptStatus
    to_status: ManuscriptStatus
    changed_by_id: int | None
    note: str | None
    created_at: datetime


class WorkflowNoteRequest(BaseModel):
    """Optional editorial or author note accompanying a workflow transition."""

    note: str | None = Field(default=None, max_length=4000)

    @field_validator("note")
    @classmethod
    def _clean_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DeskRejectRequest(BaseModel):
    """Required documented rationale for desk-rejecting a manuscript."""

    rationale: str = Field(..., min_length=1, max_length=4000)

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("rationale cannot be blank.")
        return stripped


class AssignEditorRequest(BaseModel):
    """Payload for assigning a Handling Editor to a manuscript."""

    editor_id: int = Field(..., ge=1)
