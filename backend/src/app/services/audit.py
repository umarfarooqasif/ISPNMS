import json
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog

# Never written to audit logs in clear text.
SENSITIVE_KEYS = {"cnic", "password", "password_hash", "totp_secret_enc", "token", "refresh_token"}


def _clean(value: Any) -> Any:
    if value is None:
        return None
    raw = json.loads(json.dumps(value, default=str))
    return _mask(raw)


def _mask(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: ("<redacted>" if k in SENSITIVE_KEYS and v is not None else _mask(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_mask(v) for v in obj]
    return obj


def log(
    db: Session,
    *,
    user_id: uuid.UUID | None,
    action: str,
    entity: str | None = None,
    entity_id: Any = None,
    before: Any = None,
    after: Any = None,
    request: Request | None = None,
) -> None:
    """Writes an audit row inside the caller's transaction (so it commits or rolls back with it)."""
    ip = device = None
    if request is not None:
        ip = request.client.host if request.client else None
        device = (request.headers.get("user-agent") or "")[:300] or None
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=_clean(before),
            after=_clean(after),
            ip=ip,
            device=device,
        )
    )
