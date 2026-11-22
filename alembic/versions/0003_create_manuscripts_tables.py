"""Create manuscripts, manuscript_authors, and manuscript_versions tables.

Revision ID: 0003_create_manuscripts_tables
Revises: 0002_create_journals_rbac_workflow
Create Date: 2026-11-22 19:25:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_create_manuscripts_tables"
down_revision: str | Sequence[str] | None = "0002_create_journals_rbac_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "manuscripts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column("submitter_id", sa.Integer(), nullable=False),
        sa.Column("assigned_editor_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("subject_area", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("current_version_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("current_review_round", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "stage_entered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("page_range", sa.String(length=64), nullable=True),
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
            ["assigned_editor_id"],
            ["users.id"],
            name=op.f("fk_manuscripts_assigned_editor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["journal_id"],
            ["journals.id"],
            name=op.f("fk_manuscripts_journal_id_journals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitter_id"],
            ["users.id"],
            name=op.f("fk_manuscripts_submitter_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_manuscripts")),
        sa.UniqueConstraint("doi", name=op.f("uq_manuscripts_doi")),
    )
    op.create_index(op.f("ix_manuscripts_journal_id"), "manuscripts", ["journal_id"], unique=False)
    op.create_index(
        op.f("ix_manuscripts_submitter_id"),
        "manuscripts",
        ["submitter_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_manuscripts_assigned_editor_id"),
        "manuscripts",
        ["assigned_editor_id"],
        unique=False,
    )
    op.create_index(op.f("ix_manuscripts_status"), "manuscripts", ["status"], unique=False)

    op.create_table(
        "manuscript_authors",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("manuscript_id", sa.Integer(), nullable=False),
        sa.Column("author_order", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("affiliation", sa.String(length=255), nullable=True),
        sa.Column("orcid", sa.String(length=32), nullable=True),
        sa.Column(
            "is_corresponding",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["manuscript_id"],
            ["manuscripts.id"],
            name=op.f("fk_manuscript_authors_manuscript_id_manuscripts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_manuscript_authors_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_manuscript_authors")),
        sa.UniqueConstraint(
            "manuscript_id",
            "author_order",
            name="uq_manuscript_authors_manuscript_order",
        ),
    )
    op.create_index(
        op.f("ix_manuscript_authors_manuscript_id"),
        "manuscript_authors",
        ["manuscript_id"],
        unique=False,
    )

    op.create_table(
        "manuscript_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("manuscript_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("file_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("extracted_text", sa.Text(), server_default="", nullable=False),
        sa.Column("response_to_reviewers", sa.Text(), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["manuscript_id"],
            ["manuscripts.id"],
            name=op.f("fk_manuscript_versions_manuscript_id_manuscripts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_manuscript_versions_uploaded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_manuscript_versions")),
        sa.UniqueConstraint("file_key", name=op.f("uq_manuscript_versions_file_key")),
        sa.UniqueConstraint(
            "manuscript_id",
            "version_number",
            name="uq_manuscript_versions_manuscript_version",
        ),
    )
    op.create_index(
        op.f("ix_manuscript_versions_manuscript_id"),
        "manuscript_versions",
        ["manuscript_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_manuscript_versions_manuscript_id"), table_name="manuscript_versions")
    op.drop_table("manuscript_versions")

    op.drop_index(op.f("ix_manuscript_authors_manuscript_id"), table_name="manuscript_authors")
    op.drop_table("manuscript_authors")

    op.drop_index(op.f("ix_manuscripts_status"), table_name="manuscripts")
    op.drop_index(op.f("ix_manuscripts_assigned_editor_id"), table_name="manuscripts")
    op.drop_index(op.f("ix_manuscripts_submitter_id"), table_name="manuscripts")
    op.drop_index(op.f("ix_manuscripts_journal_id"), table_name="manuscripts")
    op.drop_table("manuscripts")
