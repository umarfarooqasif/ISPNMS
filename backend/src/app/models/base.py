import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, MetaData, Numeric, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.core.security import decrypt_text, encrypt_text

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


# Money is always NUMERIC(12,2) / Decimal. Never float.
Money = Numeric(12, 2)


class EncryptedString(TypeDecorator):
    """Application-level encryption for sensitive columns (e.g. CNIC)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt_text(value)

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt_text(value)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = ["Base", "Money", "EncryptedString", "uuid_pk", "TimestampMixin", "Decimal"]
