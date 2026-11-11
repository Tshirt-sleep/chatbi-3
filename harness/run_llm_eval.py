"""Bounded DeepSeek intent evaluation. Reports contain no prompts or model text."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from backend.chatbi.config import ROOT
from backend.chatbi.intent_schemas import IntentDraft
from backend.chatbi.intent_validation import (
    IntentValidationError,
    validate_intent_draft,
)
from backend.chatbi.llm_provider import (
    P7_PROMPT_VERSION,
    DeepSeekIntentProvider,
    IntentProviderError,
)
from backend.chatbi.query_service import CATALOG_VERSION, _intent_context

CASES_PATH = ROOT / "harness" / "llm_golden_cases.json"
DEFAULT_OUTPUT = ROOT / "data" / "local" / "p7-intent-report.json"
PRICE_SNAPSHOT = {
    "date": "2026-11-07",
    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
    "input_cache_miss_peak_usd_per_million": 0.30,
    "input_cache_hit_peak_usd_per_million": 0.006,
    "output_peak_usd_per_million": 1.20,
}


def _code_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "uncommitted"


def score_draft(
    draft: IntentDraft, expected: dict[str, Any]
) -> tuple[bool, str | None]:
    """Compare only declared semantic fields; do not persist free-form model text."""
    try:
        validated = validate_intent_draft(draft)
    except IntentValidationError as error:
        return False, error.reason_code

    actual: dict[str, Any] = {
        "status": draft.status,
        "question_kind": draft.question_kind,
        "template_id": validated.template_id,
    }
    if draft.status == "ready":
        actual["metric_ids"] = sorted(draft.metric_ids)
        actual["dimension_ids"] = sorted(draft.dimension_ids)
        actual["time_range"] = (
            [draft.time_range.start_inclusive, draft.time_range.end_exclusive]
            if draft.time_range
            else None
        )
        actual["comparison_range"] = (
            [
                draft.comparison_range.start_inclusive,
                draft.comparison_range.end_exclusive,
            ]
            if draft.comparison_range
            else None
        )
        actual["limit"] = draft.limit
    for field, target in expected.items():
        found = actual.get(field)
        if field in {"metric_ids", "dimension_ids"} and isinstance(found, list):
            if sorted(target) != found:
                return False, "intent_mismatch"
        elif found != target:
            return False, "intent_mismatch"
    return True, None


def evaluate_case(
    provider: DeepSeekIntentProvider, case: dict[str, Any]
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        draft = provider.parse(case["question"], _intent_context(case["question"]))
        passed, error_category = score_draft(draft, case["expected"])
        actual_status = draft.status
        actual_kind = draft.question_kind
    except IntentProviderError as error:
        passed = False
        actual_status = "provider_error"
        actual_kind = None
        error_category = (
            error.args[0]
            if error.args
            and isinstance(error.args[0], str)
            and error.args[0].startswith("provider_")
            else "evaluation_error"
        )
    return {
        "case_id": case["id"],
        "expected_status": case["expected"]["status"],
        "actual_status": actual_status,
        "expected_kind": case["expected"].get("question_kind"),
        "actual_kind": actual_kind,
        "actual_model_id": provider.last_model_id,
        "passed": passed,
        "error_category": error_category,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "usage": dict(provider.last_usage),
    }


def build_report(limit: int, cases: list[dict[str, Any]]) -> dict[str, Any]:
    if limit < 1 or limit > len(cases):
        raise ValueError(f"limit must be between 1 and {len(cases)}")
    if os.getenv("CHATBI_LLM_PROVIDER", "disabled").lower() != "deepseek":
        raise RuntimeError(
            "Set CHATBI_LLM_PROVIDER=deepseek to enable the bounded API evaluation"
        )
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured in this process")

    provider = DeepSeekIntentProvider(
        api_key,
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    results = [evaluate_case(provider, case) for case in cases[:limit]]
    durations = sorted(row["duration_ms"] for row in results)
    total_prompt = sum(row["usage"].get("prompt_tokens", 0) for row in results)
    total_cached = sum(row["usage"].get("cached_tokens", 0) for row in results)
    total_completion = sum(row["usage"].get("completion_tokens", 0) for row in results)
    passed = sum(row["passed"] for row in results)
    uncached_prompt = max(0, total_prompt - total_cached)
    cost_peak = (
        uncached_prompt * PRICE_SNAPSHOT["input_cache_miss_peak_usd_per_million"]
        + total_cached * PRICE_SNAPSHOT["input_cache_hit_peak_usd_per_million"]
        + total_completion * PRICE_SNAPSHOT["output_peak_usd_per_million"]
    ) / 1_000_000
    cost_offpeak = cost_peak / 2
    return {
        "suite_id": "ecommerce_chatbi_p7_intent_v1",
        "model": provider.model_name,
        "prompt_version": P7_PROMPT_VERSION,
        "code_revision": _code_revision(),
        "dataset_version": json.loads(
            (
                ROOT / "data" / "generated" / "ecommerce_mock_v1" / "manifest.json"
            ).read_text(encoding="utf-8")
        )["version"],
        "semantic_catalog_version": CATALOG_VERSION,
        "case_count": len(results),
        "passed_case_count": passed,
        "intent_accuracy": passed / len(results),
        "duration_ms_median": statistics.median(durations),
        "duration_ms_p95_observed": durations[
            min(len(durations) - 1, int(len(durations) * 0.95))
        ],
        "prompt_tokens": total_prompt,
        "cached_prompt_tokens": total_cached,
        "completion_tokens": total_completion,
        "estimated_cost_usd_peak": round(cost_peak, 8),
        "estimated_cost_usd_offpeak": round(cost_offpeak, 8),
        "price_snapshot": PRICE_SNAPSHOT,
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--limit", type=int, default=7, help="Maximum calls; capped at seven per run"
    )
    args = parser.parse_args()
    cases_data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = cases_data["cases"]
    if cases_data.get("prompt_version") != P7_PROMPT_VERSION:
        parser.error(
            "golden case prompt_version does not match the provider prompt version"
        )
    if len(cases) != cases_data["max_cases"] or args.limit > cases_data["max_cases"]:
        parser.error("case list or --limit exceeds the reviewed seven-call cap")
    try:
        report = build_report(args.limit, cases)
    except RuntimeError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed_case_count"] == report["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
