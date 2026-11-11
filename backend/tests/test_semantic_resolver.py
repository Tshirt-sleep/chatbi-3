from backend.chatbi.query_service import (
    CATALOG,
    _classify,
    _group_dimension,
    _matched_catalog_term,
    _matched_entity_ids,
)


def test_metric_and_dimension_aliases_are_read_from_catalog() -> None:
    assert _matched_entity_ids("昨天订单量是多少", CATALOG.metrics) == {"order_count"}
    assert _group_dimension("再按 SKU 拆一下") == "product"
    assert _classify("昨天订单量是多少") == "uq01"


def test_ambiguous_and_unsupported_terms_are_directory_driven() -> None:
    assert _matched_catalog_term("请解释营收", "ambiguous").id == "revenue"
    assert _classify("请解释营收") == "ambiguous_term"
    assert _matched_catalog_term("最近30天退款率", "unsupported").id == "refund_rate_term"
    assert _classify("最近30天退款率是多少") == "unsupported_term"


def test_inactive_dimension_is_not_silently_ignored() -> None:
    assert _classify("昨天按地区看销售额") == "unsupported_dimension"
    assert _group_dimension("按地区拆分") is None
