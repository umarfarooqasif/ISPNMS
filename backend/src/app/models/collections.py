import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core import constants as C
from app.models.base import Base, TimestampMixin, uuid_pk
from app.models.masters import _in


class Collector(Base, TimestampMixin):
    __tablename__ = "collectors"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")

    __table_args__ = (CheckConstraint(_in("status", C.COLLECTOR_STATUSES), name="status"),)


class CollectorAreaAssignment(Base):
    __tablename__ = "collector_area_assignments"

    collector_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collectors.id", ondelete="CASCADE"), primary_key=True
    )
    area_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("areas.id"), primary_key=True)


class CollectorCustomerAssignment(Base):
    __tablename__ = "collector_customer_assignments"

    collector_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collectors.id", ondelete="CASCADE"), primary_key=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), primary_key=True)
    # Ordered customer lists / collection routes.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
