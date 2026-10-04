import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings

GOOD_KEY = Fernet.generate_key().decode()


def test_weak_secret_key_rejected():
    with pytest.raises(ValidationError):
        Settings(secret_key="short", field_encryption_keys=GOOD_KEY)


def test_malformed_encryption_key_rejected():
    with pytest.raises(ValidationError):
        Settings(secret_key="x" * 40, field_encryption_keys="not-a-fernet-key")
    with pytest.raises(ValidationError):
        Settings(secret_key="x" * 40, field_encryption_keys="")


def test_key_rotation_list_accepted_and_old_data_still_decrypts(monkeypatch):
    from app.core import security
    from app.core.config import get_settings

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    base = get_settings()
    monkeypatch.setattr(base, "field_encryption_keys", old)
    token = security.encrypt_text("35202-1234567-1")
    monkeypatch.setattr(base, "field_encryption_keys", f"{new},{old}")  # new first, old kept
    assert security.decrypt_text(token) == "35202-1234567-1"
    assert security.decrypt_text(security.encrypt_text("x")) == "x"
    monkeypatch.setattr(base, "field_encryption_keys", new)  # old key dropped: unreadable
    with pytest.raises(Exception):
        security.decrypt_text(token)
