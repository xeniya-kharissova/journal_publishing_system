"""Create editorial_decisions table.

Revision ID: 0006_create_editorial_decisions
Revises: 0005_create_review_invitations_and_reviews
Create Date: 2026-11-22 20:25:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_create_editorial_decisions"
down_revision: str | Sequence[str] | None = "0005_create_review_invitations_and_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "editorial_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("manuscript_id", sa.Integer(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("manuscript_version_number", sa.Integer(), nullable=False),
        sa.Column("decided_by_id", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("decision_letter", sa.Text(), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_editorial_decisions_decided_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["manuscript_id"],
            ["manuscripts.id"],
            name=op.f("fk_editorial_decisions_manuscript_id_manuscripts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editorial_decisions")),
        sa.UniqueConstraint(
            "manuscript_id",
            "review_round",
            name="uq_editorial_decisions_manuscript_round",
        ),
    )
    op.create_index(
        op.f("ix_editorial_decisions_manuscript_id"),
        "editorial_decisions",
        ["manuscript_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_editorial_decisions_manuscript_id"),
        table_name="editorial_decisions",
    )
    op.drop_table("editorial_decisions")
