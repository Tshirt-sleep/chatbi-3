"""Calendar periods derived from the active dataset manifest and semantic catalog."""

from __future__ import annotations

from datetime import date, timedelta

from .semantic_catalog import ACTIVE_CATALOG


def completed_month_comparison() -> tuple[date, date, date, date]:
    """Return current and prior comparable month bounds as half-open dates."""
    as_of = ACTIVE_CATALOG.as_of_date
    latest_complete_day = as_of - timedelta(days=1)
    current_start = latest_complete_day.replace(day=1)
    current_end = as_of
    previous_end = current_start
    previous_start = (current_start - timedelta(days=1)).replace(day=1)
    current_days = (current_end - current_start).days
    previous_end = min(previous_start + timedelta(days=current_days), previous_end)
    return current_start, current_end, previous_start, previous_end


def completed_week_comparison() -> tuple[date, date, date, date]:
    """Return the latest complete week-to-date and matching prior-week bounds."""
    as_of = ACTIVE_CATALOG.as_of_date
    # P3 stores ISO weekday values (Monday=1) in the policy.
    week_start_day = (ACTIVE_CATALOG.catalog.policies.week_start_day - 1) % 7
    latest_complete_day = as_of - timedelta(days=1)
    days_since_week_start = (latest_complete_day.weekday() - week_start_day) % 7
    current_start = latest_complete_day - timedelta(days=days_since_week_start)
    current_end = as_of
    elapsed_days = (current_end - current_start).days
    previous_start = current_start - timedelta(days=7)
    previous_end = previous_start + timedelta(days=elapsed_days)
    return current_start, current_end, previous_start, previous_end
