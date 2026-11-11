"""Portable SQLAlchemy schema; all rows are scoped by dataset_id."""

from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DatasetManifest(Base):
    __tablename__ = "dataset_manifests"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    timezone: Mapped[str] = mapped_column(String(40), nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)


class Category(Base):
    __tablename__ = "categories"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    category_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    category_name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_category_id: Mapped[str | None] = mapped_column(String(40))
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "parent_category_id"],
            ["categories.dataset_id", "categories.category_id"],
        ),
    )


class Channel(Base):
    __tablename__ = "channels"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    channel_code: Mapped[str] = mapped_column(String(80), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(120), nullable=False)


class Customer(Base):
    __tablename__ = "customers"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    region_code: Mapped[str | None] = mapped_column(String(20))


class Product(Base):
    __tablename__ = "products"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    primary_leaf_category_id: Mapped[str] = mapped_column(String(40), nullable=False)
    list_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "primary_leaf_category_id"],
            ["categories.dataset_id", "categories.category_id"],
        ),
    )


class Order(Base):
    __tablename__ = "orders"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(40), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(40), nullable=False)
    order_status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    paid_at: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    gross_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "customer_id"],
            ["customers.dataset_id", "customers.customer_id"],
        ),
        ForeignKeyConstraint(
            ["dataset_id", "channel_id"],
            ["channels.dataset_id", "channels.channel_id"],
        ),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    order_item_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(40), nullable=False)
    product_id: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    line_discount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    line_amount_after_discount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "order_id"],
            ["orders.dataset_id", "orders.order_id"],
        ),
        ForeignKeyConstraint(
            ["dataset_id", "product_id"],
            ["products.dataset_id", "products.product_id"],
        ),
    )


class Refund(Base):
    __tablename__ = "refunds"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    refund_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_item_id: Mapped[str] = mapped_column(String(40), nullable=False)
    refunded_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_at: Mapped[str] = mapped_column(String(40), nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String(40))
    refund_status: Mapped[str] = mapped_column(String(24), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "order_item_id"],
            ["order_items.dataset_id", "order_items.order_item_id"],
        ),
    )


class SaaSAccount(Base):
    __tablename__ = "saas_accounts"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    account_name: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class SaaSPlan(Base):
    __tablename__ = "saas_plans"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    plan_name: Mapped[str] = mapped_column(String(80), nullable=False)
    monthly_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)


class SaaSAcquisitionChannel(Base):
    __tablename__ = "saas_acquisition_channels"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    channel_name: Mapped[str] = mapped_column(String(80), nullable=False)


class SaaSSubscription(Base):
    __tablename__ = "saas_subscriptions"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(40), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(40), nullable=False)
    acquisition_channel_id: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    canceled_at: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "account_id"],
            ["saas_accounts.dataset_id", "saas_accounts.account_id"],
        ),
        ForeignKeyConstraint(
            ["dataset_id", "plan_id"],
            ["saas_plans.dataset_id", "saas_plans.plan_id"],
        ),
        ForeignKeyConstraint(
            ["dataset_id", "acquisition_channel_id"],
            ["saas_acquisition_channels.dataset_id", "saas_acquisition_channels.channel_id"],
        ),
    )


class TurnFeedback(Base):
    __tablename__ = "turn_feedback"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "session_id", "turn_id", "mock_user_id", name="uq_turn_feedback_identity"
        ),
    )

    feedback_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    turn_id: Mapped[str] = mapped_column(String(36), nullable=False)
    mock_user_id: Mapped[str] = mapped_column(String(24), nullable=False)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[str] = mapped_column(String(40), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    semantic_catalog_id: Mapped[str] = mapped_column(String(80), nullable=False)
    semantic_catalog_version: Mapped[str] = mapped_column(String(40), nullable=False)
