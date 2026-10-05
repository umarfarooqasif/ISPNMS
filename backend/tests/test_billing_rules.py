"""Pure billing rules (no database): cycles, pricing, statuses, late-fee timing."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.billing_rules import (
    ServiceSpec, add_months, cycle_label, derive_customer_status, late_fee_applies,
    plan_cycles, price_connection,
)

D = Decimal


# ---------------------------------------------------------------- add_months
def test_add_months_clamps_to_month_end_and_does_not_drift():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)  # leap year
    # With the anchor the customer returns to the 31st instead of staying on the 28th.
    assert add_months(date(2026, 1, 31), 2, anchor_day=31) == date(2026, 3, 31)
    assert add_months(date(2026, 12, 5), 1) == date(2027, 1, 5)
    assert add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)


def test_add_months_rejects_bad_anchor():
    with pytest.raises(ValueError):
        add_months(date(2026, 1, 1), 1, anchor_day=32)


def test_cycle_label_covers_one_month():
    assert cycle_label(date(2026, 10, 14)) == "14 Oct 2026 - 13 Nov 2026"
    assert cycle_label(date(2026, 1, 31), 31) == "31 Jan 2026 - 27 Feb 2026"


# ---------------------------------------------------------------- plan_cycles
RUN = date(2026, 10, 4)


def test_nothing_due_outside_the_lead_window():
    plan = plan_cycles(date(2026, 10, 10), None, RUN, 5, 1, False)  # horizon is 9 Oct
    assert plan.billed == () and plan.new_next_due is None and plan.behind == 0


def test_due_inside_lead_window_bills_one_cycle_and_advances():
    plan = plan_cycles(date(2026, 10, 9), None, RUN, 5, 1, False)
    assert plan.billed == (date(2026, 10, 9),)
    assert plan.new_next_due == date(2026, 11, 9) and plan.behind == 0


def test_due_exactly_today_is_billed():
    plan = plan_cycles(RUN, None, RUN, 0, 1, False)
    assert plan.billed == (RUN,)


def test_backlog_is_billed_one_cycle_per_run_and_reported_as_behind():
    # Imported due date 14 Aug; today is 4 Oct, so 14 Aug and 14 Sep are both due.
    plan = plan_cycles(date(2026, 8, 14), None, RUN, 0, 1, False)
    assert plan.billed == (date(2026, 8, 14),)
    assert plan.behind == 1
    assert plan.new_next_due == date(2026, 9, 14)  # still due: the next run continues the catch-up


def test_backlog_with_higher_max_cycles_bills_all_missed_cycles():
    plan = plan_cycles(date(2026, 8, 14), None, RUN, 0, 3, False)
    assert plan.billed == (date(2026, 8, 14), date(2026, 9, 14))
    assert plan.behind == 0 and plan.new_next_due == date(2026, 10, 14)


def test_skip_remaining_jumps_to_the_first_future_cycle_and_reports_what_was_skipped():
    plan = plan_cycles(date(2026, 6, 14), None, RUN, 0, 1, True)
    assert plan.billed == (date(2026, 6, 14),)
    assert plan.skipped == (date(2026, 7, 14), date(2026, 8, 14), date(2026, 9, 14))
    assert plan.new_next_due == date(2026, 10, 14) and plan.behind == 0


def test_anchor_day_keeps_month_end_customers_on_the_31st():
    plan = plan_cycles(date(2026, 1, 31), 31, date(2026, 4, 1), 0, 12, False)
    assert plan.billed == (date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31))
    assert plan.new_next_due == date(2026, 4, 30)


def test_plan_cycles_validates_arguments():
    with pytest.raises(ValueError):
        plan_cycles(RUN, None, RUN, 0, 0, False)
    with pytest.raises(ValueError):
        plan_cycles(RUN, None, RUN, 0, 13, False)
    with pytest.raises(ValueError):
        plan_cycles(RUN, None, RUN, -1, 1, False)
    with pytest.raises(ValueError):  # absurd date must not loop forever
        plan_cycles(date(1900, 1, 1), None, RUN, 0, 1, False)


def test_running_twice_never_bills_the_same_cycle_twice():
    first = plan_cycles(date(2026, 10, 1), None, RUN, 0, 1, False)
    second = plan_cycles(first.new_next_due, None, RUN, 0, 1, False)
    assert first.billed == (date(2026, 10, 1),) and second.billed == ()


# ---------------------------------------------------------------- pricing
def test_internet_only_uses_the_service_line_price():
    p = price_connection("INTERNET", [ServiceSpec("INTERNET", D("1500.00"), "Star6", D("1000"))], None)
    assert p.total == D("1500.00") and p.problems == ()
    assert [(ln.charge_type, ln.amount) for ln in p.lines] == [("INTERNET", D("1500.00"))]


def test_combined_connection_keeps_cable_and_internet_separate():
    p = price_connection("COMBINED", [
        ServiceSpec("INTERNET", D("1000.00"), "Star3"), ServiceSpec("CABLE", D("300.00"), "cable 1"),
    ], None)
    assert p.total == D("1300.00")
    assert {ln.charge_type for ln in p.lines} == {"INTERNET", "CABLE"}


def test_falls_back_to_the_package_list_price():
    p = price_connection("INTERNET", [ServiceSpec("INTERNET", None, "Star3", D("1000.00"))], None)
    assert p.total == D("1000.00") and p.problems == ()


def test_missing_price_is_a_problem_not_a_free_month():
    p = price_connection("INTERNET", [ServiceSpec("INTERNET", None, "Star3", None)], None)
    assert p.total == D("0.00") and p.lines == () and len(p.problems) == 1


def test_no_service_lines_is_a_problem():
    p = price_connection("INTERNET", [], None)
    assert p.problems and p.total == D("0.00")


def test_special_price_override_replaces_service_lines():
    p = price_connection("COMBINED", [ServiceSpec("INTERNET", D("1500.00"))], D("900.00"))
    assert p.total == D("900.00") and len(p.lines) == 1 and p.lines[0].charge_type == "INTERNET"
    cable = price_connection("CABLE", [], D("250.00"))
    assert cable.lines[0].charge_type == "CABLE"


def test_decimal_totals_are_exact():
    p = price_connection("COMBINED", [
        ServiceSpec("INTERNET", D("0.10")), ServiceSpec("CABLE", D("0.20")),
    ], None)
    assert p.total == D("0.30")  # 0.1 + 0.2 in floats would be 0.30000000000000004


def test_zero_priced_line_is_not_emitted():
    p = price_connection("COMBINED", [
        ServiceSpec("INTERNET", D("1000.00")), ServiceSpec("CABLE", D("0")),
    ], None)
    assert len(p.lines) == 1 and p.total == D("1000.00") and p.problems == ()


# ---------------------------------------------------------------- statuses
def test_status_all_disconnected():
    assert derive_customer_status(["DISCONNECTED"], ["OVERDUE"]) == "DISCONNECTED"


def test_status_all_suspended():
    assert derive_customer_status(["SUSPENDED"], []) == "SUSPENDED"


def test_status_worst_open_invoice_wins():
    assert derive_customer_status(["ACTIVE"], ["DUE", "OVERDUE", "PARTIAL"]) == "OVERDUE"
    assert derive_customer_status(["ACTIVE"], ["DUE", "PARTIAL"]) == "PARTIAL"
    assert derive_customer_status(["ACTIVE"], ["DUE"]) == "DUE"


def test_status_paid_and_free():
    assert derive_customer_status(["ACTIVE"], []) == "PAID"
    assert derive_customer_status(["FREE"], []) == "FREE"
    assert derive_customer_status(["TRIAL", "FREE"], []) == "FREE"
    assert derive_customer_status(["FREE", "ACTIVE"], []) == "PAID"


def test_status_one_disconnected_one_active_is_judged_on_the_live_one():
    assert derive_customer_status(["DISCONNECTED", "ACTIVE"], ["DUE"]) == "DUE"


# ---------------------------------------------------------------- late fees
def test_late_fee_only_after_the_grace_period_has_fully_passed():
    due = date(2026, 9, 1)
    assert not late_fee_applies(due, date(2026, 9, 6), 5)   # day 5: still within grace
    assert late_fee_applies(due, date(2026, 9, 7), 5)       # day 6: late
    assert not late_fee_applies(due, date(2026, 8, 1), 0)   # not yet due
