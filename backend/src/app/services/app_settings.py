"""Business settings that an administrator can change in the web app instead of editing a file.

A saved value overrides the server-file default (the .env value); removing the saved value goes back
to the default. Validation is strict and explained in plain words, because these settings control
money (late fees) and billing timing.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # database types are only needed for annotations, so the pure logic imports cleanly
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Spec:
    key: str
    kind: str                       # "int" | "money" | "choice" | "text"
    label: str
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()
    max_length: int = 200


SPECS: dict[str, Spec] = {s.key: s for s in (
    Spec("billing.lead_days", "int", "Days ahead to bill", 0, 60),
    Spec("late_fee.amount", "money", "Late fee per overdue bill"),
    Spec("late_fee.grace_days", "int", "Grace days before a late fee", 0, 90),
    Spec("late_fee.due_days", "int", "Days to pay a late fee", 0, 90),
    Spec("import.recharge_date_means", "choice", "What the Wasooli recharge date means",
         choices=("NEXT_DUE", "LAST_RECHARGE")),
    Spec("company.name", "text", "Business name", max_length=120),
    Spec("company.phone", "text", "Business phone", max_length=40),
    Spec("company.address", "text", "Business address", max_length=200),
)}

MAX_FEE = Decimal("1000000")


class SettingError(ValueError):
    """A setting value that cannot be accepted. The message is shown to the administrator."""


def validate(key: str, raw: Any) -> Any:
    """Returns the cleaned value to store, or raises SettingError. The stored form is JSON-safe:
    integers stay integers and money is kept as an exact decimal string."""
    spec = SPECS.get(key)
    if spec is None:
        raise SettingError(f"Unknown setting: {key}")
    if spec.kind == "int":
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise SettingError(f"{spec.label}: enter a whole number.")
        text = str(raw).strip()
        if not re.fullmatch(r"\d{1,4}", text):
            raise SettingError(f"{spec.label}: enter a whole number.")
        value = int(text)
        if not (spec.minimum <= value <= spec.maximum):  # type: ignore[operator]
            raise SettingError(f"{spec.label}: use a number from {spec.minimum} to {spec.maximum}.")
        return value
    if spec.kind == "money":
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise SettingError(f"{spec.label}: enter an amount such as 100 or 100.50.")
        text = str(raw).strip()
        if not re.fullmatch(r"\d{1,9}(\.\d{1,2})?", text):
            raise SettingError(f"{spec.label}: enter an amount such as 100 or 100.50 (0 switches it off).")
        amount = Decimal(text)
        if amount > MAX_FEE:
            raise SettingError(f"{spec.label}: that is too large.")
        return str(amount.quantize(Decimal("0.01")))
    if spec.kind == "choice":
        if raw not in spec.choices:
            raise SettingError(f"{spec.label}: choose one of {', '.join(spec.choices)}.")
        return raw
    if not isinstance(raw, str):
        raise SettingError(f"{spec.label}: enter text.")
    text = " ".join(raw.split())
    if len(text) > spec.max_length:
        raise SettingError(f"{spec.label}: at most {spec.max_length} characters.")
    return text


def server_defaults() -> dict[str, Any]:
    """What applies when nothing is saved: the values from the server's .env file."""
    from app.core.config import get_settings

    s = get_settings()
    return {
        "billing.lead_days": s.billing_lead_days,
        "late_fee.amount": str(Decimal(s.late_fee_amount).quantize(Decimal("0.01"))),
        "late_fee.grace_days": s.late_fee_grace_days,
        "late_fee.due_days": s.late_fee_due_days,
        "import.recharge_date_means": s.recharge_date_means,
        "company.name": "",
        "company.phone": "",
        "company.address": "",
    }


@dataclass(frozen=True)
class Effective:
    billing_lead_days: int
    late_fee_amount: Decimal
    late_fee_grace_days: int
    late_fee_due_days: int
    recharge_date_means: str
    company_name: str
    company_phone: str
    company_address: str


def merged(saved: dict[str, Any]) -> dict[str, Any]:
    """Saved values over the defaults. A saved value that is no longer valid is ignored (the default
    is used) rather than breaking billing."""
    out = server_defaults()
    for key, raw in saved.items():
        try:
            out[key] = validate(key, raw)
        except SettingError:
            continue
    return out


def to_effective(values: dict[str, Any]) -> Effective:
    return Effective(
        billing_lead_days=int(values["billing.lead_days"]),
        late_fee_amount=Decimal(values["late_fee.amount"]),
        late_fee_grace_days=int(values["late_fee.grace_days"]),
        late_fee_due_days=int(values["late_fee.due_days"]),
        recharge_date_means=str(values["import.recharge_date_means"]),
        company_name=str(values["company.name"]),
        company_phone=str(values["company.phone"]),
        company_address=str(values["company.address"]),
    )


def saved_values(db: Session) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models import AppSetting

    return {row.key: row.value for row in db.scalars(select(AppSetting))}


def effective(db: Session) -> Effective:
    """The settings billing, late fees and imports should use right now."""
    return to_effective(merged(saved_values(db)))


def apply_changes(db: Session, changes: dict[str, Any], user_id: uuid.UUID | None) -> tuple[dict, dict]:
    """Saves changes. A value of None removes the saved value (back to the default).
    All-or-nothing: if any value is invalid nothing is saved. Returns (before, after) of what changed."""
    from sqlalchemy import select

    from app.models import AppSetting

    cleaned: dict[str, Any] = {}
    for key, raw in changes.items():
        cleaned[key] = None if raw is None else validate(key, raw)
    existing = {row.key: row for row in db.scalars(select(AppSetting))}
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for key, value in cleaned.items():
        row = existing.get(key)
        old = row.value if row else None
        if value is None:
            if row is not None:
                db.delete(row)
                before[key], after[key] = old, None
        elif row is None:
            db.add(AppSetting(key=key, value=value, updated_by=user_id))
            before[key], after[key] = None, value
        elif row.value != value:
            row.value = value
            row.updated_by = user_id
            before[key], after[key] = old, value
    db.flush()
    return before, after
