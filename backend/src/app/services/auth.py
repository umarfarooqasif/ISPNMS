import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.models import LoginHistory, RefreshToken, User
from app.services import audit


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _issue_tokens(db: Session, user: User, family_id: uuid.UUID, ip: str | None) -> dict:
    s = get_settings()
    refresh = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh),
            family_id=family_id,
            expires_at=datetime.now(UTC) + timedelta(days=s.refresh_token_days),
            ip=ip,
        )
    )
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": s.access_token_minutes * 60,
    }


def login(db: Session, username: str, password: str, request) -> dict:
    s = get_settings()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "")[:300] or None
    now = datetime.now(UTC)

    user = db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))

    def record(success: bool):
        db.add(
            LoginHistory(
                user_id=user.id if user else None,
                username_attempted=username[:64],
                success=success,
                ip=ip,
                user_agent=ua,
            )
        )

    if user is None:
        verify_password(DUMMY_HASH, password)  # keep timing similar
        record(False)
        db.commit()
        raise AuthError("Invalid username or password")

    if user.locked_until and user.locked_until > now:
        record(False)
        db.commit()
        raise AuthError("Account temporarily locked. Try again later.", 423)

    if not user.is_active or not verify_password(user.password_hash, password):
        if user.is_active:
            user.failed_attempts += 1
            if user.failed_attempts >= s.max_failed_logins:
                user.locked_until = now + timedelta(minutes=s.lockout_minutes)
                user.failed_attempts = 0
        record(False)
        db.commit()  # persist the failure even though we raise
        raise AuthError("Invalid username or password")

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    tokens = _issue_tokens(db, user, uuid.uuid4(), ip)
    record(True)
    audit.log(db, user_id=user.id, action="auth.login", entity="user", entity_id=user.id, request=request)
    db.commit()
    return tokens


def refresh(db: Session, token: str, request) -> dict:
    ip = request.client.host if request.client else None
    row = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)).with_for_update()
    )
    if row is None:
        raise AuthError("Invalid refresh token")

    now = datetime.now(UTC)
    if row.revoked_at is not None:
        # A rotated/revoked token was presented again: assume theft, kill the whole family.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        audit.log(
            db, user_id=row.user_id, action="auth.refresh_reuse_detected",
            entity="user", entity_id=row.user_id, request=request,
        )
        db.commit()
        raise AuthError("Invalid refresh token")

    user = db.get(User, row.user_id)
    if row.expires_at <= now or user is None or not user.is_active:
        raise AuthError("Invalid refresh token")

    row.revoked_at = now
    tokens = _issue_tokens(db, user, row.family_id, ip)
    db.commit()
    return tokens


def logout(db: Session, token: str, request) -> None:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)))
    if row is None:
        return
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    audit.log(db, user_id=row.user_id, action="auth.logout", entity="user", entity_id=row.user_id, request=request)
    db.commit()
