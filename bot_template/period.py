"""Period parsing and formatting for plans and subscriptions.

Supports calendar periods (month:1, year:1) and fixed-day periods (day:7).
Used for plan duration, subscription period, and billing interval mapping.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class Period:
    """Normalized period: unit (day/month/year) + count."""
    unit: str  # "day", "month", "year"
    count: int  # positive integer

    @property
    def spec(self) -> str:
        return f"{self.unit}:{self.count}"

    @property
    def nominal_days(self) -> int:
        """Approximate days for display ordering (not for billing calculations)."""
        if self.unit == "day":
            return self.count
        if self.unit == "month":
            return self.count * 30
        if self.unit == "year":
            return self.count * 365
        return 0

    @property
    def is_calendar(self) -> bool:
        """True for calendar-anchored periods (month/year), false for fixed-day."""
        return self.unit in ("month", "year")

    def label_ru(self) -> str:
        """Human-readable Russian label."""
        if self.unit == "day":
            if self.count == 1:
                return "1 день"
            if 2 <= self.count <= 4:
                return f"{self.count} дня"
            return f"{self.count} дней"
        if self.unit == "month":
            if self.count == 1:
                return "1 месяц"
            if 2 <= self.count <= 4:
                return f"{self.count} месяца"
            return f"{self.count} месяцев"
        if self.unit == "year":
            if self.count == 1:
                return "1 год"
            if 2 <= self.count <= 4:
                return f"{self.count} года"
            return f"{self.count} лет"
        return self.spec

    def add_to(self, base: datetime) -> datetime:
        """Add period to datetime (calendar-aware for month/year)."""
        if self.unit == "day":
            return base + timedelta(days=self.count)
        if self.unit == "month":
            return _add_months(base, self.count)
        if self.unit == "year":
            return _add_months(base, self.count * 12)
        return base

    @classmethod
    def from_plan(cls, plan: dict | None) -> Optional["Period"]:
        """Parse period from plan dict: prefers `period` field, falls back to `days`."""
        if not plan:
            return None
        # New format: period="month:1" or "day:7"
        period_str = plan.get("period")
        if isinstance(period_str, str) and period_str:
            return cls.parse(period_str)
        # Legacy format: days=30
        days = plan.get("days")
        if isinstance(days, int) and days > 0:
            return cls(unit="day", count=days)
        return None

    @classmethod
    def parse(cls, spec: str | None) -> Optional["Period"]:
        """Parse 'month:1', 'day:7', 'year:1'."""
        if not isinstance(spec, str) or not spec:
            return None
        m = re.fullmatch(r"(day|month|year):(\d+)", spec.strip())
        if not m:
            return None
        unit, count_str = m.groups()
        count = int(count_str)
        if count <= 0:
            return None
        return cls(unit=unit, count=count)


def _add_months(base: datetime, months: int) -> datetime:
    """Add calendar months, handling end-of-month correctly (Jan 31 + 1 month = Feb 28/29)."""
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    # Clamp day to last day of target month
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    day = min(base.day, last_day)
    return base.replace(year=year, month=month, day=day)