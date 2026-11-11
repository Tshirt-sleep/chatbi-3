"""Provider-neutral structured intent contracts for P7 model parsing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DraftTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: Literal["Asia/Shanghai"]
    start_inclusive: str
    end_exclusive: str


class DraftSort(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str
    direction: Literal["asc", "desc"]


class IntentDraft(BaseModel):
    """Untrusted model proposal; it must pass validate_intent_draft before use."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "clarification_required", "unsupported", "unknown_term"]
    question_kind: (
        Literal[
            "uq01",
            "uq02",
            "uq03",
            "uq04",
            "uq05",
            "uq06",
            "uq07",
            "uq08",
            "uq09",
            "uq10",
            "saas01",
            "saas02",
            "saas03",
            "saas04",
            "saas05",
            "saas06",
        ]
        | None
    ) = None
    metric_ids: list[str] = Field(default_factory=list)
    dimension_ids: list[str] = Field(default_factory=list)
    time_range: DraftTimeRange | None = None
    comparison_range: DraftTimeRange | None = None
    filter_ids: list[str] = Field(default_factory=list)
    sort: list[DraftSort] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=20)
    clarification_prompt: str | None = Field(default=None, min_length=1, max_length=300)
