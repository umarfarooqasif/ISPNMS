"""Monthly bill run, late fees, overdue queries and billing-aware connection status changes.

Guarantees (each backed by a database constraint or lock, and covered by tests):
* A connection cycle is invoiced at most once (partial unique index on billing_run_items).
* Two runs can never overlap (advisory lock); running again the same day creates nothing new.
* One customer failing never aborts the run: it is recorded as an ERROR item and the rest continue.
* Nothing is silent: skipped cycles, unpriced connections and missing due dates are all reported.
* Previews write nothing at all.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    BillingAccount,
    BillingRun,
    BillingRunItem,
    Connection,
    Customer,
    Invoice,
    LateFee,
    OpeningBalance,
    Package,
    Payment,
    PaymentAllocation,
)
from app.services import billing as svc
from app.services.billing import ZERO, BillingError, LineIn, money
from app.services.billing_rules import (
    ServiceSpec,
    cycle_label,
    derive_customer_status,
    late_fee_applies,
    month_start,
    plan_cycles,
    price_connection,
)

RUN_LOCK_KEY = 7_301_001  # pg advisory lock id shared by every billing run
BILLABLE_STATUSES = ("ACTIVE", "FREE", "TRIAL")


@dataclass
class ItemResult:
    customer_id: uuid.UUID
    outcome: str
    connection_id: uuid.UUID | None = None
    cycle_due_date: date | None = None
    amount: Decimal = ZERO
    invoice_id: uuid.UUID | None = None
    message: str | None = None


@dataclass
class RunResult:
    dry_run: bool
    run_id: uuid.UUID | None = None
    invoices_created: int = 0
    total_billed: Decimal = ZERO
    counts: dict[str, int] = field(default_factory=dict)
    behind_connections: int = 0   # connections still owing more cycles after this run
    skipped_cycles: int = 0
    items: list[ItemResult] = field(default_factory=list)


# ------------------------------------------------------------------ monthly bill run


def _packages_for(db: Session, conns: list[Connection]) -> dict[uuid.UUID, Package]:
    ids = {sl.package_id for c in conns for sl in c.service_lines if sl.package_id}
    ids |= {c.package_id for c in conns if c.package_id}
    return {p.id: p for p in db.scalars(select(Package).where(Package.id.in_(ids)))} if ids else {}


def _specs(conn: Connection, packages: dict[uuid.UUID, Package]) -> list[ServiceSpec]:
    specs = []
    for sl in conn.service_lines:
        pkg = packages.get(sl.package_id) if sl.package_id else None
        list_price = None
        if pkg is not None:
            own = pkg.cable_price if sl.service == "CABLE" else pkg.internet_price
            list_price = own if own is not None else pkg.monthly_price
        specs.append(ServiceSpec(sl.service, sl.price, pkg.name if pkg else None, list_price))
    return specs


def _process_customer(
    db: Session, *, run: BillingRun | None, customer_id: uuid.UUID, conns: list[Connection],
    packages: dict[uuid.UUID, Package], run_date: date, lead_days: int, max_cycles: int,
    skip_remaining: bool, user_id: uuid.UUID | None, behind: Counter,
) -> list[ItemResult]:
    """Plans (and, unless run is None, writes) everything for one customer. Raises on failure."""
    dry = run is None
    items: list[ItemResult] = []
    per_cycle: dict[date, list] = defaultdict(list)  # cycle date -> [(conn, pricing)]
    advance: list[tuple[Connection, date]] = []      # (connection, new next_due_date)
    behind_msg: dict[uuid.UUID, str] = {}

    for conn in conns:
        plan = plan_cycles(conn.next_due_date, conn.billing_day, run_date, lead_days, max_cycles,
                           skip_remaining)
        if not plan.billed:
            continue
        if conn.status in ("FREE", "TRIAL"):
            items.append(ItemResult(customer_id, "FREE_SKIPPED", conn.id, plan.billed[0], ZERO,
                                    message=f"{conn.status} connection: nothing charged"))
            advance.append((conn, plan.new_next_due))
        else:
            pricing = price_connection(conn.connection_type, _specs(conn, packages),
                                       conn.monthly_price_override)
            if pricing.problems or pricing.total <= ZERO:
                why = "; ".join(pricing.problems) or "price is zero"
                items.append(ItemResult(customer_id, "ZERO_PRICE", conn.id, plan.billed[0], ZERO,
                                        message=f"not billed, fix the price first: {why}"))
                continue  # due date is NOT advanced, so it shows up again next run
            for d in plan.billed:
                per_cycle[d].append((conn, pricing))
            advance.append((conn, plan.new_next_due))
            if plan.behind:
                behind[conn.id] += plan.behind
                behind_msg[conn.id] = f"{plan.behind} more cycle(s) still due"
        if plan.skipped:
            behind["skipped"] += len(plan.skipped)
            items.append(ItemResult(
                customer_id, "CYCLES_SKIPPED", conn.id, plan.skipped[0], ZERO,
                message="missed cycles not billed: " + ", ".join(d.isoformat() for d in plan.skipped)))

    for d in sorted(per_cycle):
        lines = [
            LineIn(ln.charge_type, ln.amount,
                   f"{conn.connection_code} {ln.description} {cycle_label(d, conn.billing_day)}",
                   conn.id)
            for conn, pricing in per_cycle[d] for ln in pricing.lines
        ]
        invoice = None
        if not dry:
            invoice = svc.create_invoice(
                db, customer_id=customer_id, lines=lines, issue_date=run_date,
                due_date=max(d, run_date), period=month_start(d),
                notes=f"Billing cycle {d.isoformat()}", user_id=user_id,
            )
        for conn, pricing in per_cycle[d]:
            note = behind_msg.get(conn.id)
            items.append(ItemResult(
                customer_id, "INVOICED", conn.id, d, pricing.total,
                invoice.id if invoice else None,
                (invoice.invoice_number if invoice else "would be invoiced")
                + (f"; {note}" if note else "")))

    if not dry:
        for conn, new_due in advance:
            conn.next_due_date = new_due
        for it in items:
            db.add(BillingRunItem(
                run_id=run.id, customer_id=it.customer_id, connection_id=it.connection_id,
                cycle_due_date=it.cycle_due_date, outcome=it.outcome, amount=it.amount,
                invoice_id=it.invoice_id, message=it.message))
        db.flush()
    return items


def run_monthly_billing(
    db: Session, *, run_date: date | None = None, lead_days: int | None = None, max_cycles: int = 1,
    skip_remaining: bool = False, user_id: uuid.UUID | None = None, dry_run: bool = True,
) -> RunResult:
    """Bills every due connection. dry_run=True (the default) previews without writing anything."""
    run_date = run_date or svc.local_today()
    lead_days = get_settings().billing_lead_days if lead_days is None else lead_days
    horizon = run_date + timedelta(days=lead_days)

    run = None
    if not dry_run:
        # Serialises runs: a second run waits here, then finds nothing left to bill.
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": RUN_LOCK_KEY})
        run = BillingRun(
            kind="MONTHLY", run_date=run_date, created_by=user_id,
            params={"lead_days": lead_days, "max_cycles": max_cycles,
                    "skip_remaining": skip_remaining},
        )
        db.add(run)
        db.flush()

    due = list(db.scalars(
        select(Connection).join(Customer, Customer.id == Connection.customer_id)
        .where(Connection.deleted_at.is_(None), Customer.status == "ACTIVE",
               Connection.status.in_(BILLABLE_STATUSES), Connection.next_due_date.is_not(None),
               Connection.next_due_date <= horizon)
        .order_by(Connection.customer_id, Connection.connection_code)))
    packages = _packages_for(db, due)
    by_customer: dict[uuid.UUID, list[Connection]] = defaultdict(list)
    for c in due:
        by_customer[c.customer_id].append(c)

    result = RunResult(dry_run=dry_run, run_id=run.id if run else None)
    behind: Counter = Counter()
    for customer_id, conns in by_customer.items():
        local: Counter = Counter()  # merged into `behind` only if this customer succeeds
        try:
            if dry_run:
                items = _process_customer(
                    db, run=None, customer_id=customer_id, conns=conns, packages=packages,
                    run_date=run_date, lead_days=lead_days, max_cycles=max_cycles,
                    skip_remaining=skip_remaining, user_id=user_id, behind=local)
            else:
                with db.begin_nested():  # a failing customer rolls back alone
                    items = _process_customer(
                        db, run=run, customer_id=customer_id, conns=conns, packages=packages,
                        run_date=run_date, lead_days=lead_days, max_cycles=max_cycles,
                        skip_remaining=skip_remaining, user_id=user_id, behind=local)
            behind.update(local)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            items = [ItemResult(customer_id, "ERROR", None, None, ZERO, None, str(exc)[:500])]
            if not dry_run:
                db.add(BillingRunItem(run_id=run.id, customer_id=customer_id, outcome="ERROR",
                                      amount=ZERO, message=items[0].message))
                db.flush()
        result.items.extend(items)

    # Active connections the run cannot bill at all because they have no due date.
    missing = db.execute(
        select(Connection.id, Connection.customer_id)
        .join(Customer, Customer.id == Connection.customer_id)
        .where(Connection.deleted_at.is_(None), Customer.status == "ACTIVE",
               Connection.status == "ACTIVE", Connection.next_due_date.is_(None))
    ).all()
    for conn_id, cust_id in missing:
        it = ItemResult(cust_id, "NO_DUE_DATE", conn_id, None, ZERO, None,
                        "active connection has no next due date; set one to start billing it")
        result.items.append(it)
        if not dry_run:
            db.add(BillingRunItem(run_id=run.id, customer_id=cust_id, connection_id=conn_id,
                                  outcome="NO_DUE_DATE", amount=ZERO, message=it.message))

    invoiced = [i for i in result.items if i.outcome == "INVOICED"]
    result.counts = dict(Counter(i.outcome for i in result.items))
    result.total_billed = sum((i.amount for i in invoiced), ZERO)
    result.skipped_cycles = behind.pop("skipped", 0)
    result.behind_connections = len(behind)
    if invoiced:
        if dry_run:
            result.invoices_created = len({(i.customer_id, i.cycle_due_date) for i in invoiced})
        else:
            result.invoices_created = len({i.invoice_id for i in invoiced})
    if run is not None:
        run.invoices_created = result.invoices_created
        run.total_billed = result.total_billed
        run.summary = {"counts": result.counts, "behind_connections": result.behind_connections,
                       "skipped_cycles": result.skipped_cycles}
        db.flush()
    return result


# ------------------------------------------------------------------ overdue / late fees


def overdue_invoices(db: Session, before: date):
    """[(Invoice, customer_id, outstanding)] for invoices due before `before` with money outstanding."""
    paid = (
        select(PaymentAllocation.invoice_id.label("invoice_id"),
               func.sum(PaymentAllocation.amount).label("paid"))
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(Payment.status != "VOID")
        .group_by(PaymentAllocation.invoice_id)
        .subquery()
    )
    outstanding = Invoice.total - func.coalesce(paid.c.paid, 0)
    rows = db.execute(
        select(Invoice, BillingAccount.customer_id, outstanding.label("outstanding"))
        .join(BillingAccount, BillingAccount.id == Invoice.billing_account_id)
        .outerjoin(paid, paid.c.invoice_id == Invoice.id)
        .where(Invoice.due_date < before, Invoice.total > 0, outstanding > 0)
        .order_by(Invoice.due_date, Invoice.invoice_number)
    ).all()
    return [(inv, cust, Decimal(out)) for inv, cust, out in rows]


def run_late_fees(
    db: Session, *, run_date: date | None = None, amount: Decimal | None = None,
    grace_days: int | None = None, due_days: int | None = None, user_id: uuid.UUID | None = None,
    dry_run: bool = True,
) -> RunResult:
    """Charges one flat late fee per overdue invoice, once ever, as a separate fee invoice.

    Skipped on purpose: invoices that are themselves late fees, imported opening balances (old
    arrears are not penalised retroactively), and customers who are fully disconnected.
    """
    s = get_settings()
    run_date = run_date or svc.local_today()
    amount = money(s.late_fee_amount if amount is None else amount)
    grace_days = s.late_fee_grace_days if grace_days is None else grace_days
    due_days = s.late_fee_due_days if due_days is None else due_days
    if amount <= ZERO:
        raise BillingError("late fees are disabled: the fee amount is zero", 409)

    already = set(db.scalars(select(LateFee.invoice_id)))
    fee_invoices = set(db.scalars(select(LateFee.fee_invoice_id)))
    opening = set(db.scalars(select(OpeningBalance.invoice_id)))
    # Customers whose connections are ALL disconnected owe money but are not charged late fees.
    # (Customers with no connection records at all are treated normally.)
    all_cust = {cid for (cid,) in db.execute(
        select(Connection.customer_id).where(Connection.deleted_at.is_(None)).distinct())}
    live = {cid for (cid,) in db.execute(
        select(Connection.customer_id).where(Connection.deleted_at.is_(None),
                                             Connection.status != "DISCONNECTED").distinct())}
    fully_disconnected = all_cust - live

    run = None
    if not dry_run:
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": RUN_LOCK_KEY})
        run = BillingRun(kind="LATE_FEES", run_date=run_date, created_by=user_id,
                         params={"amount": str(amount), "grace_days": grace_days,
                                 "due_days": due_days})
        db.add(run)
        db.flush()

    by_customer: dict[uuid.UUID, list[Invoice]] = defaultdict(list)
    for inv, cust, _out in overdue_invoices(db, run_date):
        if (inv.id in already or inv.id in fee_invoices or inv.id in opening
                or cust in fully_disconnected or not late_fee_applies(inv.due_date, run_date, grace_days)):
            continue
        by_customer[cust].append(inv)

    result = RunResult(dry_run=dry_run, run_id=run.id if run else None)
    for cust, invs in by_customer.items():
        total = amount * len(invs)
        try:
            fee_invoice = None
            if not dry_run:
                with db.begin_nested():
                    fee_invoice = svc.create_invoice(
                        db, customer_id=cust,
                        lines=[LineIn("LATE_FEE", amount, f"Late fee for {i.invoice_number}")
                               for i in invs],
                        issue_date=run_date, due_date=run_date + timedelta(days=due_days),
                        period=None, notes="Late fee", user_id=user_id)
                    for i in invs:
                        db.add(LateFee(invoice_id=i.id, fee_invoice_id=fee_invoice.id,
                                       run_id=run.id, amount=amount))
                    db.add(BillingRunItem(
                        run_id=run.id, customer_id=cust, outcome="LATE_FEE", amount=total,
                        invoice_id=fee_invoice.id,
                        message="late fee for " + ", ".join(i.invoice_number for i in invs)))
                    db.flush()
            result.items.append(ItemResult(
                cust, "LATE_FEE", None, None, total, fee_invoice.id if fee_invoice else None,
                "late fee for " + ", ".join(i.invoice_number for i in invs)))
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            result.items.append(ItemResult(cust, "ERROR", None, None, ZERO, None, str(exc)[:500]))
            if not dry_run:
                db.add(BillingRunItem(run_id=run.id, customer_id=cust, outcome="ERROR",
                                      amount=ZERO, message=str(exc)[:500]))
                db.flush()

    fees = [i for i in result.items if i.outcome == "LATE_FEE"]
    result.counts = dict(Counter(i.outcome for i in result.items))
    result.total_billed = sum((i.amount for i in fees), ZERO)
    result.invoices_created = len(fees)
    if run is not None:
        run.invoices_created = result.invoices_created
        run.total_billed = result.total_billed
        run.summary = {"counts": result.counts}
        db.flush()
    return result


def suspension_candidates(db: Session, *, overdue_days: int, today: date | None = None):
    """Customers with an ACTIVE connection and an invoice more than `overdue_days` past due.

    Read-only on purpose: nothing is ever suspended automatically.
    Returns [(customer_id, oldest_due_date, outstanding_total, [connection ids])].
    """
    today = today or svc.local_today()
    cutoff = today - timedelta(days=overdue_days)
    per: dict[uuid.UUID, list] = defaultdict(lambda: [None, ZERO])
    for inv, cust, out in overdue_invoices(db, cutoff + timedelta(days=1)):
        row = per[cust]
        row[0] = inv.due_date if row[0] is None else min(row[0], inv.due_date)
        row[1] += out
    if not per:
        return []
    active = defaultdict(list)
    for cid, conn_id in db.execute(
        select(Connection.customer_id, Connection.id)
        .where(Connection.customer_id.in_(per), Connection.status == "ACTIVE",
               Connection.deleted_at.is_(None))
    ):
        active[cid].append(conn_id)
    out = [(c, per[c][0], per[c][1], active[c]) for c in per if active.get(c)]
    return sorted(out, key=lambda r: (r[1], str(r[0])))


# ------------------------------------------------------------------ connection status


def change_connection_status(
    db: Session, *, connection_id: uuid.UUID, new_status: str, reason: str,
    user_id: uuid.UUID | None, reconnection_fee=None, next_due_date: date | None = None,
) -> tuple[Connection, str, Invoice | None]:
    """Billing-aware status change. Returns (connection, old_status, reconnection_invoice|None).

    * Going to SUSPENDED/DISCONNECTED stops billing (those connections are never in a bill run).
    * Coming back to ACTIVE restarts billing at `next_due_date` (default today) and may charge a
      RECONNECTION fee as a normal invoice.
    * Nothing else changes the status; the importer never re-activates a disconnected connection.
    """
    if not reason or not reason.strip():
        raise BillingError("a reason is required", 422)
    conn = db.scalar(select(Connection).where(Connection.id == connection_id).with_for_update())
    if conn is None or conn.deleted_at is not None:
        raise BillingError("connection not found", 404)
    old = conn.status
    if old == new_status:
        raise BillingError(f"connection is already {old}", 409)

    fee = money(reconnection_fee) if reconnection_fee is not None else ZERO
    reconnecting = new_status == "ACTIVE" and old in ("SUSPENDED", "DISCONNECTED")
    if fee != ZERO and not reconnecting:
        raise BillingError("a reconnection fee only applies when reactivating a suspended or "
                           "disconnected connection", 422)
    if fee < ZERO:
        raise BillingError("reconnection fee cannot be negative", 422)

    conn.status = new_status
    today = svc.local_today()
    if new_status in ("ACTIVE", "FREE", "TRIAL") and (next_due_date or reconnecting
                                                       or conn.next_due_date is None):
        conn.next_due_date = next_due_date or today
        conn.billing_day = conn.next_due_date.day
    elif next_due_date is not None:
        raise BillingError("next_due_date only applies when the connection is billable", 422)

    invoice = None
    if fee > ZERO:
        invoice = svc.create_invoice(
            db, customer_id=conn.customer_id,
            lines=[LineIn("RECONNECTION", fee, f"Reconnection fee {conn.connection_code}", conn.id)],
            issue_date=today, due_date=today, period=None, notes=f"Reconnection: {reason.strip()}",
            user_id=user_id)
    db.flush()
    return conn, old, invoice


def customer_billing_status(db: Session, customer_id: uuid.UUID, open_invoice_statuses) -> str:
    """PAID / DUE / PARTIAL / OVERDUE / SUSPENDED / DISCONNECTED / FREE for one customer."""
    statuses = list(db.scalars(
        select(Connection.status).where(Connection.customer_id == customer_id,
                                        Connection.deleted_at.is_(None))))
    return derive_customer_status(statuses, open_invoice_statuses)
