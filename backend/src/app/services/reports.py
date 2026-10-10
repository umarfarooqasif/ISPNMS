"""Pure reporting helpers: date ranges, zero-filled series, rates and safe CSV. No database here."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

MAX_RANGE_DAYS = 366
MAX_EXPORT_ROWS = 200_000
ZERO = Decimal("0.00")


# ------------------------------------------------------------------ date ranges


def parse_range(start: date | None, end: date | None, today: date, max_days: int = MAX_RANGE_DAYS) -> tuple[date, date]:
    """An inclusive date range. Default: the first of this month up to today."""
    lo = start or today.replace(day=1)
    hi = end or today
    if hi < lo:
        raise ValueError("The end date is before the start date.")
    if (hi - lo).days + 1 > max_days:
        raise ValueError(f"Choose a range of at most {max_days} days.")
    return lo, hi


def day_bounds(start: date, end: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start 00:00, day after end 00:00) in the business timezone, so 'today' means the local day."""
    return (datetime.combine(start, time.min, tz), datetime.combine(end + timedelta(days=1), time.min, tz))


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def month_start(d: date) -> date:
    return d.replace(day=1)


def last_months(today: date, count: int) -> list[date]:
    """First day of each of the last `count` months, oldest first, ending with the current month."""
    year, month = today.year, today.month
    out: list[date] = []
    for _ in range(count):
        out.append(date(year, month, 1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(out))


def next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


# ------------------------------------------------------------------ series


def fill_days(found: dict[date, tuple[Decimal, int]], start: date, end: date) -> list[dict]:
    """One row per day, with zeros for days nothing happened, so charts have no gaps."""
    rows = []
    for d in days_between(start, end):
        total, count = found.get(d, (ZERO, 0))
        rows.append({"date": d, "total": Decimal(total).quantize(ZERO), "count": count})
    return rows


def fill_months(billed: dict[date, Decimal], collected: dict[date, Decimal], months: list[date]) -> list[dict]:
    return [
        {
            "month": m,
            "billed": Decimal(billed.get(m, ZERO)).quantize(ZERO),
            "collected": Decimal(collected.get(m, ZERO)).quantize(ZERO),
        }
        for m in months
    ]


def collection_rate(collected: Decimal, billed: Decimal) -> Decimal | None:
    """Collected as a percentage of billed, to one decimal. None when nothing was billed."""
    if billed <= 0:
        return None
    return (Decimal(collected) * 100 / Decimal(billed)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ CSV

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
# Plain numbers and phone numbers (digits, spaces, dots, dashes, brackets) cannot call a function.
_PLAIN_NUMBER = re.compile(r"^[+-]?\d[\d\s().-]*$")


def csv_cell(value: object) -> str:
    """One cell as text, safe to open in Excel: text starting with = + - @ would be run as a formula."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_TRIGGERS) and not _PLAIN_NUMBER.match(text):
        return "'" + text
    return text


def build_csv(headers: list[str], rows: Iterable[Iterable[object]]) -> str:
    """CSV with a UTF-8 byte-order mark so Excel shows Urdu correctly, and CRLF line ends."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([csv_cell(h) for h in headers])
    for row in rows:
        writer.writerow([csv_cell(v) for v in row])
    return "\ufeff" + buffer.getvalue()


def safe_filename(name: str, start: date | None = None, end: date | None = None) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "report"
    if start and end:
        stem += f"_{start.isoformat()}_to_{end.isoformat()}"
    return f"{stem}.csv"
