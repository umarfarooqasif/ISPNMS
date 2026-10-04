import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import customer_scope, get_visible_customer, require
from app.api.schemas import (
    ConnectionCreate, ConnectionOut, ConnectionUpdate, CustomerCreate, CustomerOut, CustomerUpdate,
)
from app.core.db import get_db
from app.models import (
    Area, Connection, ConnectionServiceLine, Customer, ExternalRef, Package, Street, User,
)
from app.services import audit
from app.services.billing import get_or_create_account
from app.services.customers import mask_cnic, next_code, normalize_mobile

router = APIRouter(tags=["customers"])


def _out(c: Customer) -> CustomerOut:
    out = CustomerOut.model_validate(c)
    out.cnic_masked = mask_cnic(c.cnic)
    return out


def _snapshot(c: Customer, fields) -> dict:
    return {f: getattr(c, f) for f in fields}


def _check_refs(db: Session, area_id, street_id):
    if area_id and db.get(Area, area_id) is None:
        raise HTTPException(422, "Unknown area")
    if street_id and db.get(Street, street_id) is None:
        raise HTTPException(422, "Unknown street")


# ------------------------------------------------------------------ customers
@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerCreate, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("customer.create"))):
    _check_refs(db, body.area_id, body.street_id)
    data = body.model_dump()
    customer = Customer(
        customer_code=next_code(db, "customer_code_seq", "C"),
        mobile_normalized=normalize_mobile(body.mobile),
        **data,
    )
    db.add(customer)
    db.flush()
    get_or_create_account(db, customer.id)
    audit.log(db, user_id=user.id, action="customer.create", entity="customer",
              entity_id=customer.id, after=data, request=request)
    db.commit()
    return _out(customer)


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(
    q: str | None = None, area_id: uuid.UUID | None = None, status: str | None = None,
    internet_id: str | None = None, limit: int = 50, offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(require("customer.view", "customer.view_assigned")),
):
    stmt = select(Customer).order_by(Customer.full_name, Customer.id)
    scope = customer_scope(db, user)
    if scope is not None:
        stmt = stmt.where(scope)
    stmt = stmt.where(Customer.status == status) if status else stmt.where(Customer.status != "ARCHIVED")
    if area_id:
        stmt = stmt.where(Customer.area_id == area_id)
    if internet_id:
        stmt = stmt.where(exists().where(
            Connection.customer_id == Customer.id, Connection.internet_id == internet_id))
    if q:
        like = f"%{q.strip()}%"
        conds = [
            Customer.full_name.ilike(like), Customer.customer_code.ilike(like),
            Customer.house_no.ilike(like), Customer.mobile.ilike(like),
            exists().where(Connection.customer_id == Customer.id,
                           Connection.internet_id == q.strip()),
        ]
        norm = normalize_mobile(q)
        if norm:
            conds.append(Customer.mobile_normalized == norm)
        stmt = stmt.where(or_(*conds))
    stmt = stmt.limit(min(max(limit, 1), 200)).offset(max(offset, 0))
    return [_out(c) for c in db.scalars(stmt)]


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(require("customer.view", "customer.view_assigned"))):
    return _out(get_visible_customer(db, user, customer_id))


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: uuid.UUID, body: CustomerUpdate, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(require("customer.update"))):
    customer = get_visible_customer(db, user, customer_id)
    fields = body.model_dump(exclude_unset=True)
    if "full_name" in fields and fields["full_name"] is None:
        raise HTTPException(422, "full_name cannot be empty")
    _check_refs(db, fields.get("area_id"), fields.get("street_id"))
    before = _snapshot(customer, fields)
    for k, v in fields.items():
        setattr(customer, k, v)
    if "mobile" in fields:
        customer.mobile_normalized = normalize_mobile(customer.mobile)
    db.flush()
    audit.log(db, user_id=user.id, action="customer.update", entity="customer",
              entity_id=customer.id, before=before, after=fields, request=request)
    db.commit()
    return _out(customer)


@router.post("/customers/{customer_id}/archive", response_model=CustomerOut)
def archive_customer(customer_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require("customer.archive"))):
    """Customers are archived, never deleted: their billing history must survive."""
    customer = get_visible_customer(db, user, customer_id)
    before = {"status": customer.status}
    customer.status = "ARCHIVED"
    customer.deleted_at = datetime.now(UTC)
    audit.log(db, user_id=user.id, action="customer.archive", entity="customer",
              entity_id=customer.id, before=before, after={"status": "ARCHIVED"}, request=request)
    db.commit()
    return _out(customer)


@router.get("/customers/{customer_id}/cnic")
def reveal_cnic(customer_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("customer.cnic.view"))):
    customer = get_visible_customer(db, user, customer_id)
    audit.log(db, user_id=user.id, action="customer.cnic.view", entity="customer",
              entity_id=customer.id, request=request)
    db.commit()
    return {"customer_id": customer.id, "cnic": customer.cnic}


# ------------------------------------------------------------------ connections
def _check_package(db: Session, package_id):
    if package_id and db.get(Package, package_id) is None:
        raise HTTPException(422, "Unknown package")


@router.post("/customers/{customer_id}/connections", response_model=ConnectionOut, status_code=201)
def create_connection(customer_id: uuid.UUID, body: ConnectionCreate, request: Request,
                      db: Session = Depends(get_db),
                      user: User = Depends(require("connection.create"))):
    customer = get_visible_customer(db, user, customer_id)
    _check_package(db, body.package_id)
    _check_refs(db, body.area_id, None)
    for sl in body.service_lines:
        _check_package(db, sl.package_id)

    # Imported/disconnected statuses are stored as given; nothing defaults a connection to ACTIVE
    # except an explicit omission by a human creating a new service.
    conn = Connection(
        customer_id=customer.id,
        connection_code=next_code(db, "connection_code_seq", "CN"),
        **body.model_dump(exclude={"service_lines", "external_refs"}),
    )
    conn.service_lines = [ConnectionServiceLine(**sl.model_dump()) for sl in body.service_lines]
    conn.external_refs = [ExternalRef(**r.model_dump()) for r in body.external_refs]
    db.add(conn)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate external reference or service line")
    audit.log(db, user_id=user.id, action="connection.create", entity="connection",
              entity_id=conn.id, after=body.model_dump(), request=request)
    db.commit()
    return conn


@router.get("/customers/{customer_id}/connections", response_model=list[ConnectionOut])
def list_connections(customer_id: uuid.UUID, db: Session = Depends(get_db),
                     user: User = Depends(require("connection.view"))):
    customer = get_visible_customer(db, user, customer_id)
    return list(db.scalars(
        select(Connection).where(Connection.customer_id == customer.id,
                                 Connection.deleted_at.is_(None)).order_by(Connection.connection_code)
    ))


def _load_connection(db: Session, user: User, connection_id: uuid.UUID) -> Connection:
    conn = db.get(Connection, connection_id)
    if conn is None or conn.deleted_at:
        raise HTTPException(404, "Connection not found")
    get_visible_customer(db, user, conn.customer_id)  # scope check; 404 if outside scope
    return conn


@router.get("/connections/{connection_id}", response_model=ConnectionOut)
def get_connection(connection_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(require("connection.view"))):
    return _load_connection(db, user, connection_id)


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
def update_connection(connection_id: uuid.UUID, body: ConnectionUpdate, request: Request,
                      db: Session = Depends(get_db),
                      user: User = Depends(require("connection.update"))):
    conn = _load_connection(db, user, connection_id)
    fields = body.model_dump(exclude_unset=True)
    _check_package(db, fields.get("package_id"))
    before = {k: getattr(conn, k) for k in fields}
    for k, v in fields.items():
        setattr(conn, k, v)
    db.flush()
    audit.log(db, user_id=user.id, action="connection.update", entity="connection",
              entity_id=conn.id, before=before, after=fields, request=request)
    db.commit()
    return conn
