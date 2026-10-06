"""Endpoints used by the Flutter collector app. Everything is scoped to the caller's own collector
profile: assigned customers only, own payments only."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import collector_of, require
from app.api.schemas import (
    CollectionSummaryOut, SnapshotPage, SyncPaymentOut, SyncPaymentsIn, SyncPaymentsOut,
)
from app.core.db import get_db
from app.models import Collector, User
from app.services import billing as svc
from app.services import collector_app as app_svc

router = APIRouter(prefix="/collector", tags=["collector-app"])


def _my_collector(db: Session, user: User) -> Collector:
    collector = collector_of(db, user)
    if collector is None:
        raise HTTPException(403, "You do not have a collector profile")
    return collector


@router.get("/snapshot", response_model=SnapshotPage)
def snapshot(limit: int = 300, offset: int = 0, db: Session = Depends(get_db),
             user: User = Depends(require("collection.view_own"))):
    """Download your assigned customers (with bills) before going offline. Page through with
    offset until `offset + len(customers) >= total`."""
    collector = _my_collector(db, user)
    if collector.status != "ACTIVE":
        raise HTTPException(403, "Your collector account is inactive")
    return app_svc.snapshot_page(db, collector, limit=limit, offset=offset)


@router.post("/payments/sync", response_model=SyncPaymentsOut)
def sync_payments(body: SyncPaymentsIn, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require("payment.create"))):
    """Upload offline payments. Always answers per item (HTTP 200) so one bad payment never blocks
    the rest, and re-sending the same batch is harmless."""
    collector = _my_collector(db, user)
    results = app_svc.sync_payments(
        db, user, collector, [app_svc.SyncItem(**p.model_dump()) for p in body.payments], request)
    db.commit()
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return SyncPaymentsOut(
        counts=counts, results=[SyncPaymentOut(**r.__dict__) for r in results])


@router.get("/summary", response_model=CollectionSummaryOut)
def today_summary(day: date | None = None, db: Session = Depends(get_db),
                  user: User = Depends(require("collection.view_own"))):
    """Totals of your own payments for a day (default today), by payment method."""
    collector = _my_collector(db, user)
    return app_svc.collection_summary(db, collector, day or svc.local_today())
