"""Journal, per-journal RBAC membership, and workflow configuration ORM entities."""

from datetime import UTC, datetime
from enum import StrEnum

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
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JournalRole(StrEnum):
    """Supported per-journal RBAC roles."""

    CHIEF_EDITOR = "chief_editor"
    HANDLING_EDITOR = "handling_editor"
    REVIEWER = "reviewer"
    AUTHOR = "author"


class AnonymityMode(StrEnum):
    """Peer-review anonymity modes supported by a journal."""

    DOUBLE_ANONYMOUS = "double_anonymous"
    SINGLE_ANONYMOUS = "single_anonymous"
    OPEN = "open"


class Journal(Base):
    """Independent scholarly journal hosted on the platform."""

    __tablename__ = "journals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    issn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    publisher_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    doi_prefix: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="10.9999",
        server_default="10.9999",
    )
    apc_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    apc_amount_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    apc_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
        server_default="USD",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
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

    workflow_config: Mapped["JournalWorkflowConfig"] = relationship(
        "JournalWorkflowConfig",
        back_populates="journal",
        uselist=False,
        cascade="all, delete-orphan",
    )
    memberships: Mapped[list["JournalMembership"]] = relationship(
        "JournalMembership",
        back_populates="journal",
        cascade="all, delete-orphan",
    )


class JournalWorkflowConfig(Base):
    """Per-journal editorial workflow rules, quality gates, and SLA thresholds."""

    __tablename__ = "journal_workflow_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[int] = mapped_column(
        ForeignKey("journals.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    anonymity_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AnonymityMode.DOUBLE_ANONYMOUS.value,
        server_default=AnonymityMode.DOUBLE_ANONYMOUS.value,
    )
    min_reviewers: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
        server_default="2",
    )
    require_desk_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    require_plagiarism_check: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    desk_review_sla_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=7,
        server_default="7",
    )
    review_sla_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=21,
        server_default="21",
    )
    decision_sla_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=14,
        server_default="14",
    )
    revision_sla_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
    )
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

    journal: Mapped[Journal] = relationship("Journal", back_populates="workflow_config")


class JournalMembership(Base):
    """Per-journal role assignment linking a user to a journal with a specific role."""

    __tablename__ = "journal_memberships"
    __table_args__ = (
        UniqueConstraint(
            "journal_id",
            "user_id",
            "role",
            name="uq_journal_memberships_journal_user_role",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[int] = mapped_column(
        ForeignKey("journals.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    journal: Mapped[Journal] = relationship("Journal", back_populates="memberships")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
