"""Date helpers."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def months_between(start: date, end: date) -> int:
    """Whole months from start to end (0 if end is before start)."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + end.month - start.month
    if add_months(start, months) > end:
        months -= 1
    return months


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def entry_date(recorded_at: str) -> date:
    return datetime.fromisoformat(recorded_at).date()
