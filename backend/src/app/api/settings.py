"""Business settings: read, change, and the business details printed on receipts."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user, require
from app.core.db import get_db
from app.models import User
from app.services import app_settings as cfg
from app.services import audit

router = APIRouter(tags=["settings"])


class SettingsOut(BaseModel):
    values: dict[str, Any]       # what applies right now
    defaults: dict[str, Any]     # the server-file (.env) values
    overridden: list[str]        # settings that have a saved value
    labels: dict[str, str]


class SettingsIn(BaseModel):
    values: dict[str, Any]       # key -> new value; null removes the saved value (back to the default)


class CompanyOut(BaseModel):
    name: str
    phone: str
    address: str


def _state(db: Session) -> SettingsOut:
    saved = cfg.saved_values(db)
    valid_saved = []
    for key, raw in saved.items():
        try:
            cfg.validate(key, raw)
            valid_saved.append(key)
        except cfg.SettingError:
            pass
    return SettingsOut(
        values=cfg.merged(saved), defaults=cfg.server_defaults(), overridden=sorted(valid_saved),
        labels={k: s.label for k, s in cfg.SPECS.items()},
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings_state(db: Session = Depends(get_db), user: User = Depends(require("settings.manage"))):
    return _state(db)


@router.put("/settings", response_model=SettingsOut)
def change_settings(body: SettingsIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("settings.manage"))):
    """All-or-nothing: if any value is invalid, nothing is saved."""
    if not body.values:
        raise HTTPException(422, "Nothing to change.")
    try:
        before, after = cfg.apply_changes(db, body.values, user.id)
    except cfg.SettingError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    if after:
        audit.log(db, user_id=user.id, action="settings.update", entity="settings",
                  before=before, after=after, request=request)
    db.commit()
    return _state(db)


@router.get("/settings/company", response_model=CompanyOut)
def company_details(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The business name, phone and address printed on receipts. Any logged-in user may read these."""
    e = cfg.effective(db)
    return CompanyOut(name=e.company_name, phone=e.company_phone, address=e.company_address)
