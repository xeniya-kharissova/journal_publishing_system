"""Manuscript, ordered co-author, and versioned PDF ORM entities."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.journal import Journal
from app.models.user import User

if TYPE_CHECKING:
    from app.models.review import Review, ReviewInvitation


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ManuscriptStatus(StrEnum):
    """Editorial workflow lifecycle states for a manuscript submission."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    DESK_REVIEW = "desk_review"
    UNDER_REVIEW = "under_review"
    REVISION_REQUESTED = "revision_requested"
    ACCEPTED = "accepted"
    PRODUCTION = "production"
    PUBLISHED = "published"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class Manuscript(Base):
    """Scholarly manuscript submission belonging to a specific journal."""

    __tablename__ = "manuscripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[int] = mapped_column(
        ForeignKey("journals.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    submitter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    assigned_editor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    abstract: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    subject_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        index=True,
        nullable=False,
        default=ManuscriptStatus.DRAFT.value,
        server_default=ManuscriptStatus.DRAFT.value,
    )
    current_version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    current_review_round: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    stage_entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    doi: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    page_range: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    journal: Mapped[Journal] = relationship("Journal", foreign_keys=[journal_id])
    submitter: Mapped[User] = relationship("User", foreign_keys=[submitter_id])
    assigned_editor: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[assigned_editor_id],
    )
    co_authors: Mapped[list["ManuscriptAuthor"]] = relationship(
        "ManuscriptAuthor",
        back_populates="manuscript",
        cascade="all, delete-orphan",
        order_by="ManuscriptAuthor.author_order.asc()",
    )
    versions: Mapped[list["ManuscriptVersion"]] = relationship(
        "ManuscriptVersion",
        back_populates="manuscript",
        cascade="all, delete-orphan",
        order_by="ManuscriptVersion.version_number.asc()",
    )
    status_history: Mapped[list["ManuscriptStatusHistory"]] = relationship(
        "ManuscriptStatusHistory",
        back_populates="manuscript",
        cascade="all, delete-orphan",
        order_by="ManuscriptStatusHistory.id.asc()",
    )
    review_invitations: Mapped[list["ReviewInvitation"]] = relationship(
        "ReviewInvitation",
        back_populates="manuscript",
        cascade="all, delete-orphan",
        order_by="ReviewInvitation.id.asc()",
    )
    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="manuscript",
        cascade="all, delete-orphan",
        order_by="Review.id.asc()",
    )


class ManuscriptAuthor(Base):
    """Ordered co-author metadata attached to a manuscript."""

    __tablename__ = "manuscript_authors"
    __table_args__ = (
        UniqueConstraint(
            "manuscript_id",
            "author_order",
            name="uq_manuscript_authors_manuscript_order",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manuscript_id: Mapped[int] = mapped_column(
        ForeignKey("manuscripts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    author_order: Mapped[int] = mapped_column(Integer, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    affiliation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    orcid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_corresponding: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    manuscript: Mapped[Manuscript] = relationship("Manuscript", back_populates="co_authors")
    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id])


class ManuscriptVersion(Base):
    """Immutable uploaded manuscript PDF version with locally extracted plain text."""

    __tablename__ = "manuscript_versions"
    __table_args__ = (
        UniqueConstraint(
            "manuscript_id",
            "version_number",
            name="uq_manuscript_versions_manuscript_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manuscript_id: Mapped[int] = mapped_column(
        ForeignKey("manuscripts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    extracted_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    response_to_reviewers: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    manuscript: Mapped[Manuscript] = relationship("Manuscript", back_populates="versions")
    uploaded_by: Mapped[User | None] = relationship("User", foreign_keys=[uploaded_by_id])

    @property
    def extracted_text_length(self) -> int:
        """Return character count of locally extracted PDF text."""
        return len(self.extracted_text or "")


class ManuscriptStatusHistory(Base):
    """Immutable audit log recording every workflow state transition on a manuscript."""

    __tablename__ = "manuscript_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manuscript_id: Mapped[int] = mapped_column(
        ForeignKey("manuscripts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    manuscript: Mapped[Manuscript] = relationship("Manuscript", back_populates="status_history")
    changed_by: Mapped[User | None] = relationship("User", foreign_keys=[changed_by_id])
