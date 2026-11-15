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
    assert _matched_catalog_term("最近30天退款率", "metric").target_id == "refund_rate"
    assert _classify("最近30天退款率最高的商品有哪些") == "uq07"
    assert _classify("最近30天退款率是多少") == "unsupported"


def test_inactive_dimension_is_not_silently_ignored() -> None:
    assert _classify("昨天按地区看销售额") == "unsupported_dimension"
    assert _group_dimension("按地区拆分") is None


def test_common_natural_wording_routes_to_allowlisted_intents() -> None:
    cases = (
        ("昨日流水和订单量分别是多少", "uq01"),
        ("近一周每天的 GMV 走势怎么样", "uq02"),
        ("最近完整月销售额比前一个月高多少", "uq03"),
        ("近30天 GMV 排名前十的 SKU 有哪些", "uq04"),
        ("过去30天按品类拆分销售额和订单数", "uq05"),
        ("近30天各渠道平均订单金额分别多少", "uq06"),
        ("近30天哪些 SKU 的退款订单率最高", "uq07"),
        ("本周相较上周哪些类目的销售额下滑最多", "uq08"),
        ("订单量涨了但流水没涨，是什么原因", "uq09"),
        ("营收和销售额有何不同", "ambiguous_term"),
        ("最近30天退款金额是多少", None),
    )

    for question, expected in cases:
        assert _classify(question) == expected
