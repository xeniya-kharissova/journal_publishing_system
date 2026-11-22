"""SQLAlchemy ORM models registry."""

from app.core.database import Base
from app.models.journal import (
    AnonymityMode,
    Journal,
    JournalMembership,
    JournalRole,
    JournalWorkflowConfig,
)
from app.models.manuscript import (
    Manuscript,
    ManuscriptAuthor,
    ManuscriptStatus,
    ManuscriptStatusHistory,
    ManuscriptVersion,
)
from app.models.user import User

__all__ = [
    "AnonymityMode",
    "Base",
    "Journal",
    "JournalMembership",
    "JournalRole",
    "JournalWorkflowConfig",
    "Manuscript",
    "ManuscriptAuthor",
    "ManuscriptStatus",
    "ManuscriptStatusHistory",
    "ManuscriptVersion",
    "User",
]
