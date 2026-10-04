import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import collector_of, current_user, require
from app.api.schemas import AssignAreas, AssignCustomers, CollectorCreate, CollectorOut
from app.core.db import get_db
from app.models import (
    Area, Collector, CollectorAreaAssignment, CollectorCustomerAssignment, Customer, User,
)
from app.services import audit

router = APIRouter(prefix="/collectors", tags=["collectors"])


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
    return collector


@router.get("", response_model=list[CollectorOut])
def list_collectors(db: Session = Depends(get_db), _: User = Depends(require("collector.manage"))):
    return list(db.scalars(select(Collector).order_by(Collector.code)))


@router.get("/me", response_model=CollectorOut)
def my_collector(db: Session = Depends(get_db), user: User = Depends(current_user)):
    collector = collector_of(db, user)
    if collector is None:
        raise HTTPException(404, "You are not a collector")
    return collector


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
