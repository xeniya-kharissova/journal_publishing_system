"""Business logic for manuscript drafts, co-authors, versioned PDFs, and download RBAC."""

import io
import re
from pathlib import PurePath
from uuid import uuid4

from fastapi import UploadFile
from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.adapters.storage import StorageAdapter
from app.core.config import Settings
from app.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.models.journal import AnonymityMode, JournalRole
from app.models.manuscript import (
    Manuscript,
    ManuscriptAuthor,
    ManuscriptStatus,
    ManuscriptVersion,
)
from app.models.review import ReviewInvitation, ReviewInvitationStatus
from app.models.user import User
from app.schemas.manuscript import (
    ManuscriptAuthorInput,
    ManuscriptCreateRequest,
    ManuscriptResponse,
    ManuscriptUpdateRequest,
    ManuscriptVersionResponse,
)
from app.services import journal_service

ALLOWED_PDF_MIME_TYPES = frozenset({"application/pdf", "application/x-pdf"})
_PDF_MAGIC_PREFIX = b"%PDF-"
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def extract_pdf_text(data: bytes) -> str:
    """Extract plain text from a PDF byte stream, degrading gracefully on unreadable PDFs."""
    try:
        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text.strip())
        return "\n\n".join(parts).strip()
    except Exception:
        return ""


def _sanitize_original_filename(raw_filename: str | None) -> str:
    """Strip directory components and unsafe characters from an uploaded filename."""
    if not raw_filename:
        return "manuscript.pdf"
    base = PurePath(raw_filename.replace("\\", "/")).name
    cleaned = _FILENAME_SAFE_RE.sub("_", base).strip(" ._")
    if not cleaned:
        return "manuscript.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned[:255]


def _validate_co_author_users(db: Session, co_authors: list[ManuscriptAuthorInput]) -> None:
    """Ensure any optional user_id referenced on a co-author exists."""
    user_ids = {author.user_id for author in co_authors if author.user_id is not None}
    if not user_ids:
        return
    existing_ids = set(db.scalars(select(User.id).where(User.id.in_(user_ids))).all())
    missing = sorted(user_ids - existing_ids)
    if missing:
        raise NotFoundError(
            f"Referenced co-author user(s) not found: {missing}.",
            code="co_author_user_not_found",
            details={"missing_user_ids": missing},
        )


def _build_co_author_models(co_authors: list[ManuscriptAuthorInput]) -> list[ManuscriptAuthor]:
    """Convert validated co-author inputs into ordered ManuscriptAuthor ORM entities."""
    return [
        ManuscriptAuthor(
            author_order=index,
            full_name=author.full_name,
            email=author.email,
            affiliation=author.affiliation,
            orcid=author.orcid,
            is_corresponding=author.is_corresponding,
            user_id=author.user_id,
        )
        for index, author in enumerate(co_authors, start=1)
    ]


def get_manuscript_or_404(db: Session, manuscript_id: int) -> Manuscript:
    """Fetch a manuscript with its ordered co-authors or raise 404."""
    manuscript = db.scalar(
        select(Manuscript)
        .options(selectinload(Manuscript.co_authors))
        .where(Manuscript.id == manuscript_id)
    )
    if manuscript is None:
        raise NotFoundError(
            f"Manuscript {manuscript_id} was not found.",
            code="manuscript_not_found",
            details={"manuscript_id": manuscript_id},
        )
    return manuscript


def has_editorial_access(db: Session, *, manuscript: Manuscript, user: User) -> bool:
    """Return True if user is System Admin, journal Chief Editor, or assigned Handling Editor."""
    if user.is_system_admin:
        return True
    if journal_service.has_journal_role(
        db,
        user=user,
        journal_id=manuscript.journal_id,
        allowed_roles=[JournalRole.CHIEF_EDITOR],
    ):
        return True
    return manuscript.assigned_editor_id == user.id and journal_service.has_journal_role(
        db,
        user=user,
        journal_id=manuscript.journal_id,
        allowed_roles=[JournalRole.HANDLING_EDITOR, JournalRole.CHIEF_EDITOR],
    )


def is_accepted_reviewer(db: Session, *, manuscript_id: int, user_id: int) -> bool:
    """Return True if user holds an accepted or completed review invitation for this manuscript."""
    invitation_id = db.scalar(
        select(ReviewInvitation.id).where(
            ReviewInvitation.manuscript_id == manuscript_id,
            ReviewInvitation.reviewer_id == user_id,
            ReviewInvitation.status.in_(
                [
                    ReviewInvitationStatus.ACCEPTED.value,
                    ReviewInvitationStatus.COMPLETED.value,
                ]
            ),
        )
    )
    return invitation_id is not None


def should_mask_author_identity(db: Session, *, manuscript: Manuscript, user: User) -> bool:
    """Return True when the viewer is a reviewer under double_anonymous mode."""
    if has_editorial_access(db, manuscript=manuscript, user=user):
        return False
    if manuscript.submitter_id == user.id:
        return False
    config = journal_service.get_workflow_config(db, manuscript.journal_id)
    return config.anonymity_mode == AnonymityMode.DOUBLE_ANONYMOUS.value


def can_access_manuscript(db: Session, *, manuscript: Manuscript, user: User) -> bool:
    """Return True if user is authorized to inspect or download the manuscript."""
    if has_editorial_access(db, manuscript=manuscript, user=user):
        return True
    if manuscript.submitter_id == user.id:
        return True
    return is_accepted_reviewer(db, manuscript_id=manuscript.id, user_id=user.id)


def project_manuscript_for_user(
    db: Session,
    *,
    manuscript: Manuscript,
    current_user: User,
) -> ManuscriptResponse:
    """Return a role- and anonymity-aware ManuscriptResponse for an authorized viewer."""
    response = ManuscriptResponse.model_validate(manuscript)
    if should_mask_author_identity(db, manuscript=manuscript, user=current_user):
        return response.model_copy(update={"submitter_id": None, "co_authors": []})
    return response


def project_versions_for_user(
    db: Session,
    *,
    manuscript: Manuscript,
    versions: list[ManuscriptVersion],
    current_user: User,
) -> list[ManuscriptVersionResponse]:
    """Return anonymity-aware version metadata (stripping uploader ID in double-anonymous mode)."""
    responses = [ManuscriptVersionResponse.model_validate(v) for v in versions]
    if should_mask_author_identity(db, manuscript=manuscript, user=current_user):
        return [item.model_copy(update={"uploaded_by_id": None}) for item in responses]
    return responses


def _require_manuscript_access(db: Session, *, manuscript: Manuscript, user: User) -> None:
    if not can_access_manuscript(db, manuscript=manuscript, user=user):
        raise ForbiddenError(
            "You do not have permission to access this manuscript.",
            code="manuscript_access_forbidden",
            details={"manuscript_id": manuscript.id},
        )


def create_manuscript_draft(
    db: Session,
    *,
    payload: ManuscriptCreateRequest,
    current_user: User,
) -> Manuscript:
    """Create a new manuscript draft with ordered co-authors in an active journal."""
    journal = journal_service.get_journal_or_404(db, payload.journal_id)
    if not journal.is_active:
        raise BadRequestError(
            f"Journal {journal.id} is inactive and cannot accept new submissions.",
            code="journal_inactive",
            details={"journal_id": journal.id},
        )

    _validate_co_author_users(db, payload.co_authors)

    manuscript = Manuscript(
        journal_id=journal.id,
        submitter_id=current_user.id,
        title=payload.title,
        abstract=payload.abstract,
        keywords=payload.keywords,
        subject_area=payload.subject_area,
        status=ManuscriptStatus.DRAFT.value,
        current_version_number=0,
        current_review_round=0,
    )
    manuscript.co_authors = _build_co_author_models(payload.co_authors)

    db.add(manuscript)
    db.commit()
    return get_manuscript_or_404(db, manuscript.id)


def update_manuscript_draft(
    db: Session,
    *,
    manuscript_id: int,
    payload: ManuscriptUpdateRequest,
    current_user: User,
) -> Manuscript:
    """Update metadata and/or ordered co-authors of a draft manuscript by its submitter."""
    manuscript = get_manuscript_or_404(db, manuscript_id)

    if manuscript.submitter_id != current_user.id:
        raise ForbiddenError(
            "Only the submitting author can edit this manuscript.",
            code="manuscript_edit_forbidden",
            details={"manuscript_id": manuscript_id},
        )

    if manuscript.status != ManuscriptStatus.DRAFT.value:
        raise ConflictError(
            f"Manuscript cannot be edited while in '{manuscript.status}' status.",
            code="manuscript_not_editable",
            details={"manuscript_id": manuscript_id, "status": manuscript.status},
        )

    provided = payload.model_fields_set

    if "title" in provided:
        if payload.title is None:
            raise BadRequestError("title cannot be null.", code="invalid_title")
        manuscript.title = payload.title

    if "abstract" in provided:
        if payload.abstract is None:
            raise BadRequestError("abstract cannot be null.", code="invalid_abstract")
        manuscript.abstract = payload.abstract

    if "keywords" in provided:
        if payload.keywords is None:
            raise BadRequestError("keywords cannot be null.", code="invalid_keywords")
        manuscript.keywords = payload.keywords

    if "subject_area" in provided:
        manuscript.subject_area = payload.subject_area

    if "co_authors" in provided:
        if payload.co_authors is None:
            raise BadRequestError("co_authors cannot be null.", code="invalid_co_authors")
        _validate_co_author_users(db, payload.co_authors)
        manuscript.co_authors.clear()
        db.flush()
        manuscript.co_authors.extend(_build_co_author_models(payload.co_authors))

    db.add(manuscript)
    db.commit()
    return get_manuscript_or_404(db, manuscript.id)


def list_my_manuscripts_paginated(
    db: Session,
    *,
    current_user: User,
    page: int,
    page_size: int,
    journal_id: int | None = None,
    status_filter: ManuscriptStatus | None = None,
) -> tuple[list[Manuscript], int]:
    """Return paginated submissions owned by the authenticated author."""
    query = select(Manuscript).where(Manuscript.submitter_id == current_user.id)
    if journal_id is not None:
        query = query.where(Manuscript.journal_id == journal_id)
    if status_filter is not None:
        query = query.where(Manuscript.status == status_filter.value)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(
            query.options(selectinload(Manuscript.co_authors))
            .order_by(Manuscript.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, int(total)


def get_manuscript_for_user(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
) -> Manuscript:
    """Return manuscript details if the authenticated user is authorized to view it."""
    manuscript = get_manuscript_or_404(db, manuscript_id)
    _require_manuscript_access(db, manuscript=manuscript, user=current_user)
    return manuscript


def get_manuscript_response_for_user(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
) -> ManuscriptResponse:
    """Return anonymity-enforced manuscript details for an authorized viewer."""
    manuscript = get_manuscript_for_user(
        db,
        manuscript_id=manuscript_id,
        current_user=current_user,
    )
    return project_manuscript_for_user(db, manuscript=manuscript, current_user=current_user)


def list_manuscript_versions_for_user(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
) -> list[ManuscriptVersion]:
    """Return ordered version history for a manuscript if authorized."""
    manuscript = get_manuscript_or_404(db, manuscript_id)
    _require_manuscript_access(db, manuscript=manuscript, user=current_user)

    return list(
        db.scalars(
            select(ManuscriptVersion)
            .where(ManuscriptVersion.manuscript_id == manuscript.id)
            .order_by(ManuscriptVersion.version_number.asc())
        ).all()
    )


def list_manuscript_version_responses_for_user(
    db: Session,
    *,
    manuscript_id: int,
    current_user: User,
) -> list[ManuscriptVersionResponse]:
    """Return anonymity-enforced version history for an authorized viewer."""
    manuscript = get_manuscript_or_404(db, manuscript_id)
    _require_manuscript_access(db, manuscript=manuscript, user=current_user)
    versions = list(
        db.scalars(
            select(ManuscriptVersion)
            .where(ManuscriptVersion.manuscript_id == manuscript.id)
            .order_by(ManuscriptVersion.version_number.asc())
        ).all()
    )
    return project_versions_for_user(
        db,
        manuscript=manuscript,
        versions=versions,
        current_user=current_user,
    )


def upload_manuscript_version(
    db: Session,
    *,
    manuscript_id: int,
    file: UploadFile,
    current_user: User,
    storage: StorageAdapter,
    settings: Settings,
    response_to_reviewers: str | None = None,
) -> ManuscriptVersion:
    """Validate, store, extract text from, and record a new manuscript PDF version."""
    manuscript = get_manuscript_or_404(db, manuscript_id)

    if manuscript.submitter_id != current_user.id:
        raise ForbiddenError(
            "Only the submitting author can upload manuscript versions.",
            code="manuscript_upload_forbidden",
            details={"manuscript_id": manuscript_id},
        )

    allowed_upload_statuses = {
        ManuscriptStatus.DRAFT.value,
        ManuscriptStatus.REVISION_REQUESTED.value,
    }
    if manuscript.status not in allowed_upload_statuses:
        raise ConflictError(
            f"Cannot upload a new manuscript version while in '{manuscript.status}' status.",
            code="manuscript_upload_not_allowed",
            details={"manuscript_id": manuscript_id, "status": manuscript.status},
        )

    raw_content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if raw_content_type not in ALLOWED_PDF_MIME_TYPES:
        raise UnsupportedMediaTypeError(
            "Only PDF files (application/pdf) are accepted.",
            code="invalid_file_type",
            details={"content_type": file.content_type},
        )

    max_bytes = settings.max_upload_size_bytes
    data = file.file.read(max_bytes + 1)
    if not data:
        raise BadRequestError(
            "Uploaded PDF file is empty.",
            code="empty_file",
        )
    if len(data) > max_bytes:
        raise PayloadTooLargeError(
            f"Uploaded file exceeds the maximum allowed size of {max_bytes} bytes.",
            code="file_too_large",
            details={"max_upload_size_bytes": max_bytes},
        )
    if not data.startswith(_PDF_MAGIC_PREFIX):
        raise BadRequestError(
            "Uploaded file does not have a valid PDF signature (%PDF-).",
            code="invalid_pdf_signature",
        )

    original_filename = _sanitize_original_filename(file.filename)
    next_version = manuscript.current_version_number + 1
    file_key = f"manuscripts/{manuscript.id}/v{next_version}_{uuid4().hex}.pdf"
    extracted_text = extract_pdf_text(data)

    canonical_key = storage.save_file(file_key, data)

    cleaned_response = (
        response_to_reviewers.strip() if response_to_reviewers and response_to_reviewers.strip() else None
    )
    version = ManuscriptVersion(
        manuscript_id=manuscript.id,
        version_number=next_version,
        file_key=canonical_key,
        original_filename=original_filename,
        content_type="application/pdf",
        file_size_bytes=len(data),
        extracted_text=extracted_text,
        response_to_reviewers=cleaned_response,
        uploaded_by_id=current_user.id,
    )
    manuscript.current_version_number = next_version

    db.add(version)
    db.add(manuscript)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete_file(canonical_key)
        raise

    db.refresh(version)
    return version


def download_manuscript_version_for_user(
    db: Session,
    *,
    manuscript_id: int,
    version_number: int,
    current_user: User,
    storage: StorageAdapter,
) -> tuple[ManuscriptVersion, bytes]:
    """Authorize and read a specific manuscript PDF version from storage."""
    manuscript = get_manuscript_or_404(db, manuscript_id)
    _require_manuscript_access(db, manuscript=manuscript, user=current_user)

    version = db.scalar(
        select(ManuscriptVersion).where(
            ManuscriptVersion.manuscript_id == manuscript.id,
            ManuscriptVersion.version_number == version_number,
        )
    )
    if version is None:
        raise NotFoundError(
            f"Version v{version_number} was not found for manuscript {manuscript_id}.",
            code="manuscript_version_not_found",
            details={"manuscript_id": manuscript_id, "version_number": version_number},
        )

    try:
        pdf_bytes = storage.read_file(version.file_key)
    except FileNotFoundError as exc:
        raise NotFoundError(
            f"Stored PDF file for manuscript {manuscript_id} version v{version_number} is missing.",
            code="manuscript_file_missing",
            details={"manuscript_id": manuscript_id, "version_number": version_number},
        ) from exc

    return version, pdf_bytes
