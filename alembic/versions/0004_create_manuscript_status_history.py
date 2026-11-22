"""Create manuscript_status_history table.

Revision ID: 0004_create_manuscript_status_history
Revises: 0003_create_manuscripts_tables
Create Date: 2026-11-22 20:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_create_manuscript_status_history"
down_revision: str | Sequence[str] | None = "0003_create_manuscripts_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "manuscript_status_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("manuscript_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=False),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("changed_by_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"],
            ["users.id"],
            name=op.f("fk_manuscript_status_history_changed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["manuscript_id"],
            ["manuscripts.id"],
            name=op.f("fk_manuscript_status_history_manuscript_id_manuscripts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_manuscript_status_history")),
    )
    op.create_index(
        op.f("ix_manuscript_status_history_manuscript_id"),
        "manuscript_status_history",
        ["manuscript_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_manuscript_status_history_manuscript_id"),
        table_name="manuscript_status_history",
    )
    op.drop_table("manuscript_status_history")
