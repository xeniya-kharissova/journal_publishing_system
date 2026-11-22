"""Peer-review invitation and structured review ORM entities."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import User

if TYPE_CHECKING:
    from app.models.manuscript import Manuscript, ManuscriptVersion


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ReviewInvitationStatus(StrEnum):
    """Lifecycle states of a peer-review invitation."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    COMPLETED = "completed"
    EXPIRED = "expired"


class ReviewRecommendation(StrEnum):
    """Structured editorial recommendation submitted by a peer reviewer."""

    ACCEPT = "accept"
    MINOR_REVISION = "minor_revision"
    MAJOR_REVISION = "major_revision"
    REJECT = "reject"


class ReviewInvitation(Base):
    """Invitation sent by an editor to a journal reviewer for a specific review round."""

    __tablename__ = "review_invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manuscript_id: Mapped[int] = mapped_column(
        ForeignKey("manuscripts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    reviewer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    review_round: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        index=True,
        nullable=False,
        default=ReviewInvitationStatus.PENDING.value,
        server_default=ReviewInvitationStatus.PENDING.value,
    )
    invited_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    manuscript: Mapped["Manuscript"] = relationship(
        "Manuscript",
        back_populates="review_invitations",
    )
    reviewer: Mapped[User] = relationship("User", foreign_keys=[reviewer_id])
    invited_by: Mapped[User | None] = relationship("User", foreign_keys=[invited_by_id])
    review: Mapped["Review | None"] = relationship(
        "Review",
        back_populates="invitation",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Review(Base):
    """Structured peer-review evaluation submitted for an accepted review invitation."""

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint(
            "originality_score >= 1 AND originality_score <= 5",
            name="ck_reviews_originality_score_range",
        ),
        CheckConstraint(
            "methodology_score >= 1 AND methodology_score <= 5",
            name="ck_reviews_methodology_score_range",
        ),
        CheckConstraint(
            "clarity_score >= 1 AND clarity_score <= 5",
            name="ck_reviews_clarity_score_range",
        ),
        CheckConstraint(
            "significance_score >= 1 AND significance_score <= 5",
            name="ck_reviews_significance_score_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invitation_id: Mapped[int] = mapped_column(
        ForeignKey("review_invitations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    manuscript_id: Mapped[int] = mapped_column(
        ForeignKey("manuscripts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    manuscript_version_id: Mapped[int] = mapped_column(
        ForeignKey("manuscript_versions.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    reviewer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    review_round: Mapped[int] = mapped_column(Integer, nullable=False)
    originality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    methodology_score: Mapped[int] = mapped_column(Integer, nullable=False)
    clarity_score: Mapped[int] = mapped_column(Integer, nullable=False)
    significance_score: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    comments_to_author: Mapped[str] = mapped_column(Text, nullable=False)
    confidential_comments_to_editor: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    invitation: Mapped[ReviewInvitation] = relationship(
        "ReviewInvitation",
        back_populates="review",
    )
    manuscript: Mapped["Manuscript"] = relationship(
        "Manuscript",
        back_populates="reviews",
    )
    manuscript_version: Mapped["ManuscriptVersion"] = relationship(
        "ManuscriptVersion",
        foreign_keys=[manuscript_version_id],
    )
    reviewer: Mapped[User] = relationship("User", foreign_keys=[reviewer_id])
