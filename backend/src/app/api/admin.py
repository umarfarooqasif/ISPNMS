import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import current_user, has_perm, require
from app.api.schemas import AuditOut, PasswordSet, UserCreate, UserOut, UserUpdate
from app.core.db import get_db
from app.core.security import hash_password
from app.models import AuditLog, RefreshToken, Role, User
from app.services import audit
from app.services.rbac import PERMISSIONS, create_user

router = APIRouter(tags=["admin"])


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id, username=u.username, full_name=u.full_name, email=u.email,
        is_active=u.is_active, role_codes=sorted(r.code for r in u.roles),
    )


def _resolve_roles(db: Session, actor: User, codes: list[str]) -> list[Role]:
    if "super_admin" in codes and not has_perm(actor, "role.manage"):
        raise HTTPException(403, "Only a super admin can grant the super_admin role")
    roles = list(db.scalars(select(Role).where(Role.code.in_(codes)))) if codes else []
    if len(roles) != len(set(codes)):
        raise HTTPException(422, "Unknown role code")
    return roles


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), _: User = Depends(require("user.manage", "role.manage"))):
    return [
        {"code": r.code, "name": r.name, "permissions": sorted(p.code for p in r.permissions)}
        for r in db.scalars(select(Role).order_by(Role.code))
    ]


@router.get("/permissions")
def list_permissions(_: User = Depends(require("user.manage", "role.manage"))):
    return [{"code": c, "description": d} for c, d in sorted(PERMISSIONS.items())]


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require("user.manage"))):
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user_ep(
    body: UserCreate, request: Request, db: Session = Depends(get_db),
    actor: User = Depends(require("user.manage")),
):
    _resolve_roles(db, actor, body.role_codes)
    try:
        user = create_user(
            db, username=body.username, password=body.password, full_name=body.full_name,
            role_codes=body.role_codes, email=body.email,
        )
        audit.log(
            db, user_id=actor.id, action="user.create", entity="user", entity_id=user.id,
            after={"username": user.username, "roles": body.role_codes}, request=request,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username already exists")
    return _user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID, body: UserUpdate, request: Request, db: Session = Depends(get_db),
    actor: User = Depends(require("user.manage")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    # Only a super admin may modify a super admin account.
    if any(r.code == "super_admin" for r in user.roles) and not has_perm(actor, "role.manage"):
        raise HTTPException(403, "Only a super admin can modify a super admin")
    if body.is_active is False and user.id == actor.id:
        raise HTTPException(409, "You cannot deactivate your own account")

    before = {"full_name": user.full_name, "email": user.email, "is_active": user.is_active,
              "roles": sorted(r.code for r in user.roles)}
    data = body.model_dump(exclude_unset=True)
    if "role_codes" in data and data["role_codes"] is not None:
        user.roles = _resolve_roles(db, actor, data["role_codes"])
    for f in ("full_name", "email", "is_active"):
        if f in data and data[f] is not None:
            setattr(user, f, data[f])
    if data.get("is_active") is False:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    db.flush()
    after = {"full_name": user.full_name, "email": user.email, "is_active": user.is_active,
             "roles": sorted(r.code for r in user.roles)}
    audit.log(db, user_id=actor.id, action="user.update", entity="user", entity_id=user.id,
              before=before, after=after, request=request)
    db.commit()
    return _user_out(user)


@router.post("/users/{user_id}/password", status_code=204)
def set_password(
    user_id: uuid.UUID, body: PasswordSet, request: Request, db: Session = Depends(get_db),
    actor: User = Depends(require("user.manage")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if any(r.code == "super_admin" for r in user.roles) and not has_perm(actor, "role.manage"):
        raise HTTPException(403, "Only a super admin can modify a super admin")
    user.password_hash = hash_password(body.password)
    user.failed_attempts = 0
    user.locked_until = None
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    audit.log(db, user_id=actor.id, action="user.password_set", entity="user", entity_id=user.id,
              request=request)
    db.commit()


@router.get("/audit-logs", response_model=list[AuditOut])
def audit_logs(
    entity: str | None = None, entity_id: str | None = None, user_id: uuid.UUID | None = None,
    action: str | None = None, limit: int = 100, offset: int = 0,
    db: Session = Depends(get_db), _: User = Depends(require("audit.view")),
):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return list(db.scalars(stmt.limit(min(max(limit, 1), 500)).offset(max(offset, 0))))


__all__ = ["router", "func", "current_user"]
