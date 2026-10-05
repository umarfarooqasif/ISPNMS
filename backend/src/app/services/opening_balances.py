"""Optional opening balances: money customers already owed when they moved to this system.

The Wasooli export carries no balances, so every customer starts at zero. If you want to carry
old dues over, load them here. Each one becomes an ordinary invoice (so payments allocate against
it like any other) and is recorded once per customer: loading the same customer twice is refused.
"""

from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Connection, Customer, ExternalRef, OpeningBalance
from app.services import billing as svc
from app.services.billing import ZERO, BillingError, LineIn, money

MAX_ROWS = 5000


@dataclass
class OpeningRow:
    amount: str | Decimal
    wasooli_id: str | None = None
    customer_id: uuid.UUID | None = None
    note: str | None = None


@dataclass
class OpeningResult:
    index: int
    status: str  # CREATED | WOULD_CREATE | ALREADY_EXISTS | NOT_FOUND | INVALID
    customer_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    message: str | None = None


def _resolve_customer(db: Session, row: OpeningRow) -> uuid.UUID | None:
    if row.customer_id is not None:
        return row.customer_id if db.get(Customer, row.customer_id) else None
    if not row.wasooli_id:
        return None
    return db.scalar(
        select(Connection.customer_id)
        .join(ExternalRef, ExternalRef.connection_id == Connection.id)
        .where(ExternalRef.system == "WASOOLI", ExternalRef.ref_type == "ID",
               ExternalRef.value == row.wasooli_id.strip())
    )


def load_opening_balances(
    db: Session, rows: list[OpeningRow], *, as_of: date | None = None,
    user_id: uuid.UUID | None = None, dry_run: bool = True,
) -> list[OpeningResult]:
    if len(rows) > MAX_ROWS:
        raise BillingError(f"at most {MAX_ROWS} rows per load", 422)
    as_of = as_of or svc.local_today()
    results: list[OpeningResult] = []
    seen: set[uuid.UUID] = set()

    for i, row in enumerate(rows):
        try:
            amount = money(Decimal(str(row.amount).strip()))
        except (InvalidOperation, BillingError, ValueError):
            results.append(OpeningResult(i, "INVALID", message=f"bad amount: {row.amount!r}"))
            continue
        if amount <= ZERO:
            results.append(OpeningResult(
                i, "INVALID", message="amount must be greater than zero (credits are not loaded here)"))
            continue
        cust = _resolve_customer(db, row)
        if cust is None:
            who = row.wasooli_id or row.customer_id
            results.append(OpeningResult(i, "NOT_FOUND", message=f"no customer for {who}"))
            continue
        if cust in seen or db.scalar(select(OpeningBalance.id).where(OpeningBalance.customer_id == cust)):
            results.append(OpeningResult(i, "ALREADY_EXISTS", cust,
                                         message="this customer already has an opening balance"))
            continue
        seen.add(cust)
        if dry_run:
            results.append(OpeningResult(i, "WOULD_CREATE", cust))
            continue
        with db.begin_nested():
            invoice = svc.create_invoice(
                db, customer_id=cust,
                lines=[LineIn("OTHER", amount, "Opening balance (previous dues)")],
                issue_date=as_of, due_date=as_of, period=None, notes="Opening balance",
                user_id=user_id)
            db.add(OpeningBalance(customer_id=cust, invoice_id=invoice.id, amount=amount,
                                  as_of_date=as_of, note=row.note, created_by=user_id))
            db.flush()
        results.append(OpeningResult(i, "CREATED", cust, invoice.id))
    return results


def read_csv(path: str) -> list[OpeningRow]:
    """CSV with a header row: wasooli_id,amount[,note]."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not {"wasooli_id", "amount"} <= {f.strip() for f in reader.fieldnames}:
            raise BillingError("CSV needs a header row with at least: wasooli_id,amount", 422)
        return [
            OpeningRow(amount=(r.get("amount") or "").strip(), wasooli_id=(r.get("wasooli_id") or "").strip(),
                       note=(r.get("note") or "").strip() or None)
            for r in reader
        ]
