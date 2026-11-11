"""add isolated SaaS subscription mock tables

Revision ID: f9b23a8c41d2
Revises: ab66400d87f3
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f9b23a8c41d2"
down_revision: str | Sequence[str] | None = "ab66400d87f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saas_accounts",
        sa.Column("dataset_id", sa.String(80), nullable=False),
        sa.Column("account_id", sa.String(40), nullable=False),
        sa.Column("account_name", sa.String(120), nullable=False),
        sa.Column("region", sa.String(40), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("dataset_id", "account_id"),
    )
    op.create_table(
        "saas_plans",
        sa.Column("dataset_id", sa.String(80), nullable=False),
        sa.Column("plan_id", sa.String(40), nullable=False),
        sa.Column("plan_name", sa.String(80), nullable=False),
        sa.Column("monthly_fee_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.PrimaryKeyConstraint("dataset_id", "plan_id"),
    )
    op.create_table(
        "saas_acquisition_channels",
        sa.Column("dataset_id", sa.String(80), nullable=False),
        sa.Column("channel_id", sa.String(40), nullable=False),
        sa.Column("channel_name", sa.String(80), nullable=False),
        sa.PrimaryKeyConstraint("dataset_id", "channel_id"),
    )
    op.create_table(
        "saas_subscriptions",
        sa.Column("dataset_id", sa.String(80), nullable=False),
        sa.Column("subscription_id", sa.String(40), nullable=False),
        sa.Column("account_id", sa.String(40), nullable=False),
        sa.Column("plan_id", sa.String(40), nullable=False),
        sa.Column("acquisition_channel_id", sa.String(40), nullable=False),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("canceled_at", sa.String(40), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id", "account_id"], ["saas_accounts.dataset_id", "saas_accounts.account_id"]
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "plan_id"], ["saas_plans.dataset_id", "saas_plans.plan_id"]
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "acquisition_channel_id"],
            ["saas_acquisition_channels.dataset_id", "saas_acquisition_channels.channel_id"],
        ),
        sa.PrimaryKeyConstraint("dataset_id", "subscription_id"),
    )


def downgrade() -> None:
    op.drop_table("saas_subscriptions")
    op.drop_table("saas_acquisition_channels")
    op.drop_table("saas_plans")
    op.drop_table("saas_accounts")
