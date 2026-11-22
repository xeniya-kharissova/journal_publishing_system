"""Create review_invitations and reviews tables.

Revision ID: 0005_create_review_invitations_and_reviews
Revises: 0004_create_manuscript_status_history
Create Date: 2026-11-22 20:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_create_review_invitations_and_reviews"
down_revision: str | Sequence[str] | None = "0004_create_manuscript_status_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_invitations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("manuscript_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("invited_by_id", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
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
            ["invited_by_id"],
            ["users.id"],
            name=op.f("fk_review_invitations_invited_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["manuscript_id"],
            ["manuscripts.id"],
            name=op.f("fk_review_invitations_manuscript_id_manuscripts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name=op.f("fk_review_invitations_reviewer_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_invitations")),
    )
    op.create_index(
        op.f("ix_review_invitations_manuscript_id"),
        "review_invitations",
        ["manuscript_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_invitations_reviewer_id"),
        "review_invitations",
        ["reviewer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_invitations_status"),
        "review_invitations",
        ["status"],
        unique=False,
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("invitation_id", sa.Integer(), nullable=False),
        sa.Column("manuscript_id", sa.Integer(), nullable=False),
        sa.Column("manuscript_version_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=False),
        sa.Column("review_round", sa.Integer(), nullable=False),
        sa.Column("originality_score", sa.Integer(), nullable=False),
        sa.Column("methodology_score", sa.Integer(), nullable=False),
        sa.Column("clarity_score", sa.Integer(), nullable=False),
        sa.Column("significance_score", sa.Integer(), nullable=False),
        sa.Column("recommendation", sa.String(length=32), nullable=False),
        sa.Column("comments_to_author", sa.Text(), nullable=False),
        sa.Column("confidential_comments_to_editor", sa.Text(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "originality_score >= 1 AND originality_score <= 5",
            name="ck_reviews_originality_score_range",
        ),
        sa.CheckConstraint(
            "methodology_score >= 1 AND methodology_score <= 5",
            name="ck_reviews_methodology_score_range",
        ),
        sa.CheckConstraint(
            "clarity_score >= 1 AND clarity_score <= 5",
            name="ck_reviews_clarity_score_range",
        ),
        sa.CheckConstraint(
            "significance_score >= 1 AND significance_score <= 5",
            name="ck_reviews_significance_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["review_invitations.id"],
            name=op.f("fk_reviews_invitation_id_review_invitations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["manuscript_id"],
            ["manuscripts.id"],
            name=op.f("fk_reviews_manuscript_id_manuscripts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["manuscript_version_id"],
            ["manuscript_versions.id"],
            name=op.f("fk_reviews_manuscript_version_id_manuscript_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name=op.f("fk_reviews_reviewer_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
    )
    op.create_index(
        op.f("ix_reviews_invitation_id"),
        "reviews",
        ["invitation_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_reviews_manuscript_id"),
        "reviews",
        ["manuscript_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reviews_manuscript_version_id"),
        "reviews",
        ["manuscript_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reviews_reviewer_id"),
        "reviews",
        ["reviewer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_reviews_reviewer_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_manuscript_version_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_manuscript_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_invitation_id"), table_name="reviews")
    op.drop_table("reviews")

    op.drop_index(op.f("ix_review_invitations_status"), table_name="review_invitations")
    op.drop_index(op.f("ix_review_invitations_reviewer_id"), table_name="review_invitations")
    op.drop_index(op.f("ix_review_invitations_manuscript_id"), table_name="review_invitations")
    op.drop_table("review_invitations")
