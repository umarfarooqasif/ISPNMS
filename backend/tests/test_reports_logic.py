"""Pure reporting helpers (no database): ranges, series, rates and CSV safety."""

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.services.reports import (
    build_csv, collection_rate, csv_cell, day_bounds, days_between, fill_days, fill_months, last_months,
    month_start, next_month, parse_range, safe_filename,
)

D = Decimal
TODAY = date(2026, 10, 4)


def test_default_range_is_this_month_up_to_today():
    assert parse_range(None, None, TODAY) == (date(2026, 10, 1), TODAY)
    assert parse_range(date(2026, 9, 1), None, TODAY) == (date(2026, 9, 1), TODAY)


def test_bad_ranges_are_refused_with_a_plain_message():
    with pytest.raises(ValueError, match="before the start"):
        parse_range(date(2026, 10, 5), date(2026, 10, 1), TODAY)
    with pytest.raises(ValueError, match="at most 366"):
        parse_range(date(2025, 1, 1), date(2026, 10, 1), TODAY)
    assert parse_range(date(2025, 10, 4), TODAY, TODAY)[0] == date(2025, 10, 4)   # exactly 366 days is allowed


def test_day_bounds_follow_the_local_day_not_utc():
    tz = ZoneInfo("Asia/Karachi")   # UTC+5
    lo, hi = day_bounds(date(2026, 10, 4), date(2026, 10, 4), tz)
    assert lo.utcoffset() == timedelta(hours=5) and hi - lo == timedelta(days=1)
    # a payment at 23:30 local on the 4th is inside "the 4th" even though it is 18:30 UTC
    assert lo <= datetime(2026, 10, 4, 23, 30, tzinfo=tz) < hi
    assert not (lo <= datetime(2026, 10, 5, 0, 5, tzinfo=tz) < hi)


def test_days_and_months():
    assert days_between(date(2026, 10, 1), date(2026, 10, 3)) == [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)]
    assert last_months(date(2026, 2, 15), 4) == [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]
    assert last_months(date(2026, 10, 4), 1) == [date(2026, 10, 1)]
    assert month_start(date(2026, 10, 31)) == date(2026, 10, 1)
    assert next_month(date(2026, 12, 1)) == date(2027, 1, 1) and next_month(date(2026, 10, 1)) == date(2026, 11, 1)


def test_series_have_no_gaps_and_keep_exact_amounts():
    rows = fill_days({date(2026, 10, 2): (D("1500.50"), 3)}, date(2026, 10, 1), date(2026, 10, 3))
    assert [(r["date"], r["total"], r["count"]) for r in rows] == [
        (date(2026, 10, 1), D("0.00"), 0), (date(2026, 10, 2), D("1500.50"), 3), (date(2026, 10, 3), D("0.00"), 0)]
    months = [date(2026, 8, 1), date(2026, 9, 1)]
    out = fill_months({date(2026, 9, 1): D("1000")}, {date(2026, 8, 1): D("0.10"), date(2026, 9, 1): D("400.5")}, months)
    assert out == [{"month": date(2026, 8, 1), "billed": D("0.00"), "collected": D("0.10")},
                   {"month": date(2026, 9, 1), "billed": D("1000.00"), "collected": D("400.50")}]


def test_collection_rate():
    assert collection_rate(D("850"), D("1000")) == D("85.0")
    assert collection_rate(D("1"), D("3")) == D("33.3")
    assert collection_rate(D("2"), D("3")) == D("66.7")
    assert collection_rate(D("1200"), D("1000")) == D("120.0")     # collected old dues too
    assert collection_rate(D("500"), D("0")) is None
    assert collection_rate(D("0"), D("-5")) is None


@pytest.mark.parametrize("dangerous", ["=1+1", "=HYPERLINK(\"http://x\")", "+cmd|' /C calc'!A0", "-2+3+cmd", "@SUM(A1)", "\tcmd", "\r=1"])
def test_text_that_would_run_as_a_formula_is_neutralised(dangerous):
    assert csv_cell(dangerous).startswith("'")
    assert csv_cell(dangerous)[1:] == dangerous


@pytest.mark.parametrize("fine", ["-500.00", "+923001234567", "0300 1234567", "-1000", "(042) 123-4567", "Ali Khan", "علی خان", "", "12.5"])
def test_ordinary_values_are_left_alone(fine):
    assert csv_cell(fine) == fine


def test_none_and_numbers_become_text():
    assert csv_cell(None) == ""
    assert csv_cell(D("1500.50")) == "1500.50"
    assert csv_cell(0) == "0"


def test_a_csv_round_trips_with_urdu_commas_quotes_and_newlines():
    rows = [["CU-1", "علی خان", D("1500.50"), 'He said "hi", ok'], ["CU-2", "=cmd", D("-20.00"), "line1\nline2"]]
    text = build_csv(["code", "name", "amount", "note"], rows)
    assert text.startswith("\ufeff")                      # Excel reads UTF-8 (Urdu) correctly
    assert "\r\n" in text
    back = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    assert back[0] == ["code", "name", "amount", "note"]
    assert back[1] == ["CU-1", "علی خان", "1500.50", 'He said "hi", ok']
    assert back[2] == ["CU-2", "'=cmd", "-20.00", "line1\nline2"]    # formula neutralised, real negative kept


def test_headers_only_when_there_are_no_rows():
    assert build_csv(["a", "b"], []) == "\ufeffa,b\r\n"


def test_file_names_are_safe():
    assert safe_filename("payments", date(2026, 10, 1), date(2026, 10, 4)) == "payments_2026-10-01_to_2026-10-04.csv"
    assert safe_filename("../../etc/passwd") == "etc_passwd.csv"
    assert safe_filename("???") == "report.csv"
