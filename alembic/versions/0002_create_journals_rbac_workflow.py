"""Create journals, journal_workflow_configs, and journal_memberships tables.

Revision ID: 0002_create_journals_rbac_workflow
Revises: 0001_create_users_table
Create Date: 2026-11-22 19:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_create_journals_rbac_workflow"
down_revision: str | Sequence[str] | None = "0001_create_users_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "journals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("issn", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_keywords", sa.JSON(), nullable=False),
        sa.Column("publisher_name", sa.String(length=255), nullable=True),
        sa.Column(
            "doi_prefix",
            sa.String(length=64),
            server_default="10.9999",
            nullable=False,
        ),
        sa.Column(
            "apc_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "apc_amount_cents",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "apc_currency",
            sa.String(length=3),
            server_default="USD",
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journals")),
    )
    op.create_index(op.f("ix_journals_slug"), "journals", ["slug"], unique=True)

    op.create_table(
        "journal_workflow_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column(
            "anonymity_mode",
            sa.String(length=32),
            server_default="double_anonymous",
            nullable=False,
        ),
        sa.Column("min_reviewers", sa.Integer(), server_default="2", nullable=False),
        sa.Column(
            "require_desk_review",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "require_plagiarism_check",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("desk_review_sla_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column("review_sla_days", sa.Integer(), server_default="21", nullable=False),
        sa.Column("decision_sla_days", sa.Integer(), server_default="14", nullable=False),
        sa.Column("revision_sla_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["journal_id"],
            ["journals.id"],
            name=op.f("fk_journal_workflow_configs_journal_id_journals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_workflow_configs")),
    )
    op.create_index(
        op.f("ix_journal_workflow_configs_journal_id"),
        "journal_workflow_configs",
        ["journal_id"],
        unique=True,
    )

    op.create_table(
        "journal_memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("assigned_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_id"],
            ["users.id"],
            name=op.f("fk_journal_memberships_assigned_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["journal_id"],
            ["journals.id"],
            name=op.f("fk_journal_memberships_journal_id_journals"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_journal_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_memberships")),
        sa.UniqueConstraint(
            "journal_id",
            "user_id",
            "role",
            name="uq_journal_memberships_journal_user_role",
        ),
    )
    op.create_index(
        op.f("ix_journal_memberships_journal_id"),
        "journal_memberships",
        ["journal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_journal_memberships_user_id"),
        "journal_memberships",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_journal_memberships_user_id"), table_name="journal_memberships")
    op.drop_index(op.f("ix_journal_memberships_journal_id"), table_name="journal_memberships")
    op.drop_table("journal_memberships")

    op.drop_index(
        op.f("ix_journal_workflow_configs_journal_id"),
        table_name="journal_workflow_configs",
    )
    op.drop_table("journal_workflow_configs")

    op.drop_index(op.f("ix_journals_slug"), table_name="journals")
    op.drop_table("journals")
