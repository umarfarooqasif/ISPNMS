import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core import constants as C
from app.models.base import Base, EncryptedString, Money, TimestampMixin, uuid_pk


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class Area(Base, TimestampMixin):
    __tablename__ = "areas"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_ur: Mapped[str | None] = mapped_column(String(120))
    code: Mapped[str | None] = mapped_column(String(32))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("uq_areas_name_lower", func.lower(name), unique=True),)


class Street(Base, TimestampMixin):
    __tablename__ = "streets"

    id: Mapped[uuid.UUID] = uuid_pk()
    area_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("areas.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_ur: Mapped[str | None] = mapped_column(String(120))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("area_id", "name"),)


class Package(Base, TimestampMixin):
    """Database-driven packages. Names and prices are never hardcoded in code."""

    __tablename__ = "packages"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name_ur: Mapped[str | None] = mapped_column(String(120))
    speed_mbps: Mapped[int | None] = mapped_column(SmallInteger)
    monthly_price: Mapped[Decimal | None] = mapped_column(Money)
    cable_price: Mapped[Decimal | None] = mapped_column(Money)
    internet_price: Mapped[Decimal | None] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    description: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    aliases: Mapped[list["PackageAlias"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(_in("status", C.PACKAGE_STATUSES), name="status"),
        CheckConstraint(
            "(monthly_price IS NULL OR monthly_price >= 0) AND "
            "(cable_price IS NULL OR cable_price >= 0) AND "
            "(internet_price IS NULL OR internet_price >= 0)",
            name="prices_non_negative",
        ),
    )


class PackageAlias(Base):
    """Maps source strings such as 'Star3' to a package. Unknown aliases surface in import review."""

    __tablename__ = "package_aliases"

    id: Mapped[uuid.UUID] = uuid_pk()
    package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(120), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    source: Mapped[str | None] = mapped_column(String(32))

    package: Mapped[Package] = relationship(back_populates="aliases")


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # Only full_name is required. The existing PDF has no CNIC and many missing fields.
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name_ur: Mapped[str | None] = mapped_column(String(200))
    father_name: Mapped[str | None] = mapped_column(String(200))
    cnic: Mapped[str | None] = mapped_column(EncryptedString)
    mobile: Mapped[str | None] = mapped_column(String(32))
    mobile_normalized: Mapped[str | None] = mapped_column(String(20), index=True)
    whatsapp: Mapped[str | None] = mapped_column(String(32))
    alt_contact: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(Text)
    address_ur: Mapped[str | None] = mapped_column(Text)
    area_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("areas.id"), index=True)
    street_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("streets.id"))
    house_no: Mapped[str | None] = mapped_column(String(64))
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    connections: Mapped[list["Connection"]] = relationship(back_populates="customer")

    __table_args__ = (
        # Created in migration 0002 (needs the pg_trgm extension); declared here so
        # `alembic check` stays clean.
        Index(
            "ix_customers_full_name_trgm",
            "full_name",
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_customers_address_trgm",
            "address",
            postgresql_using="gin",
            postgresql_ops={"address": "gin_trgm_ops"},
        ),
        CheckConstraint(_in("status", C.CUSTOMER_STATUSES), name="status"),
        CheckConstraint(
            "(lat IS NULL OR lat BETWEEN -90 AND 90) AND (lng IS NULL OR lng BETWEEN -180 AND 180)",
            name="gps_range",
        ),
    )


class CustomFieldDef(Base, TimestampMixin):
    """Admin-configurable extra customer fields (no schema change needed)."""

    __tablename__ = "custom_field_defs"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    field_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    required: Mapped[bool] = mapped_column(nullable=False, default=False)

    __table_args__ = (
        CheckConstraint(
            "field_type IN ('text','number','date','boolean','choice')", name="field_type"
        ),
    )


class CustomerCustomValue(Base):
    __tablename__ = "customer_custom_values"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("custom_field_defs.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)


class Connection(Base, TimestampMixin):
    """A service line. One customer may have many connections."""

    __tablename__ = "connections"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    connection_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    internet_id: Mapped[str | None] = mapped_column(String(64), index=True)
    username: Mapped[str | None] = mapped_column(String(128), index=True)
    package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("packages.id"))
    connection_type: Mapped[str] = mapped_column(String(16), nullable=False)
    install_date: Mapped[date | None] = mapped_column(Date)
    # Wasooli "Recharge Date", kept exactly as exported. It is the NEXT DUE DATE (confirmed).
    source_recharge_date: Mapped[date | None] = mapped_column(Date)
    # The billing cycle driver: the due date of the next cycle to invoice. Starts as the imported
    # recharge date and moves forward one month every time a cycle is invoiced.
    next_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", index=True)
    monthly_price_override: Mapped[Decimal | None] = mapped_column(Money)
    billing_day: Mapped[int | None] = mapped_column(SmallInteger)
    area_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("areas.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship(back_populates="connections")
    service_lines: Mapped[list["ConnectionServiceLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    external_refs: Mapped[list["ExternalRef"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(_in("connection_type", C.CONNECTION_TYPES), name="connection_type"),
        CheckConstraint(_in("status", C.CONNECTION_STATUSES), name="status"),
        CheckConstraint("billing_day IS NULL OR billing_day BETWEEN 1 AND 31", name="billing_day"),
        CheckConstraint(
            "monthly_price_override IS NULL OR monthly_price_override >= 0",
            name="override_non_negative",
        ),
    )


class ConnectionServiceLine(Base):
    """Cable and internet are separate lines so combined connections keep separate amounts."""

    __tablename__ = "connection_service_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service: Mapped[str] = mapped_column(String(16), nullable=False)
    package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("packages.id"))
    price: Mapped[Decimal | None] = mapped_column(Money)

    __table_args__ = (
        CheckConstraint("service IN ('CABLE','INTERNET')", name="service"),
        CheckConstraint("price IS NULL OR price >= 0", name="price_non_negative"),
        UniqueConstraint("connection_id", "service"),
    )


class ExternalRef(Base):
    """Preserves source-system IDs (Wasooli ID, Internet ID, Zalpro, MikroTik) for matching."""

    __tablename__ = "external_refs"

    id: Mapped[uuid.UUID] = uuid_pk()
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system: Mapped[str] = mapped_column(String(16), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        CheckConstraint(_in("system", C.EXTERNAL_SYSTEMS), name="system"),
        CheckConstraint(_in("ref_type", C.EXTERNAL_REF_TYPES), name="ref_type"),
        UniqueConstraint("system", "ref_type", "value"),
    )
