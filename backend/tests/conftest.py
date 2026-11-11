"""Keep automated tests offline even when a local developer .env enables an LLM."""

import pytest


@pytest.fixture(autouse=True)
def disable_hosted_llm_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATBI_LLM_PROVIDER", "disabled")
