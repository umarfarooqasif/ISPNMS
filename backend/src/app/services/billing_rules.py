"""Pure billing rules: no database, no web framework. Easy to test and to change.

Cycle model (the Wasooli "Recharge Date" is the NEXT DUE DATE, confirmed by the ISP owner):
    * Billing is prepaid. A connection with next_due_date D is invoiced for the month
      D .. D + 1 month - 1 day, and the invoice is due on D (never earlier than the run date).
    * Once a cycle is invoiced the connection's next_due_date moves one month forward.
    * `anchor_day` (connections.billing_day) keeps a 31st-of-the-month customer on the 31st (or the
      last day of shorter months) instead of drifting to the 28th after February.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal("0.00")
MAX_CYCLES_PER_RUN = 12
_SAFETY_MONTHS = 600  # refuse to walk more than 50 years of missed cycles


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int, anchor_day: int | None = None) -> date:
    """d + N months, clamped to the end of short months. Uses `anchor_day` instead of d.day if given."""
    anchor = anchor_day or d.day
    if not 1 <= anchor <= 31:
        raise ValueError("anchor_day must be between 1 and 31")
    index = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    return date(year, month, min(anchor, calendar.monthrange(year, month)[1]))


def cycle_label(due: date, anchor_day: int | None = None) -> str:
    """'14 Oct 2026 - 13 Nov 2026': the service period an invoice for cycle `due` pays for."""
    end = add_months(due, 1, anchor_day) - timedelta(days=1)
    return f"{due:%d %b %Y} - {end:%d %b %Y}"


# ------------------------------------------------------------------ which cycles to bill


@dataclass(frozen=True)
class CyclePlan:
    billed: tuple[date, ...]    # cycle due dates to invoice now, oldest first
    skipped: tuple[date, ...]   # missed cycles deliberately NOT billed (only with skip_remaining)
    behind: int                 # cycles still due after this run (0 when skipping)
    new_next_due: date | None   # None = nothing was due, leave the connection untouched


def plan_cycles(
    next_due: date, anchor_day: int | None, run_date: date, lead_days: int, max_cycles: int,
    skip_remaining: bool,
) -> CyclePlan:
    """Decides which cycles of one connection a billing run should invoice.

    A cycle is due when its due date is on or before run_date + lead_days. At most `max_cycles`
    are billed per run. Cycles beyond that are either left for the next run (they show up as
    `behind`) or, with skip_remaining, written off from billing and reported as `skipped`.
    """
    if not 1 <= max_cycles <= MAX_CYCLES_PER_RUN:
        raise ValueError(f"max_cycles must be between 1 and {MAX_CYCLES_PER_RUN}")
    if lead_days < 0:
        raise ValueError("lead_days cannot be negative")

    horizon = run_date + timedelta(days=lead_days)
    if next_due > horizon:
        return CyclePlan((), (), 0, None)

    due: list[date] = []
    k = 0
    current = next_due
    while current <= horizon:
        due.append(current)
        k += 1
        if k > _SAFETY_MONTHS:
            raise ValueError("next due date is implausibly far in the past")
        current = add_months(next_due, k, anchor_day)
    first_future = current  # first cycle date after the horizon

    billed = tuple(due[:max_cycles])
    rest = due[max_cycles:]
    if skip_remaining:
        return CyclePlan(billed, tuple(rest), 0, first_future)
    return CyclePlan(billed, (), len(rest), add_months(next_due, len(billed), anchor_day))


# ------------------------------------------------------------------ what a cycle costs


@dataclass(frozen=True)
class ServiceSpec:
    service: str                       # "CABLE" | "INTERNET"
    price: Decimal | None              # price stored on the connection's service line
    package_name: str | None = None
    package_price: Decimal | None = None  # the package's list price for this service (fallback)


@dataclass(frozen=True)
class PricedLine:
    charge_type: str   # "INTERNET" | "CABLE"
    amount: Decimal
    description: str


@dataclass(frozen=True)
class Pricing:
    lines: tuple[PricedLine, ...]
    total: Decimal
    problems: tuple[str, ...]


def price_connection(
    connection_type: str, services: Iterable[ServiceSpec], override: Decimal | None,
) -> Pricing:
    """What one monthly cycle of a connection costs.

    A monthly_price_override replaces the service-line prices (special pricing). Otherwise each
    service line is charged at its own price, falling back to the package's list price. Prices are
    never invented: a line with no price anywhere is a *problem*, reported, not charged as zero.
    """
    if override is not None:
        charge_type = "CABLE" if connection_type == "CABLE" else "INTERNET"
        line = PricedLine(charge_type, override, "Monthly charge (special price)")
        return Pricing((line,) if override > ZERO else (), override, ())

    lines: list[PricedLine] = []
    problems: list[str] = []
    specs = list(services)
    if not specs:
        problems.append("connection has no service lines and no special price")
    for spec in specs:
        amount = spec.price if spec.price is not None else spec.package_price
        label = spec.package_name or spec.service.title()
        if amount is None:
            problems.append(f"{spec.service.lower()} ({label}) has no price")
            continue
        if amount > ZERO:
            lines.append(PricedLine(spec.service, amount, label))
    total = sum((ln.amount for ln in lines), ZERO)
    return Pricing(tuple(lines), total, tuple(problems))


# ------------------------------------------------------------------ statuses and fees


def derive_customer_status(connection_statuses: Iterable[str], invoice_statuses: Iterable[str]) -> str:
    """One billing status for a customer: PAID, DUE, PARTIAL, OVERDUE, SUSPENDED, DISCONNECTED or FREE.

    Service state wins when nothing is live (all disconnected / all suspended). Otherwise the worst
    open-invoice state wins. `invoice_statuses` are the statuses of invoices with money outstanding.
    """
    conns = list(connection_statuses)
    live = [s for s in conns if s != "DISCONNECTED"]
    if conns and not live:
        return "DISCONNECTED"
    if live and all(s == "SUSPENDED" for s in live):
        return "SUSPENDED"
    open_states = set(invoice_statuses)
    for state in ("OVERDUE", "PARTIAL", "DUE"):
        if state in open_states:
            return state
    if live and all(s in ("FREE", "TRIAL") for s in live):
        return "FREE"
    return "PAID"


def late_fee_applies(due_date: date, run_date: date, grace_days: int) -> bool:
    """A late fee is only charged once the grace period after the due date has fully passed."""
    return due_date + timedelta(days=grace_days) < run_date
