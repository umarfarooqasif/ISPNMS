"""Server side of the collector mobile app: what to download before leaving, how offline payments
come back, and the day's totals.

Offline rules (each covered by tests):
* Every offline payment carries a client transaction id. Syncing the same one again NEVER creates a
  second payment; it returns the original (DUPLICATE). Re-sending a whole batch is always safe.
* Each payment is judged on its own: one bad item never blocks, or rolls back, the others.
* Nothing is silently dropped. Every item gets an explicit answer:
    SYNCED     stored; server receipt number and new balance returned
    DUPLICATE  already stored earlier; the original is returned (harmless, mark it synced)
    REJECTED   will never succeed as sent (not your customer, bad amount, ...). The app keeps it and
               tells the collector to hand the cash and the paper receipt to the office.
    ERROR      temporary server problem; the app retries later.
* A collector can only sync for customers assigned to them, and cannot edit or delete anything.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import assigned_condition
from app.core import constants as C
from app.core.config import get_settings
from app.models import (
    Area,
    BillingAccount,
    Collector,
    Connection,
    Customer,
    Invoice,
    LedgerEntry,
    Payment,
    User,
)
from app.services import audit
from app.services import billing as svc
from app.services.billing import ZERO, BillingError, money
from app.services.billing_rules import derive_customer_status, price_connection
from app.services.billing_run import _packages_for, _specs

log = logging.getLogger(__name__)

MAX_SYNC_BATCH = 200
MAX_SNAPSHOT_PAGE = 500
CLOCK_SKEW = timedelta(minutes=10)
RECEIPT_REF_MAX = 40


# ------------------------------------------------------------------ snapshot (download before leaving)


def snapshot_page(db: Session, collector: Collector, *, limit: int, offset: int) -> dict:
    """One page of the collector's assigned customers with everything needed to work offline:
    contact and Urdu details, connections and packages, balance, and open invoices."""
    limit = min(max(limit, 1), MAX_SNAPSHOT_PAGE)
    offset = max(offset, 0)
    where = (assigned_condition(collector), Customer.status != "ARCHIVED")
    total = db.scalar(select(func.count()).select_from(Customer).where(*where)) or 0
    customers = list(db.scalars(
        select(Customer).where(*where).order_by(Customer.full_name, Customer.id)
        .limit(limit).offset(offset)))
    ids = [c.id for c in customers]
    today = svc.local_today()
    out: list[dict] = []
    if ids:
        conns_by: dict[uuid.UUID, list[Connection]] = {}
        conns = list(db.scalars(
            select(Connection).where(Connection.customer_id.in_(ids), Connection.deleted_at.is_(None))
            .order_by(Connection.connection_code)))
        for c in conns:
            conns_by.setdefault(c.customer_id, []).append(c)
        packages = _packages_for(db, conns)
        areas = {a.id: a for a in db.scalars(
            select(Area).where(Area.id.in_({c.area_id for c in customers if c.area_id})))} \
            if any(c.area_id for c in customers) else {}

        accounts = {a.customer_id: a.id for a in db.scalars(
            select(BillingAccount).where(BillingAccount.customer_id.in_(ids)))}
        balances = dict(db.execute(
            select(LedgerEntry.billing_account_id, func.sum(LedgerEntry.amount))
            .where(LedgerEntry.billing_account_id.in_(list(accounts.values())))
            .group_by(LedgerEntry.billing_account_id)).all()) if accounts else {}
        invoices_by: dict[uuid.UUID, list[Invoice]] = {}
        if accounts:
            for inv in db.scalars(
                select(Invoice).where(Invoice.billing_account_id.in_(list(accounts.values())),
                                      Invoice.total > 0)
                .order_by(Invoice.due_date, Invoice.invoice_number)):
                invoices_by.setdefault(inv.billing_account_id, []).append(inv)
        paid = svc.paid_by_invoice(db, [i.id for invs in invoices_by.values() for i in invs])

        for cust in customers:
            acct = accounts.get(cust.id)
            balance = Decimal(balances.get(acct, 0)).quantize(Decimal("0.01")) if acct else ZERO
            open_rows = []
            for inv in invoices_by.get(acct, []):
                got = paid.get(inv.id, ZERO)
                if inv.total - got > ZERO:
                    open_rows.append({
                        "id": inv.id, "invoice_number": inv.invoice_number, "period": inv.period,
                        "issue_date": inv.issue_date, "due_date": inv.due_date, "total": inv.total,
                        "outstanding": inv.total - got,
                        "status": svc.derive_invoice_status(inv.total, got, inv.due_date, today),
                    })
            conn_rows = []
            for c in conns_by.get(cust.id, []):
                main = packages.get(c.package_id) if c.package_id else None
                names = [packages[sl.package_id].display_name for sl in c.service_lines
                         if sl.package_id in packages] or ([main.display_name] if main else [])
                names_ur = [packages[sl.package_id].display_name_ur for sl in c.service_lines
                            if sl.package_id in packages and packages[sl.package_id].display_name_ur]
                pricing = price_connection(c.connection_type, _specs(c, packages),
                                           c.monthly_price_override)
                conn_rows.append({
                    "id": c.id, "connection_code": c.connection_code, "internet_id": c.internet_id,
                    "connection_type": c.connection_type, "status": c.status,
                    "package_name": " + ".join(names) or None,
                    "package_name_ur": " + ".join(names_ur) or None,
                    "monthly_charge": pricing.total if not pricing.problems else None,
                    "next_due_date": c.next_due_date,
                })
            area = areas.get(cust.area_id)
            out.append({
                "id": cust.id, "customer_code": cust.customer_code, "full_name": cust.full_name,
                "full_name_ur": cust.full_name_ur, "mobile": cust.mobile, "whatsapp": cust.whatsapp,
                "address": cust.address, "address_ur": cust.address_ur, "house_no": cust.house_no,
                "area_name": area.name if area else None,
                "balance": balance, "amount_due": max(balance, ZERO), "credit": max(-balance, ZERO),
                "billing_status": derive_customer_status(
                    [c["status"] for c in conn_rows], [r["status"] for r in open_rows]),
                "oldest_due_date": min((r["due_date"] for r in open_rows), default=None),
                "connections": conn_rows, "open_invoices": open_rows[:24],
            })
    return {"generated_at": datetime.now(UTC), "total": total, "offset": offset, "limit": limit,
            "customers": out}


# ------------------------------------------------------------------ offline payment sync


@dataclass
class SyncItem:
    client_txn_id: str
    customer_id: str
    amount: str
    method: str
    collected_at: str | None = None
    connection_id: str | None = None
    notes: str | None = None
    client_receipt_no: str | None = None


@dataclass
class SyncResult:
    client_txn_id: str
    status: str                       # SYNCED | DUPLICATE | REJECTED | ERROR
    code: str | None = None           # machine-readable reason for REJECTED / ERROR
    reason: str | None = None         # human-readable
    payment_id: uuid.UUID | None = None
    receipt_number: str | None = None
    allocated: Decimal | None = None
    unallocated: Decimal | None = None
    balance: Decimal | None = None
    collected_at_adjusted: bool = False


def _rej(item: SyncItem, code: str, reason: str) -> SyncResult:
    return SyncResult(item.client_txn_id, "REJECTED", code, reason)


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(get_settings().timezone))


def _sync_one(db: Session, user: User, collector: Collector, item: SyncItem,
              request=None) -> SyncResult:
    txn = (item.client_txn_id or "").strip()
    if not 8 <= len(txn) <= 64:
        return _rej(item, "INVALID", "client_txn_id must be 8 to 64 characters")
    item.client_txn_id = txn
    try:
        customer_id = uuid.UUID(item.customer_id)
        connection_id = uuid.UUID(item.connection_id) if item.connection_id else None
    except ValueError:
        return _rej(item, "INVALID", "customer_id / connection_id is not a valid id")
    try:
        amount = money(Decimal(str(item.amount).strip()))
    except (InvalidOperation, BillingError, ValueError):
        return _rej(item, "INVALID", f"bad amount: {item.amount!r}")
    if amount <= ZERO:
        return _rej(item, "INVALID", "amount must be greater than zero")
    if item.method not in C.PAYMENT_METHODS:
        return _rej(item, "INVALID", f"unknown payment method: {item.method!r}")
    receipt_ref = (item.client_receipt_no or "").strip() or None
    if receipt_ref and len(receipt_ref) > RECEIPT_REF_MAX:
        return _rej(item, "INVALID", "client_receipt_no is too long")
    try:
        collected_at = _parse_time(item.collected_at)
    except ValueError:
        return _rej(item, "INVALID", "collected_at is not a valid ISO date-time")

    # Only the collector's own customers. (The app keeps rejected items: the cash was collected, so
    # the collector is told to hand it to the office, nothing is lost and nothing is guessed.)
    if db.scalar(select(Customer.id).where(
            Customer.id == customer_id, assigned_condition(collector),
            Customer.status != "ARCHIVED")) is None:
        return _rej(item, "NOT_ASSIGNED", "this customer is not assigned to you")

    notes = (item.notes or "").strip()[:500] or None
    adjusted = False
    now = datetime.now(UTC)
    if collected_at is not None and collected_at > now + CLOCK_SKEW:
        # A phone clock that runs ahead must not lose a real payment: record it as received now.
        collected_at, adjusted = now, True
        notes = ((notes + " | ") if notes else "") + "collected_at corrected: phone clock was ahead"

    outcome = svc.record_payment(
        db, customer_id=customer_id, amount=amount, method=item.method, user_id=user.id,
        collector_id=collector.id, connection_id=connection_id, client_txn_id=txn,
        collected_at=collected_at, notes=notes, client_receipt_no=receipt_ref)
    result = SyncResult(
        txn, "DUPLICATE" if outcome.replay else "SYNCED", payment_id=outcome.payment.id,
        receipt_number=outcome.receipt.receipt_number if outcome.receipt else None,
        allocated=outcome.allocated, unallocated=outcome.credit, balance=outcome.balance,
        collected_at_adjusted=adjusted)
    if not outcome.replay:
        audit.log(db, user_id=user.id, action="payment.create", entity="payment",
                  entity_id=outcome.payment.id,
                  after={"customer_id": customer_id, "amount": amount, "method": item.method,
                         "receipt_number": result.receipt_number, "collector_id": collector.id,
                         "client_txn_id": txn, "client_receipt_no": receipt_ref,
                         "via": "offline_sync", "collected_at_adjusted": adjusted},
                  request=request)
    return result


def sync_payments(db: Session, user: User, collector: Collector, items: list[SyncItem],
                  request=None) -> list[SyncResult]:
    """Processes a batch. One answer per item, in order; the caller commits once at the end."""
    if len(items) > MAX_SYNC_BATCH:
        raise BillingError(f"at most {MAX_SYNC_BATCH} payments per sync call", 422)
    if collector.status != "ACTIVE":
        return [_rej(i, "COLLECTOR_INACTIVE", "your collector account is inactive") for i in items]
    results: list[SyncResult] = []
    for item in items:
        try:
            with db.begin_nested():  # a failing item rolls back alone
                results.append(_sync_one(db, user, collector, item, request))
        except BillingError as exc:
            code = "CONFLICT" if exc.status_code == 409 else "INVALID"
            results.append(_rej(item, code, exc.message))
        except IntegrityError:
            results.append(_rej(item, "RECEIPT_REF_IN_USE",
                                "that receipt number was already used for another payment"))
        except Exception:  # noqa: BLE001 - reported as retryable, never swallowed silently
            log.exception("offline payment sync failed for txn %s", item.client_txn_id)
            results.append(SyncResult(item.client_txn_id, "ERROR", "SERVER_ERROR",
                                      "temporary problem on the server; it will be retried"))
    return results


# ------------------------------------------------------------------ today's collection


def collection_summary(db: Session, collector: Collector, day: date) -> dict:
    tz = ZoneInfo(get_settings().timezone)
    start = datetime.combine(day, time.min, tz)
    end = start + timedelta(days=1)
    mine = (Payment.collector_id == collector.id, Payment.collected_at >= start,
            Payment.collected_at < end)
    rows = db.execute(
        select(Payment.method, func.count(), func.coalesce(func.sum(Payment.amount), 0))
        .where(*mine, Payment.status != "VOID").group_by(Payment.method)
        .order_by(Payment.method)).all()
    voided = db.scalar(select(func.count()).select_from(Payment).where(*mine, Payment.status == "VOID")) or 0
    by_method = [{"method": m, "count": n, "total": Decimal(t)} for m, n, t in rows]
    return {"date": day, "count": sum(r["count"] for r in by_method),
            "total": sum((r["total"] for r in by_method), ZERO), "by_method": by_method,
            "voided_count": voided}
