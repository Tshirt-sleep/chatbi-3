"""Code-owned allowlist of query shapes and fixed server templates."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class QueryCapability:
    metric_ids: frozenset[str]
    dimension_ids: frozenset[str]
    template_id: str


SUPPORTED_CAPABILITIES = MappingProxyType(
    {
        "uq01": QueryCapability(
            frozenset({"sales_amount", "order_count"}), frozenset(), "uq01_daily_summary"
        ),
        "uq02": QueryCapability(
            frozenset({"sales_amount"}), frozenset({"order_date"}), "uq02_daily_sales_trend"
        ),
        "uq03": QueryCapability(
            frozenset({"sales_amount"}), frozenset(), "uq03_monthly_comparison"
        ),
        "uq04": QueryCapability(
            frozenset({"sales_amount"}), frozenset({"product"}), "uq04_product_top"
        ),
        "uq05": QueryCapability(
            frozenset({"order_count", "sales_amount"}),
            frozenset({"category"}),
            "uq05_category_summary",
        ),
        "uq06": QueryCapability(
            frozenset({"average_order_value"}),
            frozenset({"channel"}),
            "uq06_channel_aov",
        ),
        "uq08": QueryCapability(
            frozenset({"sales_amount"}),
            frozenset({"category"}),
            "uq08_category_comparison",
        ),
        "uq09": QueryCapability(
            frozenset({"order_count", "sales_amount", "average_order_value"}),
            frozenset(),
            "uq09_period_summary",
        ),
    }
)

EXECUTABLE_KINDS = frozenset(SUPPORTED_CAPABILITIES)
KIND_METRICS = MappingProxyType(
    {kind: capability.metric_ids for kind, capability in SUPPORTED_CAPABILITIES.items()}
)
KIND_DIMENSIONS = MappingProxyType(
    {kind: capability.dimension_ids for kind, capability in SUPPORTED_CAPABILITIES.items()}
)
QUERY_TEMPLATE_BY_KIND = MappingProxyType(
    {kind: capability.template_id for kind, capability in SUPPORTED_CAPABILITIES.items()}
)
COMPARISON_KINDS = frozenset({"uq03", "uq08", "uq09"})
ALLOWED_FILTERS = frozenset({"valid_paid_orders", "positive_sales"})

SUPPORTED_METRIC_IMPLEMENTATIONS = frozenset({"sales_amount", "order_count", "average_order_value"})
SUPPORTED_DIMENSION_IMPLEMENTATIONS = frozenset({"order_date", "product", "category", "channel"})
SUPPORTED_FIELD_REFS = frozenset(
    {
        "orders.paid_at",
        "orders.order_id",
        "orders.channel_id",
        "order_items.order_id",
        "order_items.product_id",
        "order_items.line_amount_after_discount_cents",
        "products.product_id",
        "products.product_name",
        "products.primary_leaf_category_id",
        "categories.category_id",
        "channels.channel_id",
        "customers.region_code",
    }
)
