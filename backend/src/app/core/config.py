from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+psycopg://isp:isp@localhost:5432/isp"
    # Required: no insecure defaults for secrets.
    secret_key: str
    # Comma-separated Fernet keys. First key encrypts, all keys can decrypt (rotation).
    field_encryption_keys: str

    access_token_minutes: int = 15
    refresh_token_days: int = 14
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    timezone: str = "Asia/Karachi"
    receipt_prefix: str = "RC"
    invoice_prefix: str = "INV"
    storage_dir: str = "/data/storage"
    # Interactive API docs expose the API surface, so they are off unless explicitly enabled.
    enable_docs: bool = False

    # First-run bootstrap (used by the seed script only).
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str | None = None


    @field_validator("secret_key")
    @classmethod
    def _strong_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v

    @field_validator("field_encryption_keys")
    @classmethod
    def _valid_fernet_keys(cls, v: str) -> str:
        keys = [k.strip() for k in v.split(",") if k.strip()]
        if not keys:
            raise ValueError("FIELD_ENCRYPTION_KEYS must contain at least one key")
        for k in keys:
            try:
                Fernet(k.encode())
            except Exception as exc:
                raise ValueError(
                    "FIELD_ENCRYPTION_KEYS must be valid Fernet keys "
                    "(openssl rand -base64 32 | tr '+/' '-_')"
                ) from exc
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
