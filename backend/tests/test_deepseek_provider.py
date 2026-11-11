"""Offline contract tests for the DeepSeek adapter; no network calls are made."""

from __future__ import annotations

import json

import httpx
import pytest
from backend.chatbi.intent_schemas import IntentDraft
from backend.chatbi.llm_provider import (
    DeepSeekIntentProvider,
    DimensionDefinition,
    IntentParseContext,
    IntentProviderError,
    MetricDefinition,
    _build_system_prompt,
    redact_question,
)
from backend.chatbi.main import _configured_intent_provider


def _context() -> IntentParseContext:
    return IntentParseContext(
        catalog_id="ecommerce_mock_semantics",
        catalog_version="0.1.0",
        as_of_date="2026-08-01",
        dataset_start_date="2025-08-01",
        timezone="Asia/Shanghai",
        metrics=(MetricDefinition("sales_amount", "销售额", "折后实付金额", ("成交额",)),),
        dimensions=(DimensionDefinition("product", "商品", ("单品",)),),
    )


def _ready_intent() -> dict[str, object]:
    return {
        "status": "ready",
        "question_kind": "uq04",
        "metric_ids": ["sales_amount"],
        "dimension_ids": ["product"],
        "time_range": {
            "start_inclusive": "2026-07-02",
            "end_exclusive": "2026-08-01",
            "timezone": "Asia/Shanghai",
        },
        "comparison_range": None,
        "filter_ids": ["valid_paid_orders", "positive_sales"],
        "sort": [{"field_id": "sales_amount", "direction": "desc"}],
        "limit": 10,
        "clarification_prompt": None,
    }


class _Response:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"choices": [{"message": {"content": self._content}}]}


def test_provider_requests_json_mode_and_validates_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> _Response:
        captured["url"] = url
        captured.update(kwargs)
        return _Response(json.dumps(_ready_intent()))

    monkeypatch.setattr(httpx, "post", fake_post)
    result = DeepSeekIntentProvider("test-secret").parse("最近30天商品销售额排行", _context())

    assert isinstance(result, IntentDraft)
    assert result.question_kind == "uq04"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    request = captured["json"]
    assert isinstance(request, dict)
    assert request["model"] == "deepseek-flash"
    assert request["response_format"] == {"type": "json_object"}
    assert "Bearer test-secret" in captured["headers"]["Authorization"]


def test_provider_sends_only_allowlisted_question_fragments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> _Response:
        captured.update(kwargs)
        return _Response(json.dumps(_ready_intent()))

    monkeypatch.setattr(httpx, "post", fake_post)
    DeepSeekIntentProvider("test-secret").parse("查张三GMV", _context())

    request = captured["json"]
    assert isinstance(request, dict)
    messages = request["messages"]
    assert isinstance(messages, list)
    user_message = messages[1]
    assert isinstance(user_message, dict)
    assert user_message["content"] == "GMV"
    assert "张三" not in str(request)
    assert "test-secret" not in str(request)


@pytest.mark.parametrize("content", ["   ", "not-json", '{"status":"ready","extra":1}'])
def test_provider_rejects_empty_invalid_or_extra_fields(
    monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _Response(content))
    with pytest.raises(
        IntentProviderError,
        match="provider_empty_content|provider_invalid_intent|provider_schema_",
    ):
        DeepSeekIntentProvider("test-secret").parse("查询销售额", _context())


def test_provider_maps_http_failure_to_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise httpx.TimeoutException("secret must not escape")

    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(IntentProviderError, match="provider_request_failed") as error:
        DeepSeekIntentProvider("test-secret").parse("查询销售额", _context())
    assert "secret" not in str(error.value)


def test_prompt_contains_only_catalog_and_explicit_context() -> None:
    prompt = _build_system_prompt(_context())
    assert "sales_amount" in prompt
    assert "订单明细" not in prompt
    assert "SQL" in prompt


def test_question_redaction_removes_contact_and_id_values() -> None:
    redacted = redact_question("查一下客户叫张三 13812345678 的 GMV，邮箱 test@example.com")

    assert redacted is not None
    assert "13812345678" not in redacted
    assert "test@example.com" not in redacted
    assert "张三" not in redacted
    assert "本周" in (redact_question("用户本周销售额") or "")
    assert "用户" not in (redact_question("用户本周销售额") or "")
    assert "张三" not in (redact_question("查询张三的订单") or "")
    assert "张三" not in (redact_question("查张三GMV") or "")


def test_question_redaction_drops_unrecognized_free_form_spans() -> None:
    redacted = redact_question("看一下王小明最近30天GMV")

    assert redacted is not None
    assert "王小明" not in redacted
    assert "GMV" in redacted
    assert "30天" in redacted


def test_question_redaction_signals_omitted_unknown_term_without_sending_it() -> None:
    redacted = redact_question("最近30天外太空舱销量趋势")

    assert redacted is not None
    assert "外太空舱" not in redacted
    assert "存在未识别文本" in redacted


def test_question_redaction_refuses_unhandled_personal_data_markers() -> None:
    assert redact_question("身份证号码是未知的，查销售额") is None


def test_app_provider_requires_explicit_enablement_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATBI_LLM_PROVIDER", "disabled")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    assert _configured_intent_provider() is None

    monkeypatch.setenv("CHATBI_LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert _configured_intent_provider() is None

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    provider = _configured_intent_provider()
    assert provider is not None
    assert provider.model_name == "deepseek-flash"
