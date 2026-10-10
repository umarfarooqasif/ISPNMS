"""Dashboard numbers, collection reports and CSV exports.

Everything here only reads. Dates are the business's local days (TIMEZONE), so "today" means the
local day, not UTC. Amounts are exact decimals. CSV files are safe to open in Excel (see
services/reports.py). Exports contain customer data, so they need their own permission and are audited.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import Date, cast, func, literal_column, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.config import get_settings
from app.core.db import get_db
from app.models import (
    Area, BillingAccount, Collector, Connection, Customer, Invoice, LedgerEntry, OpeningBalance, Payment,
    Receipt, User,
)
from app.services import audit
from app.services import billing as svc
from app.services import billing_run as runs
from app.services import reports as rep

router = APIRouter(tags=["reports"])

ZERO = Decimal("0.00")
CHUNK = 5000


# ------------------------------------------------------------------ response shapes


class DayRow(BaseModel):
    day: date
    total: Decimal
    count: int


class MethodRow(BaseModel):
    method: str
    total: Decimal
    count: int


class CollectorTotal(BaseModel):
    collector_id: uuid.UUID | None = None
    code: str
    name: str
    total: Decimal
    count: int


class MonthRow(BaseModel):
    month: date
    billed: Decimal
    collected: Decimal


class AreaTotal(BaseModel):
    area: str
    customers: int
    total: Decimal


class DashboardOut(BaseModel):
    as_of: date
    today_collected: Decimal
    today_payments: int
    month_label: str
    month_billed: Decimal
    month_collected: Decimal
    month_payments: int
    collection_rate: Decimal | None = None   # percent of this month's billing collected this month
    outstanding_total: Decimal
    outstanding_customers: int
    connections_by_status: dict[str, int]
    daily: list[DayRow]                      # the last 30 days, no gaps
    monthly: list[MonthRow]                  # the last 12 months, billed vs collected
    collectors_this_month: list[CollectorTotal]
    outstanding_by_area: list[AreaTotal]


# ------------------------------------------------------------------ helpers


def _tzname() -> str:
    return get_settings().timezone


def _range(start: date | None, end: date | None) -> tuple[date, date]:
    try:
        return rep.parse_range(start, end, svc.local_today())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _money(value: object) -> Decimal:
    return Decimal(value or 0).quantize(ZERO)


def _paid_map(db: Session, invoice_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """paid_by_invoice in chunks: a database call cannot take tens of thousands of ids at once."""
    out: dict[uuid.UUID, Decimal] = {}
    for i in range(0, len(invoice_ids), CHUNK):
        out.update(svc.paid_by_invoice(db, invoice_ids[i:i + CHUNK]))
    return out


def _local_day():
    return cast(func.timezone(_tzname(), Payment.collected_at), Date).label("bucket_day")


def _balances_subquery():
    """One row per customer who owes money: (cid, bal)."""
    return (
        select(BillingAccount.customer_id.label("cid"), func.sum(LedgerEntry.amount).label("bal"))
        .join(LedgerEntry, LedgerEntry.billing_account_id == BillingAccount.id)
        .group_by(BillingAccount.customer_id)
        .having(func.sum(LedgerEntry.amount) > 0)
        .subquery()
    )


def _collected_by_day(db: Session, start: date, end: date) -> dict[date, tuple[Decimal, int]]:
    lo, hi = rep.day_bounds(start, end, ZoneInfo(_tzname()))
    day = _local_day()
    rows = db.execute(
        select(day, func.coalesce(func.sum(Payment.amount), 0), func.count())
        .where(Payment.status != "VOID", Payment.collected_at >= lo, Payment.collected_at < hi)
        .group_by(literal_column("bucket_day"))
    ).all()
    return {d: (_money(total), n) for d, total, n in rows}


def _collected_by_month(db: Session, first_month: date, last_day: date) -> dict[date, Decimal]:
    lo, hi = rep.day_bounds(first_month, last_day, ZoneInfo(_tzname()))
    month = cast(func.date_trunc("month", func.timezone(_tzname(), Payment.collected_at)), Date).label("bucket_month")
    rows = db.execute(
        select(month, func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.status != "VOID", Payment.collected_at >= lo, Payment.collected_at < hi)
        .group_by(literal_column("bucket_month"))
    ).all()
    return {m: _money(total) for m, total in rows}


def _billed_by_month(db: Session, first_month: date, last_day: date) -> dict[date, Decimal]:
    """Invoices by the month they were issued. Opening balances carried over from the old system are
    not 'billed' this month, so they are left out."""
    month = cast(func.date_trunc("month", Invoice.issue_date), Date).label("bucket_month")
    rows = db.execute(
        select(month, func.coalesce(func.sum(Invoice.total), 0))
        .where(Invoice.issue_date >= first_month, Invoice.issue_date <= last_day,
               Invoice.id.not_in(select(OpeningBalance.invoice_id)))
        .group_by(literal_column("bucket_month"))
    ).all()
    return {m: _money(total) for m, total in rows}


def _by_collector(db: Session, start: date, end: date) -> list[CollectorTotal]:
    lo, hi = rep.day_bounds(start, end, ZoneInfo(_tzname()))
    rows = db.execute(
        select(Payment.collector_id, Collector.code, User.full_name,
               func.coalesce(func.sum(Payment.amount), 0), func.count())
        .outerjoin(Collector, Collector.id == Payment.collector_id)
        .outerjoin(User, User.id == Collector.user_id)
        .where(Payment.status != "VOID", Payment.collected_at >= lo, Payment.collected_at < hi)
        .group_by(Payment.collector_id, Collector.code, User.full_name)
    ).all()
    out = [
        CollectorTotal(collector_id=cid, code=code or "OFFICE", name=name or "Received at the office",
                       total=_money(total), count=n)
        for cid, code, name, total, n in rows
    ]
    return sorted(out, key=lambda r: (-r.total, r.code))


def _by_method(db: Session, start: date, end: date) -> list[MethodRow]:
    lo, hi = rep.day_bounds(start, end, ZoneInfo(_tzname()))
    rows = db.execute(
        select(Payment.method, func.coalesce(func.sum(Payment.amount), 0), func.count())
        .where(Payment.status != "VOID", Payment.collected_at >= lo, Payment.collected_at < hi)
        .group_by(Payment.method)
    ).all()
    return sorted((MethodRow(method=m, total=_money(t), count=n) for m, t, n in rows), key=lambda r: (-r.total, r.method))


# ------------------------------------------------------------------ dashboard


@router.get("/reports/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(require("report.view"))):
    """Everything the home page shows, in one call."""
    today = svc.local_today()
    this_month = rep.month_start(today)

    today_total, today_count = _collected_by_day(db, today, today).get(today, (ZERO, 0))
    month_days = _collected_by_day(db, this_month, today)
    month_collected = sum((t for t, _ in month_days.values()), ZERO)
    month_payments = sum((n for _, n in month_days.values()), 0)
    month_billed = _billed_by_month(db, this_month, today).get(this_month, ZERO)

    balances = _balances_subquery()
    out_total, out_count = db.execute(
        select(func.coalesce(func.sum(balances.c.bal), 0), func.count()).select_from(balances)
    ).one()
    by_area = db.execute(
        select(Area.name, func.count(), func.coalesce(func.sum(balances.c.bal), 0))
        .select_from(balances)
        .join(Customer, Customer.id == balances.c.cid)
        .outerjoin(Area, Area.id == Customer.area_id)
        .group_by(Area.name)
    ).all()
    statuses = dict(db.execute(
        select(Connection.status, func.count()).where(Connection.deleted_at.is_(None)).group_by(Connection.status)
    ).all())

    months = rep.last_months(today, 12)
    daily_start = today - timedelta(days=29)
    return DashboardOut(
        as_of=today, today_collected=_money(today_total), today_payments=today_count,
        month_label=this_month.strftime("%Y-%m"), month_billed=_money(month_billed),
        month_collected=_money(month_collected), month_payments=month_payments,
        collection_rate=rep.collection_rate(month_collected, month_billed),
        outstanding_total=_money(out_total), outstanding_customers=out_count,
        connections_by_status={k: int(v) for k, v in statuses.items()},
        daily=[DayRow(day=r["date"], total=r["total"], count=r["count"])
               for r in rep.fill_days(_collected_by_day(db, daily_start, today), daily_start, today)],
        monthly=[MonthRow(**r) for r in rep.fill_months(
            _billed_by_month(db, months[0], today), _collected_by_month(db, months[0], today), months)],
        collectors_this_month=_by_collector(db, this_month, today)[:10],
        outstanding_by_area=sorted(
            (AreaTotal(area=name or "No area", customers=n, total=_money(t)) for name, n, t in by_area),
            key=lambda r: -r.total)[:10],
    )


# ------------------------------------------------------------------ collection reports


@router.get("/reports/collections/daily", response_model=list[DayRow])
def collections_daily(date_from: date | None = None, date_to: date | None = None,
                      db: Session = Depends(get_db), user: User = Depends(require("report.view"))):
    start, end = _range(date_from, date_to)
    rows = rep.fill_days(_collected_by_day(db, start, end), start, end)
    return [DayRow(day=r["date"], total=r["total"], count=r["count"]) for r in rows]


@router.get("/reports/collections/by-method", response_model=list[MethodRow])
def collections_by_method(date_from: date | None = None, date_to: date | None = None,
                          db: Session = Depends(get_db), user: User = Depends(require("report.view"))):
    start, end = _range(date_from, date_to)
    return _by_method(db, start, end)


@router.get("/reports/collections/by-collector", response_model=list[CollectorTotal])
def collections_by_collector(date_from: date | None = None, date_to: date | None = None,
                             db: Session = Depends(get_db), user: User = Depends(require("report.view"))):
    start, end = _range(date_from, date_to)
    return _by_collector(db, start, end)


@router.get("/reports/monthly", response_model=list[MonthRow])
def monthly(months: int = Query(12, ge=1, le=36), db: Session = Depends(get_db),
            user: User = Depends(require("report.view"))):
    """Billed versus collected for each of the last `months` months."""
    today = svc.local_today()
    ms = rep.last_months(today, months)
    return [MonthRow(**r) for r in rep.fill_months(
        _billed_by_month(db, ms[0], today), _collected_by_month(db, ms[0], today), ms)]


# ------------------------------------------------------------------ CSV exports


def _csv_response(request: Request, db: Session, user: User, name: str, headers: list[str],
                  rows: list[list[object]], start: date | None = None, end: date | None = None) -> Response:
    if len(rows) > rep.MAX_EXPORT_ROWS:
        raise HTTPException(413, f"That is more than {rep.MAX_EXPORT_ROWS:,} rows. Choose a shorter date range.")
    audit.log(db, user_id=user.id, action="report.export", entity="report",
              after={"report": name, "rows": len(rows), "from": start, "to": end}, request=request)
    db.commit()
    filename = rep.safe_filename(name, start, end)
    return Response(
        content=rep.build_csv(headers, rows).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.get("/reports/export/payments.csv")
def export_payments(request: Request, date_from: date | None = None, date_to: date | None = None,
                    db: Session = Depends(get_db), user: User = Depends(require("report.export"))):
    start, end = _range(date_from, date_to)
    lo, hi = rep.day_bounds(start, end, ZoneInfo(_tzname()))
    tz = ZoneInfo(_tzname())
    found = db.execute(
        select(Payment, Customer.customer_code, Customer.full_name, Receipt.receipt_number, Collector.code)
        .join(BillingAccount, BillingAccount.id == Payment.billing_account_id)
        .join(Customer, Customer.id == BillingAccount.customer_id)
        .outerjoin(Receipt, Receipt.payment_id == Payment.id)
        .outerjoin(Collector, Collector.id == Payment.collector_id)
        .where(Payment.collected_at >= lo, Payment.collected_at < hi)
        .order_by(Payment.collected_at, Payment.id)
        .limit(rep.MAX_EXPORT_ROWS + 1)
    ).all()
    rows = [
        [p.collected_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"), receipt or "", p.client_receipt_no or "", code,
         name, p.method, p.amount, p.status, collector or "", p.notes or ""]
        for p, code, name, receipt, collector in found
    ]
    return _csv_response(request, db, user, "payments",
                         ["date_time", "receipt_no", "paper_receipt_no", "customer_id", "customer_name", "method",
                          "amount", "status", "collector", "notes"], rows, start, end)


@router.get("/reports/export/invoices.csv")
def export_invoices(request: Request, date_from: date | None = None, date_to: date | None = None,
                    db: Session = Depends(get_db), user: User = Depends(require("report.export"))):
    start, end = _range(date_from, date_to)
    today = svc.local_today()
    found = db.execute(
        select(Invoice, Customer.customer_code, Customer.full_name)
        .join(BillingAccount, BillingAccount.id == Invoice.billing_account_id)
        .join(Customer, Customer.id == BillingAccount.customer_id)
        .where(Invoice.issue_date >= start, Invoice.issue_date <= end)
        .order_by(Invoice.issue_date, Invoice.invoice_number)
        .limit(rep.MAX_EXPORT_ROWS + 1)
    ).all()
    paid = _paid_map(db, [inv.id for inv, _, _ in found])
    rows = []
    for inv, code, name in found:
        got = paid.get(inv.id, ZERO)
        rows.append([inv.invoice_number, inv.issue_date, inv.due_date, inv.period or "", code, name, inv.total, got,
                     inv.total - got, svc.derive_invoice_status(inv.total, got, inv.due_date, today)])
    return _csv_response(request, db, user, "invoices",
                         ["invoice_no", "issue_date", "due_date", "for_month", "customer_id", "customer_name",
                          "total", "paid", "owed", "status"], rows, start, end)


@router.get("/reports/export/outstanding.csv")
def export_outstanding(request: Request, db: Session = Depends(get_db),
                       user: User = Depends(require("report.export"))):
    """Everyone who owes money right now, biggest balance first."""
    today = svc.local_today()
    balances = _balances_subquery()
    found = db.execute(
        select(Customer.id, Customer.customer_code, Customer.full_name, Customer.mobile, Area.name, balances.c.bal)
        .select_from(balances)
        .join(Customer, Customer.id == balances.c.cid)
        .outerjoin(Area, Area.id == Customer.area_id)
        .order_by(balances.c.bal.desc(), Customer.customer_code)
        .limit(rep.MAX_EXPORT_ROWS + 1)
    ).all()
    oldest: dict[uuid.UUID, date] = {}
    for inv, cust_id, _out in runs.overdue_invoices(db, date(9999, 12, 31)):
        if cust_id not in oldest or inv.due_date < oldest[cust_id]:
            oldest[cust_id] = inv.due_date
    rows = []
    for cust_id, code, name, mobile, area, bal in found:
        due = oldest.get(cust_id)
        rows.append([code, name, mobile or "", area or "", _money(bal), due or "", max((today - due).days, 0) if due else ""])
    return _csv_response(request, db, user, "outstanding",
                         ["customer_id", "customer_name", "mobile", "area", "owes", "oldest_unpaid_due_date",
                          "days_overdue"], rows)


@router.get("/reports/export/customers.csv")
def export_customers(request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require("report.export"))):
    """The customer list with connections and balance. The CNIC is never exported."""
    found = db.execute(
        select(Customer, Area.name).outerjoin(Area, Area.id == Customer.area_id)
        .order_by(Customer.customer_code).limit(rep.MAX_EXPORT_ROWS + 1)
    ).all()
    conns: dict[uuid.UUID, list[Connection]] = {}
    for c in db.scalars(select(Connection).where(Connection.deleted_at.is_(None)).order_by(Connection.connection_code)):
        conns.setdefault(c.customer_id, []).append(c)
    balance = {cid: Decimal(b) for cid, b in db.execute(
        select(BillingAccount.customer_id, func.sum(LedgerEntry.amount))
        .join(LedgerEntry, LedgerEntry.billing_account_id == BillingAccount.id)
        .group_by(BillingAccount.customer_id)).all()}
    rows = []
    for cust, area in found:
        cs = conns.get(cust.id, [])
        rows.append([
            cust.customer_code, cust.full_name, cust.full_name_ur or "", cust.mobile or "", cust.whatsapp or "",
            area or "", cust.house_no or "", cust.address or "", cust.status,
            " | ".join(c.internet_id or c.connection_code for c in cs),
            " | ".join(c.status for c in cs),
            " | ".join(c.next_due_date.isoformat() if c.next_due_date else "" for c in cs),
            _money(balance.get(cust.id, ZERO)),
        ])
    return _csv_response(request, db, user, "customers",
                         ["customer_id", "name", "name_urdu", "mobile", "whatsapp", "area", "house_no", "address",
                          "status", "internet_ids", "connection_status", "next_due_dates", "balance"], rows)
