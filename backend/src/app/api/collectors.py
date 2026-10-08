import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import collector_of, current_user, require
from app.api.schemas import (
    AssignAreas, AssignCustomers, AssignmentsOut, AssignedCustomerOut, CollectorCreate, CollectorOut,
    CollectorUpdate,
)
from app.core.db import get_db
from app.models import (
    Area, Collector, CollectorAreaAssignment, CollectorCustomerAssignment, Customer, User,
)
from app.services import audit

router = APIRouter(prefix="/collectors", tags=["collectors"])


def _out(db: Session, collector: Collector) -> CollectorOut:
    user = db.get(User, collector.user_id)
    return CollectorOut(
        id=collector.id, user_id=collector.user_id, code=collector.code, status=collector.status,
        username=user.username if user else None, full_name=user.full_name if user else None,
    )


@router.post("", response_model=CollectorOut, status_code=201)
def create_collector(body: CollectorCreate, request: Request, db: Session = Depends(get_db),
                     actor: User = Depends(require("collector.manage"))):
    if db.get(User, body.user_id) is None:
        raise HTTPException(422, "Unknown user")
    collector = Collector(user_id=body.user_id, code=body.code)
    db.add(collector)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "User is already a collector, or the code is taken")
    audit.log(db, user_id=actor.id, action="collector.create", entity="collector",
              entity_id=collector.id, after=body.model_dump(), request=request)
    db.commit()
    return _out(db, collector)


@router.get("", response_model=list[CollectorOut])
def list_collectors(db: Session = Depends(get_db), _: User = Depends(require("collector.manage"))):
    return [_out(db, c) for c in db.scalars(select(Collector).order_by(Collector.code))]


@router.get("/me", response_model=CollectorOut)
def my_collector(db: Session = Depends(get_db), user: User = Depends(current_user)):
    collector = collector_of(db, user)
    if collector is None:
        raise HTTPException(404, "You are not a collector")
    return _out(db, collector)


@router.patch("/{collector_id}", response_model=CollectorOut)
def update_collector(collector_id: uuid.UUID, body: CollectorUpdate, request: Request,
                     db: Session = Depends(get_db), actor: User = Depends(require("collector.manage"))):
    """Deactivate a collector who has left (their phone can no longer sync) or bring them back."""
    collector = db.get(Collector, collector_id)
    if collector is None:
        raise HTTPException(404, "Collector not found")
    before = collector.status
    collector.status = body.status
    db.flush()
    audit.log(db, user_id=actor.id, action="collector.update", entity="collector", entity_id=collector.id,
              before={"status": before}, after={"status": body.status}, request=request)
    db.commit()
    return _out(db, collector)


@router.get("/{collector_id}/assignments", response_model=AssignmentsOut)
def get_assignments(collector_id: uuid.UUID, db: Session = Depends(get_db),
                    _: User = Depends(require("collector.manage"))):
    """What this collector currently covers: whole areas, plus individually assigned customers."""
    if db.get(Collector, collector_id) is None:
        raise HTTPException(404, "Collector not found")
    area_ids = list(db.scalars(select(CollectorAreaAssignment.area_id)
                               .where(CollectorAreaAssignment.collector_id == collector_id)))
    rows = db.execute(
        select(Customer.id, Customer.customer_code, Customer.full_name, CollectorCustomerAssignment.sort_order)
        .join(CollectorCustomerAssignment, CollectorCustomerAssignment.customer_id == Customer.id)
        .where(CollectorCustomerAssignment.collector_id == collector_id)
        .order_by(CollectorCustomerAssignment.sort_order, Customer.full_name)
    ).all()
    return AssignmentsOut(
        area_ids=area_ids,
        customers=[AssignedCustomerOut(customer_id=i, customer_code=c, full_name=n, sort_order=s)
                   for i, c, n, s in rows],
    )


@router.put("/{collector_id}/areas", status_code=204)
def set_areas(collector_id: uuid.UUID, body: AssignAreas, request: Request,
              db: Session = Depends(get_db), actor: User = Depends(require("collector.manage"))):
    if db.get(Collector, collector_id) is None:
        raise HTTPException(404, "Collector not found")
    ids = set(body.area_ids)
    found = set(db.scalars(select(Area.id).where(Area.id.in_(ids)))) if ids else set()
    if found != ids:
        raise HTTPException(422, "Unknown area in list")
    db.execute(delete(CollectorAreaAssignment).where(CollectorAreaAssignment.collector_id == collector_id))
    for a in ids:
        db.add(CollectorAreaAssignment(collector_id=collector_id, area_id=a))
    audit.log(db, user_id=actor.id, action="collector.set_areas", entity="collector",
              entity_id=collector_id, after={"area_ids": [str(a) for a in ids]}, request=request)
    db.commit()


@router.put("/{collector_id}/customers", status_code=204)
def set_customers(collector_id: uuid.UUID, body: AssignCustomers, request: Request,
                  db: Session = Depends(get_db), actor: User = Depends(require("collector.manage"))):
    if db.get(Collector, collector_id) is None:
        raise HTTPException(404, "Collector not found")
    ids = {c.customer_id for c in body.customers}
    found = set(db.scalars(select(Customer.id).where(Customer.id.in_(ids)))) if ids else set()
    if found != ids:
        raise HTTPException(422, "Unknown customer in list")
    db.execute(delete(CollectorCustomerAssignment).where(
        CollectorCustomerAssignment.collector_id == collector_id))
    for c in body.customers:
        db.add(CollectorCustomerAssignment(
            collector_id=collector_id, customer_id=c.customer_id, sort_order=c.sort_order))
    audit.log(db, user_id=actor.id, action="collector.set_customers", entity="collector",
              entity_id=collector_id, after={"count": len(ids)}, request=request)
    db.commit()
