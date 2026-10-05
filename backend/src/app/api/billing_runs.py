"""Billing operations: monthly bill run, late fees, opening balances, connection status,
outstanding and suspension-candidate reports. Every write is permission-checked and audited."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.billing import _invoice_out
from app.api.deps import require
from app.api.schemas import (
    BillingRunOut, BillRunExecute, BillRunRequest, ConnectionOut, ConnectionStatusChange,
    ConnectionStatusOut, LateFeeExecute, LateFeeRequest, OpeningBalanceLoad,
    OpeningBalanceLoadOut, OpeningBalanceResultOut, OutstandingRow, RunItemOut, RunResultOut,
    SuspensionCandidate,
)
from app.core.db import get_db
from app.models import (
    BillingAccount, BillingRun, BillingRunItem, Customer, LedgerEntry, User,
)
from app.services import audit
from app.services import billing as svc
from app.services import billing_run as runs
from app.services.billing import ZERO
from app.services.opening_balances import OpeningRow, load_opening_balances

router = APIRouter(tags=["billing-operations"])

PREVIEW_ITEM_LIMIT = 500


def _result_out(result: runs.RunResult) -> RunResultOut:
    shown = result.items[:PREVIEW_ITEM_LIMIT]
    return RunResultOut(
        dry_run=result.dry_run, run_id=result.run_id, invoices_created=result.invoices_created,
        total_billed=result.total_billed, counts=result.counts,
        behind_connections=result.behind_connections, skipped_cycles=result.skipped_cycles,
        items=[RunItemOut.model_validate(i, from_attributes=True) for i in shown],
        items_truncated=len(result.items) > len(shown),
    )


def _need_confirm(confirm: bool, what: str) -> None:
    if not confirm:
        raise HTTPException(422, f"{what} creates real invoices. Preview first, then send "
                                 f'"confirm": true to run it.')


# ------------------------------------------------------------------ monthly bill run
@router.post("/billing/runs/preview", response_model=RunResultOut)
def preview_bill_run(body: BillRunRequest, db: Session = Depends(get_db),
                     user: User = Depends(require("billing.run"))):
    """Shows exactly what a run would do. Writes nothing."""
    result = runs.run_monthly_billing(
        db, run_date=body.run_date, lead_days=body.lead_days, max_cycles=body.max_cycles,
        skip_remaining=body.skip_remaining, user_id=user.id, dry_run=True)
    db.rollback()
    return _result_out(result)


@router.post("/billing/runs", response_model=RunResultOut, status_code=201)
def execute_bill_run(body: BillRunExecute, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require("billing.run"))):
    _need_confirm(body.confirm, "A bill run")
    result = runs.run_monthly_billing(
        db, run_date=body.run_date, lead_days=body.lead_days, max_cycles=body.max_cycles,
        skip_remaining=body.skip_remaining, user_id=user.id, dry_run=False)
    audit.log(db, user_id=user.id, action="billing.run", entity="billing_run",
              entity_id=result.run_id,
              after={"run_date": body.run_date, "lead_days": body.lead_days,
                     "max_cycles": body.max_cycles, "skip_remaining": body.skip_remaining,
                     "invoices_created": result.invoices_created,
                     "total_billed": result.total_billed, "counts": result.counts},
              request=request)
    db.commit()
    return _result_out(result)


@router.get("/billing/runs", response_model=list[BillingRunOut])
def list_runs(kind: str | None = None, limit: int = 50, offset: int = 0,
              db: Session = Depends(get_db), user: User = Depends(require("invoice.view"))):
    stmt = select(BillingRun).order_by(BillingRun.created_at.desc(), BillingRun.id.desc())
    if kind:
        stmt = stmt.where(BillingRun.kind == kind)
    return list(db.scalars(stmt.limit(min(max(limit, 1), 200)).offset(max(offset, 0))))


@router.get("/billing/runs/{run_id}", response_model=BillingRunOut)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db),
            user: User = Depends(require("invoice.view"))):
    run = db.get(BillingRun, run_id)
    if run is None:
        raise HTTPException(404, "Billing run not found")
    return run


@router.get("/billing/runs/{run_id}/items", response_model=list[RunItemOut])
def run_items(run_id: uuid.UUID, outcome: str | None = None, limit: int = 100, offset: int = 0,
              db: Session = Depends(get_db), user: User = Depends(require("invoice.view"))):
    if db.get(BillingRun, run_id) is None:
        raise HTTPException(404, "Billing run not found")
    stmt = select(BillingRunItem).where(BillingRunItem.run_id == run_id)
    if outcome:
        stmt = stmt.where(BillingRunItem.outcome == outcome)
    stmt = stmt.order_by(BillingRunItem.outcome, BillingRunItem.cycle_due_date, BillingRunItem.id)
    return list(db.scalars(stmt.limit(min(max(limit, 1), 500)).offset(max(offset, 0))))


# ------------------------------------------------------------------ late fees
@router.post("/billing/late-fees/preview", response_model=RunResultOut)
def preview_late_fees(body: LateFeeRequest, db: Session = Depends(get_db),
                      user: User = Depends(require("billing.run"))):
    result = runs.run_late_fees(db, run_date=body.run_date, amount=body.amount,
                                grace_days=body.grace_days, due_days=body.due_days,
                                user_id=user.id, dry_run=True)
    db.rollback()
    return _result_out(result)


@router.post("/billing/late-fees", response_model=RunResultOut, status_code=201)
def execute_late_fees(body: LateFeeExecute, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("billing.run"))):
    _need_confirm(body.confirm, "A late-fee run")
    result = runs.run_late_fees(db, run_date=body.run_date, amount=body.amount,
                                grace_days=body.grace_days, due_days=body.due_days,
                                user_id=user.id, dry_run=False)
    audit.log(db, user_id=user.id, action="billing.late_fees", entity="billing_run",
              entity_id=result.run_id,
              after={"fees_charged": result.invoices_created, "total": result.total_billed,
                     "counts": result.counts},
              request=request)
    db.commit()
    return _result_out(result)


# ------------------------------------------------------------------ opening balances (optional)
@router.post("/billing/opening-balances", response_model=OpeningBalanceLoadOut)
def load_balances(body: OpeningBalanceLoad, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require("billing.opening_balance"))):
    """Optional. dry_run defaults to true: you see what would happen before anything is written."""
    results = load_opening_balances(
        db, [OpeningRow(amount=r.amount, wasooli_id=r.wasooli_id, customer_id=r.customer_id,
                        note=r.note) for r in body.rows],
        as_of=body.as_of_date, user_id=user.id, dry_run=body.dry_run)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    if body.dry_run:
        db.rollback()
    else:
        audit.log(db, user_id=user.id, action="opening_balances.load", entity="opening_balances",
                  after={"counts": counts, "as_of_date": body.as_of_date}, request=request)
        db.commit()
    return OpeningBalanceLoadOut(
        dry_run=body.dry_run, counts=counts,
        results=[OpeningBalanceResultOut(index=r.index, status=r.status, customer_id=r.customer_id,
                                         invoice_id=r.invoice_id, message=r.message)
                 for r in results])


# ------------------------------------------------------------------ connection status
@router.post("/connections/{connection_id}/status", response_model=ConnectionStatusOut)
def set_connection_status(connection_id: uuid.UUID, body: ConnectionStatusChange, request: Request,
                          db: Session = Depends(get_db),
                          user: User = Depends(require("connection.status"))):
    conn, old, invoice = runs.change_connection_status(
        db, connection_id=connection_id, new_status=body.status, reason=body.reason,
        user_id=user.id, reconnection_fee=body.reconnection_fee, next_due_date=body.next_due_date)
    audit.log(db, user_id=user.id, action="connection.status", entity="connection",
              entity_id=conn.id, before={"status": old},
              after={"status": conn.status, "reason": body.reason,
                     "next_due_date": conn.next_due_date,
                     "reconnection_invoice": invoice.invoice_number if invoice else None},
              request=request)
    db.commit()
    return ConnectionStatusOut(
        connection=ConnectionOut.model_validate(conn), previous_status=old,
        reconnection_invoice=_invoice_out(db, invoice) if invoice else None)


# ------------------------------------------------------------------ reports
@router.get("/billing/outstanding", response_model=list[OutstandingRow])
def outstanding(area_id: uuid.UUID | None = None, min_balance: Decimal = Decimal("0.01"),
                limit: int = 100, offset: int = 0, db: Session = Depends(get_db),
                user: User = Depends(require("invoice.view"))):
    """Customers who owe money, biggest balance first, with their billing status."""
    today = svc.local_today()
    balances = (
        select(BillingAccount.id.label("account_id"), BillingAccount.customer_id.label("cid"),
               func.sum(LedgerEntry.amount).label("bal"))
        .join(LedgerEntry, LedgerEntry.billing_account_id == BillingAccount.id)
        .group_by(BillingAccount.id, BillingAccount.customer_id)
        .having(func.sum(LedgerEntry.amount) >= min_balance)
        .subquery()
    )
    stmt = (select(Customer, balances.c.account_id, balances.c.bal)
            .join(balances, balances.c.cid == Customer.id)
            .order_by(balances.c.bal.desc(), Customer.customer_code))
    if area_id:
        stmt = stmt.where(Customer.area_id == area_id)
    rows = db.execute(stmt.limit(min(max(limit, 1), 200)).offset(max(offset, 0))).all()
    out = []
    for customer, account_id, bal in rows:
        open_rows = svc.open_invoices(db, account_id)
        statuses = [svc.derive_invoice_status(inv.total, paid, inv.due_date, today)
                    for inv, paid in open_rows]
        oldest = min((inv.due_date for inv, _ in open_rows), default=None)
        out.append(OutstandingRow(
            customer_id=customer.id, customer_code=customer.customer_code,
            full_name=customer.full_name, mobile=customer.mobile, balance=bal,
            oldest_due_date=oldest,
            days_overdue=max((today - oldest).days, 0) if oldest else 0,
            billing_status=runs.customer_billing_status(db, customer.id, statuses)))
    return out


@router.get("/billing/suspension-candidates", response_model=list[SuspensionCandidate])
def suspension_candidates(overdue_days: int = 30, db: Session = Depends(get_db),
                          user: User = Depends(require("invoice.view"))):
    """Read-only list of customers who are long overdue. Nothing is ever suspended automatically."""
    today = svc.local_today()
    rows = runs.suspension_candidates(db, overdue_days=max(overdue_days, 0), today=today)
    names = {c.id: c.full_name for c in db.scalars(
        select(Customer).where(Customer.id.in_([r[0] for r in rows])))} if rows else {}
    return [SuspensionCandidate(customer_id=cid, full_name=names.get(cid, ""),
                                oldest_due_date=oldest, days_overdue=(today - oldest).days,
                                outstanding=out if out else ZERO, connection_ids=conns)
            for cid, oldest, out, conns in rows]
