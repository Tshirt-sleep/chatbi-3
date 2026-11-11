"""add privacy-limited per-turn feedback

Revision ID: c21f8d6a4e30
Revises: f9b23a8c41d2
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c21f8d6a4e30"
down_revision: str | Sequence[str] | None = "f9b23a8c41d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "turn_feedback",
        sa.Column("feedback_id", sa.String(36), nullable=False),
        sa.Column("dataset_id", sa.String(80), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("turn_id", sa.String(36), nullable=False),
        sa.Column("mock_user_id", sa.String(24), nullable=False),
        sa.Column("rating", sa.String(8), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("submitted_at", sa.String(40), nullable=False),
        sa.Column("dataset_version", sa.String(40), nullable=False),
        sa.Column("semantic_catalog_id", sa.String(80), nullable=False),
        sa.Column("semantic_catalog_version", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("feedback_id"),
        sa.UniqueConstraint(
            "dataset_id", "session_id", "turn_id", "mock_user_id", name="uq_turn_feedback_identity"
        ),
    )
    op.create_index("ix_turn_feedback_dataset_id", "turn_feedback", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_turn_feedback_dataset_id", table_name="turn_feedback")
    op.drop_table("turn_feedback")
