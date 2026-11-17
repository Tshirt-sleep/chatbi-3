"""Bounded DeepSeek intent evaluation. Reports contain no prompts or model text."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.chatbi import database
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
from backend.chatbi.query_service import (
    CATALOG_VERSION,
    ChatSession,
    _answer_from_model_intent,
    _intent_context,
    get_debug_query,
)

CASES_PATH = ROOT / "harness" / "llm_golden_cases.json"
DEFAULT_OUTPUT = ROOT / "data" / "local" / "p7-intent-report.json"
MAX_REQUESTS_PER_RUN = 1
MOCK_DATASET_ID = "ecommerce_mock_v1"
PRICE_SNAPSHOT = {
    "date": "2026-11-07",
    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
    "input_cache_miss_peak_usd_per_million": 0.30,
    "input_cache_hit_peak_usd_per_million": 0.006,
    "output_peak_usd_per_million": 1.20,
}


def _git_output(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _source_fingerprint() -> tuple[str | None, int]:
    """Fingerprint the code and fixtures that determine model/query evaluation."""
    inputs = [
        *((ROOT / "backend" / "chatbi").rglob("*.py")),
        *((ROOT / "harness").rglob("*.py")),
        ROOT / "backend" / "chatbi" / "catalogs" / "ecommerce_mock_semantics.json",
        ROOT / "harness" / "llm_golden_cases.json",
        ROOT / "data" / "generated" / MOCK_DATASET_ID / "manifest.json",
    ]
    digest = hashlib.sha256()
    included = 0
    try:
        for path in sorted(set(inputs)):
            if not path.is_file():
                continue
            relative_path = path.relative_to(ROOT).as_posix().encode("utf-8")
            content = path.read_bytes()
            digest.update(len(relative_path).to_bytes(4, "big"))
            digest.update(relative_path)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
            included += 1
    except OSError:
        return None, included
    return digest.hexdigest(), included


def _repository_provenance() -> dict[str, Any]:
    revision = _git_output("rev-parse", "--short", "HEAD")
    status = _git_output("status", "--porcelain=v1", "--untracked-files=all")
    diff = _git_output("diff", "--binary", "HEAD")
    source_fingerprint, source_file_count = _source_fingerprint()
    return {
        "code_revision": revision.strip() if revision else "unknown",
        "working_tree_clean": not status.strip() if status is not None else None,
        "working_tree_status_sha256": (
            hashlib.sha256(status.encode("utf-8")).hexdigest()
            if status is not None
            else None
        ),
        "tracked_diff_sha256": (
            hashlib.sha256(diff.encode("utf-8")).hexdigest()
            if diff is not None
            else None
        ),
        "source_fingerprint_sha256": source_fingerprint,
        "source_fingerprint_file_count": source_file_count,
    }


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
    draft: IntentDraft | None = None
    validation_status = "not_available"
    validation_reason = None
    template_id = None
    query_executed = False
    query_execution_status = "not_required"
    query_template_id = None
    query_result_row_count = None
    query_dataset_id = None
    query_dataset_version = None
    query_mock_data = None
    try:
        draft = provider.parse(case["question"], _intent_context(case["question"]))
        intent_passed, error_category = score_draft(draft, case["expected"])
        passed = intent_passed
        actual_status = draft.status
        actual_kind = draft.question_kind
        try:
            validated = validate_intent_draft(draft)
            validation_status = "passed"
            template_id = validated.template_id
        except IntentValidationError as error:
            validation_status = "rejected"
            validation_reason = error.reason_code
        if intent_passed and draft.status == "ready":
            query_execution_status = "running"
            try:
                _require_local_mock_database()
                response = _answer_from_model_intent(
                    draft=draft,
                    request_id=f"p7-harness-{uuid.uuid4()}",
                    turn_id=str(uuid.uuid4()),
                    session=ChatSession(session_id=f"p7-harness-{uuid.uuid4()}"),
                    question=case["question"],
                    engine=database.engine,
                )
                debug = get_debug_query(response.debug_ref or "") if response else None
                query_executed = bool(debug and debug.query_executed)
                query_template_id = debug.template_id if debug else None
                query_result_row_count = debug.result_row_count if debug else None
                query_dataset_id = response.evidence.dataset_id if response else None
                query_dataset_version = (
                    response.evidence.dataset_version if response else None
                )
                query_mock_data = response.evidence.mock_data if response else None
                query_succeeded = bool(
                    response
                    and response.status == "completed"
                    and query_executed
                    and query_template_id == template_id
                    and query_dataset_id == MOCK_DATASET_ID
                    and query_dataset_version
                    and query_mock_data is True
                )
                query_execution_status = (
                    "completed" if query_succeeded else "not_executed"
                )
                passed = intent_passed and query_succeeded
                if not query_succeeded:
                    error_category = "mock_query_not_completed"
            except (LocalMockDatabaseError, SQLAlchemyError):
                query_execution_status = "local_mock_database_unavailable"
                passed = False
                error_category = "local_mock_database_unavailable"
        elif draft.status == "ready":
            query_execution_status = "skipped_intent_mismatch"
    except IntentProviderError as error:
        passed = False
        intent_passed = False
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
        "actual_metric_ids": sorted(draft.metric_ids) if draft else [],
        "actual_dimension_ids": sorted(draft.dimension_ids) if draft else [],
        "actual_time_range": (
            [draft.time_range.start_inclusive, draft.time_range.end_exclusive]
            if draft and draft.time_range
            else None
        ),
        "actual_comparison_range": (
            [
                draft.comparison_range.start_inclusive,
                draft.comparison_range.end_exclusive,
            ]
            if draft and draft.comparison_range
            else None
        ),
        "actual_filter_ids": sorted(draft.filter_ids) if draft else [],
        "actual_sort": (
            [item.model_dump(mode="json") for item in draft.sort] if draft else []
        ),
        "actual_limit": draft.limit if draft else None,
        "backend_validation_status": validation_status,
        "backend_validation_reason": validation_reason,
        "template_id": template_id,
        "actual_model_id": provider.last_model_id,
        "passed": passed,
        "intent_passed": intent_passed,
        "error_category": error_category,
        "query_execution_status": query_execution_status,
        "query_executed": query_executed,
        "query_template_id": query_template_id,
        "query_result_row_count": query_result_row_count,
        "query_dataset_id": query_dataset_id,
        "query_dataset_version": query_dataset_version,
        "query_mock_data": query_mock_data,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "usage": dict(provider.last_usage),
    }


class LocalMockDatabaseError(RuntimeError):
    """Raised when the Harness cannot prove the configured database is local Mock."""


def _require_local_mock_database() -> None:
    """Refuse evaluation queries outside this repository's local Mock SQLite file."""
    url = database.engine.url
    expected_path = (ROOT / "data" / "local" / "chatbi.sqlite").resolve()
    configured_path = Path(url.database or "")
    if not configured_path.is_absolute():
        configured_path = ROOT / configured_path
    if url.get_backend_name() != "sqlite" or configured_path.resolve() != expected_path:
        raise LocalMockDatabaseError("local_mock_database_required")
    try:
        with database.engine.connect() as connection:
            manifest = (
                connection.execute(
                    text(
                        "SELECT version, timezone FROM dataset_manifests "
                        "WHERE dataset_id = :dataset_id"
                    ),
                    {"dataset_id": MOCK_DATASET_ID},
                )
                .mappings()
                .one_or_none()
            )
    except SQLAlchemyError as error:
        raise LocalMockDatabaseError("local_mock_manifest_unavailable") from error
    try:
        expected_manifest = json.loads(
            (ROOT / "data" / "generated" / MOCK_DATASET_ID / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as error:
        raise LocalMockDatabaseError("expected_mock_manifest_unavailable") from error
    if (
        manifest is None
        or manifest["version"] != expected_manifest["version"]
        or manifest["timezone"] != expected_manifest["timezone"]
    ):
        raise LocalMockDatabaseError("local_mock_manifest_mismatch")


def select_model_fallback_cases(
    cases: list[dict[str, Any]], case_ids: list[str]
) -> list[dict[str, Any]]:
    """Select explicitly approved model-fallback cases before constructing a provider."""
    if not case_ids:
        raise ValueError(
            "provide --case-id to prevent accidental rule-case model calls"
        )
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate case IDs are not allowed")
    cases_by_id = {case["id"]: case for case in cases}
    unknown = [case_id for case_id in case_ids if case_id not in cases_by_id]
    if unknown:
        raise ValueError("unknown case ID")
    selected = [cases_by_id[case_id] for case_id in case_ids]
    if any(case.get("evaluation_route") != "model_fallback" for case in selected):
        raise ValueError("selected case is not approved for model fallback")
    return selected


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
    provenance = _repository_provenance()
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
        "suite_id": "ecommerce_chatbi_p7_intent_v2",
        "model": provider.model_name,
        "prompt_version": P7_PROMPT_VERSION,
        **provenance,
        "dataset_version": json.loads(
            (
                ROOT / "data" / "generated" / "ecommerce_mock_v1" / "manifest.json"
            ).read_text(encoding="utf-8")
        )["version"],
        "semantic_catalog_version": CATALOG_VERSION,
        "case_count": len(results),
        "passed_case_count": passed,
        "intent_accuracy": sum(row["intent_passed"] for row in results) / len(results),
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
        "--case-id",
        action="append",
        help="Reviewed model-fallback case ID (required; may be specified once per case)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum API requests; this local validation stage is capped at one",
    )
    args = parser.parse_args()
    cases_data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = cases_data["cases"]
    if cases_data.get("prompt_version") != P7_PROMPT_VERSION:
        parser.error(
            "golden case prompt_version does not match the provider prompt version"
        )
    if len(cases) != cases_data["max_cases"]:
        parser.error("case list or --limit exceeds the reviewed seven-call cap")
    if args.limit != MAX_REQUESTS_PER_RUN:
        parser.error(
            "this local validation stage permits exactly one API request per run"
        )
    try:
        selected_cases = select_model_fallback_cases(cases, args.case_id or [])
    except ValueError as error:
        parser.error(str(error))
    if len(selected_cases) > args.limit:
        parser.error("selected cases exceed the request limit")
    try:
        report = build_report(args.limit, selected_cases)
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
