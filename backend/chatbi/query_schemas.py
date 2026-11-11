"""Typed API contracts for deterministic question answering."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: Literal["ecommerce_mock_v1", "saas_subscription_mock_v1"] = "ecommerce_mock_v1"


class SessionResponse(BaseModel):
    session_id: str
    dataset_id: str
    dataset_version: str
    semantic_catalog_id: str
    semantic_catalog_version: str
    request_id: str


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000)
    clarifies_turn_id: str | None = None


class TimeRange(BaseModel):
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    start_inclusive: str
    end_exclusive: str


class MetricValue(BaseModel):
    metric_id: str
    label: str
    value: str | int | None
    unit: str
    definition: str


class Interpretation(BaseModel):
    metric_ids: list[str] = Field(default_factory=list)
    dimension_ids: list[str] = Field(default_factory=list)
    time_range: TimeRange | None = None
    comparison_range: TimeRange | None = None
    filters: list[str] = Field(default_factory=list)
    sort: list[str] = Field(default_factory=list)
    limit: int | None = None
    clarification_state: Literal["none", "required"] = "none"


class ResultRow(BaseModel):
    key: str
    label: str
    values: dict[str, str | int | None]


class Visualization(BaseModel):
    type: Literal["kpi", "line", "bar", "table", "none"]
    data: list[ResultRow] = Field(default_factory=list)


class Evidence(BaseModel):
    dataset_id: str
    dataset_version: str
    semantic_catalog_id: str
    semantic_catalog_version: str
    mock_data: Literal[True] = True
    metric_definitions: list[str] = Field(default_factory=list)


class QueryDebug(BaseModel):
    query_id: str
    template_id: str
    sql: str
    parameters: dict[str, str | int]
    query_executed: bool
    duration_ms: int | None = None
    result_row_count: int = 0


class TurnResponse(BaseModel):
    request_id: str
    turn_id: str
    status: Literal[
        "completed",
        "clarification_required",
        "unsupported",
        "unknown_term",
        "failed",
    ]
    answer_text: str
    clarification_id: str | None = None
    clarification_prompt: str | None = None
    suggested_terms: list[str] = Field(default_factory=list)
    values: list[MetricValue] = Field(default_factory=list)
    interpretation: Interpretation
    visualization: Visualization = Field(default_factory=lambda: Visualization(type="none"))
    evidence: Evidence
    debug_ref: str | None = None
