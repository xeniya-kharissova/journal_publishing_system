"""Formal editorial decision ORM entity."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import User

if TYPE_CHECKING:
    from app.models.manuscript import Manuscript


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EditorialDecisionType(StrEnum):
    """Formal editorial decisions available for a manuscript under review."""

    ACCEPT = "accept"
    MINOR_REVISION = "minor_revision"
    MAJOR_REVISION = "major_revision"
    REJECT = "reject"


class EditorialDecision(Base):
    """Formal editorial decision recorded for a manuscript review round."""

    __tablename__ = "editorial_decisions"
    __table_args__ = (
        UniqueConstraint(
            "manuscript_id",
            "review_round",
            name="uq_editorial_decisions_manuscript_round",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manuscript_id: Mapped[int] = mapped_column(
        ForeignKey("manuscripts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    review_round: Mapped[int] = mapped_column(Integer, nullable=False)
    manuscript_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    decided_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_letter: Mapped[str] = mapped_column(Text, nullable=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    manuscript: Mapped["Manuscript"] = relationship(
        "Manuscript",
        back_populates="decisions",
    )
    decided_by: Mapped[User | None] = relationship("User", foreign_keys=[decided_by_id])
