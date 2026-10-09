import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require
from app.api.schemas import (
    AliasIn, AreaIn, AreaOut, AreaUpdate, PackageIn, PackageOut, PackageUpdate, StreetIn, StreetOut,
)
from app.core.db import get_db
from app.models import Area, CollectorAreaAssignment, Customer, Package, PackageAlias, Street, User
from app.services import audit
from app.services.customers import normalize_alias

router = APIRouter(tags=["master-data"])


# ------------------------------------------------------------------ areas / streets
@router.post("/areas", response_model=AreaOut, status_code=201)
def create_area(body: AreaIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("area.manage"))):
    area = Area(**body.model_dump())
    db.add(area)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An area with this name already exists")
    audit.log(db, user_id=user.id, action="area.create", entity="area", entity_id=area.id,
              after=body.model_dump(), request=request)
    db.commit()
    return area


@router.get("/areas", response_model=list[AreaOut])
def list_areas(db: Session = Depends(get_db),
               _: User = Depends(require("area.view", "area.manage"))):
    return list(db.scalars(select(Area).where(Area.deleted_at.is_(None)).order_by(Area.name)))


@router.patch("/areas/{area_id}", response_model=AreaOut)
def update_area(area_id: uuid.UUID, body: AreaUpdate, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("area.manage"))):
    area = db.get(Area, area_id)
    if area is None or area.deleted_at is not None:
        raise HTTPException(404, "Area not found")
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(area, k) for k in changes}
    for key, value in changes.items():
        setattr(area, key, value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An area with this name already exists")
    audit.log(db, user_id=user.id, action="area.update", entity="area", entity_id=area.id,
              before=before, after=changes, request=request)
    db.commit()
    return area


@router.delete("/areas/{area_id}", status_code=204)
def delete_area(area_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("area.manage"))):
    """Removes an area from lists. Refused while customers or collectors still use it."""
    area = db.get(Area, area_id)
    if area is None or area.deleted_at is not None:
        raise HTTPException(404, "Area not found")
    customers = db.scalar(select(func.count()).select_from(Customer)
                          .where(Customer.area_id == area_id, Customer.status != "ARCHIVED")) or 0
    collectors = db.scalar(select(func.count()).select_from(CollectorAreaAssignment)
                           .where(CollectorAreaAssignment.area_id == area_id)) or 0
    if customers or collectors:
        raise HTTPException(409, f"This area is still used by {customers} customer(s) and {collectors} collector(s). "
                                 "Move them first.")
    area.deleted_at = datetime.now(UTC)
    audit.log(db, user_id=user.id, action="area.delete", entity="area", entity_id=area.id,
              before={"name": area.name}, request=request)
    db.commit()

def create_street(body: StreetIn, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require("area.manage"))):
    if db.get(Area, body.area_id) is None:
        raise HTTPException(422, "Unknown area")
    street = Street(**body.model_dump())
    db.add(street)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This street already exists in the area")
    audit.log(db, user_id=user.id, action="street.create", entity="street", entity_id=street.id,
              after=body.model_dump(), request=request)
    db.commit()
    return street


@router.get("/areas/{area_id}/streets", response_model=list[StreetOut])
def list_streets(area_id: uuid.UUID, db: Session = Depends(get_db),
                 _: User = Depends(require("area.view", "area.manage"))):
    return list(db.scalars(
        select(Street).where(Street.area_id == area_id, Street.deleted_at.is_(None)).order_by(Street.name)
    ))


# ------------------------------------------------------------------ packages
def _pkg_out(p: Package) -> PackageOut:
    fields = {f: getattr(p, f) for f in PackageOut.model_fields if f != "aliases"}
    return PackageOut(**fields, aliases=sorted(a.alias for a in p.aliases))


@router.post("/packages", response_model=PackageOut, status_code=201)
def create_package(body: PackageIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require("package.manage"))):
    data = body.model_dump(exclude={"aliases"})
    pkg = Package(**data)
    # The display name and code are always resolvable aliases ("Star 3" / "Star3" -> same key).
    names = {body.display_name, body.code, body.name, *body.aliases}
    seen: set[str] = set()
    for a in names:
        key = normalize_alias(a)
        if key and key not in seen:
            seen.add(key)
            pkg.aliases.append(PackageAlias(alias=a, alias_normalized=key, source="manual"))
    db.add(pkg)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Package code or alias already exists")
    audit.log(db, user_id=user.id, action="package.create", entity="package", entity_id=pkg.id,
              after=body.model_dump(), request=request)
    db.commit()
    return _pkg_out(pkg)


@router.get("/packages", response_model=list[PackageOut])
def list_packages(include_inactive: bool = False, db: Session = Depends(get_db),
                  _: User = Depends(require("package.view", "package.manage"))):
    stmt = select(Package).where(Package.deleted_at.is_(None)).order_by(Package.code)
    if not include_inactive:
        stmt = stmt.where(Package.status == "ACTIVE")
    return [_pkg_out(p) for p in db.scalars(stmt)]


@router.get("/packages/{package_id}", response_model=PackageOut)
def get_package(package_id: uuid.UUID, db: Session = Depends(get_db),
                _: User = Depends(require("package.view", "package.manage"))):
    pkg = db.get(Package, package_id)
    if pkg is None or pkg.deleted_at:
        raise HTTPException(404, "Package not found")
    return _pkg_out(pkg)


@router.patch("/packages/{package_id}", response_model=PackageOut)
def update_package(package_id: uuid.UUID, body: PackageUpdate, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(require("package.manage"))):
    pkg = db.get(Package, package_id)
    if pkg is None or pkg.deleted_at:
        raise HTTPException(404, "Package not found")
    fields = body.model_dump(exclude_unset=True)
    before = {k: getattr(pkg, k) for k in fields}
    for k, v in fields.items():
        setattr(pkg, k, v)
    db.flush()
    audit.log(db, user_id=user.id, action="package.update", entity="package", entity_id=pkg.id,
              before=before, after=fields, request=request)
    db.commit()
    return _pkg_out(pkg)


@router.post("/packages/{package_id}/aliases", response_model=PackageOut, status_code=201)
def add_alias(package_id: uuid.UUID, body: AliasIn, request: Request,
              db: Session = Depends(get_db), user: User = Depends(require("package.manage"))):
    pkg = db.get(Package, package_id)
    if pkg is None or pkg.deleted_at:
        raise HTTPException(404, "Package not found")
    key = normalize_alias(body.alias)
    if not key:
        raise HTTPException(422, "Alias is empty")
    pkg.aliases.append(PackageAlias(alias=body.alias.strip(), alias_normalized=key, source=body.source))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Alias already maps to a package")
    audit.log(db, user_id=user.id, action="package.alias_add", entity="package", entity_id=pkg.id,
              after={"alias": body.alias}, request=request)
    db.commit()
    return _pkg_out(pkg)


@router.delete("/packages/{package_id}", status_code=204)
def archive_package(package_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("package.manage"))):
    """Soft-delete: existing connections keep their package reference."""
    pkg = db.get(Package, package_id)
    if pkg is None or pkg.deleted_at:
        raise HTTPException(404, "Package not found")
    pkg.deleted_at = datetime.now(UTC)
    pkg.status = "INACTIVE"
    audit.log(db, user_id=user.id, action="package.archive", entity="package", entity_id=pkg.id,
              request=request)
    db.commit()
