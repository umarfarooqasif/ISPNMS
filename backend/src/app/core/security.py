import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, MultiFernet

from app.core.config import get_settings

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# Used to keep login timing similar when the username does not exist.
DUMMY_HASH = _ph.hash("not-a-real-password")


def create_access_token(user_id: uuid.UUID) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
        "typ": "access",
    }
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        if data.get("typ") != "access":
            return None
        return uuid.UUID(data["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in get_settings().field_encryption_keys.split(",") if k.strip()]
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
