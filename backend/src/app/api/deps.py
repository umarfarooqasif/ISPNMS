import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models import (
    Collector,
    CollectorAreaAssignment,
    CollectorCustomerAssignment,
    Customer,
    User,
)
from app.services.rbac import user_permissions

_bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    unauthorized = HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    user_id = decode_access_token(creds.credentials)
    if user_id is None:
        raise unauthorized
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


def has_perm(user: User, code: str) -> bool:
    return code in user_permissions(user)


def require(*codes: str):
    """Dependency: user must hold at least one of the listed permissions (server-side check)."""

    def dep(user: User = Depends(current_user)) -> User:
        perms = user_permissions(user)
        if not any(c in perms for c in codes):
            raise HTTPException(403, "Permission denied")
        return user

    return dep


def collector_of(db: Session, user: User) -> Collector | None:
    return db.scalar(select(Collector).where(Collector.user_id == user.id))


def assigned_condition(collector: Collector):
    """SQL condition: customers assigned to this collector, directly or through an assigned area."""
    direct = select(CollectorCustomerAssignment.customer_id).where(
        CollectorCustomerAssignment.collector_id == collector.id
    )
    areas = select(CollectorAreaAssignment.area_id).where(
        CollectorAreaAssignment.collector_id == collector.id
    )
    return or_(Customer.id.in_(direct), Customer.area_id.in_(areas))


def customer_scope(db: Session, user: User):
    """Returns None for unrestricted access, or a SQL condition limiting customers.

    Users with `customer.view` see everyone. Users with only `customer.view_assigned` see
    customers assigned to their collector profile (directly or via assigned areas).
    """
    perms = user_permissions(user)
    if "customer.view" in perms:
        return None
    if "customer.view_assigned" in perms:
        collector = collector_of(db, user)
        if collector is None or collector.status != "ACTIVE":
            return Customer.id.in_([])  # sees nothing
        return assigned_condition(collector)
    raise HTTPException(403, "Permission denied")


def get_visible_customer(db: Session, user: User, customer_id: uuid.UUID) -> Customer:
    """404 (not 403) for customers outside the caller's scope, so existence is not leaked."""
    stmt = select(Customer).where(Customer.id == customer_id)
    scope = customer_scope(db, user)
    if scope is not None:
        stmt = stmt.where(scope)
    customer = db.scalar(stmt)
    if customer is None:
        raise HTTPException(404, "Customer not found")
    return customer


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
