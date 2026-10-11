"""Changing the package (and price) of one service on a connection."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.customers import _load_connection
from app.api.deps import require
from app.api.schemas import Amount, ConnectionOut
from app.core.db import get_db
from app.models import ConnectionServiceLine, Package, User
from app.services import audit

router = APIRouter(tags=["connections"])


class ChangePackageIn(BaseModel):
    service: Literal["INTERNET", "CABLE"]
    package_id: uuid.UUID | None = None
    price: Amount | None = Field(default=None, ge=0)   # empty = use the package's own price
    reason: str = Field(min_length=3, max_length=300)


@router.post("/connections/{connection_id}/package", response_model=ConnectionOut)
def change_package(connection_id: uuid.UUID, body: ChangePackageIn, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(require("connection.update"))):
    """Moves one service to another package or price. It applies from the NEXT bill: bills that
    already exist are never changed."""
    conn = _load_connection(db, user, connection_id)
    if body.package_id is None and body.price is None:
        raise HTTPException(422, "Choose a package or enter a price.")
    if (body.service == "CABLE" and conn.connection_type == "INTERNET") or \
            (body.service == "INTERNET" and conn.connection_type == "CABLE"):
        raise HTTPException(422, f"This is a {conn.connection_type.lower()} connection: it has no "
                                 f"{body.service.lower()} service to change.")
    if body.package_id is not None:
        pkg = db.get(Package, body.package_id)
        if pkg is None or getattr(pkg, "deleted_at", None) is not None:
            raise HTTPException(422, "Unknown package")
        if pkg.status != "ACTIVE":
            raise HTTPException(422, "That package is inactive. Choose an active one.")

    line = next((ln for ln in conn.service_lines if ln.service == body.service), None)
    before = {"service": body.service, "package_id": line.package_id if line else None,
              "price": line.price if line else None}
    if line is None:
        line = ConnectionServiceLine(connection_id=conn.id, service=body.service)
        db.add(line)
    line.package_id = body.package_id
    line.price = body.price
    main_service = "CABLE" if conn.connection_type == "CABLE" else "INTERNET"
    if body.service == main_service and body.package_id is not None:
        conn.package_id = body.package_id   # keep the connection's main package in step
    db.flush()
    audit.log(db, user_id=user.id, action="connection.package_change", entity="connection", entity_id=conn.id,
              before=before, after={"service": body.service, "package_id": body.package_id, "price": body.price,
                                    "reason": body.reason.strip()}, request=request)
    db.commit()
    db.expire(conn, ["service_lines"])
    return conn
