"""Import tracking tables only. The parser/importer itself is Phase 2."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core import constants as C
from app.models.base import Base, TimestampMixin, uuid_pk
from app.models.masters import _in


class ImportSession(Base, TimestampMixin):
    __tablename__ = "import_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_system: Mapped[str] = mapped_column(String(16), nullable=False, default="WASOOLI")
    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="UPLOADED")
    parser_version: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[dict | None] = mapped_column(JSONB)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint(_in("status", C.IMPORT_SESSION_STATUSES), name="status"),)


class ImportRow(Base):
    __tablename__ = "import_rows"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page: Mapped[int | None] = mapped_column(Integer)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Exactly what was extracted vs what the system proposes to store.
    raw_cells: Mapped[dict | None] = mapped_column(JSONB)
    normalized: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="REVIEW", index=True)
    issues: Mapped[list | None] = mapped_column(JSONB)
    match_candidates: Mapped[list | None] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    row_hash: Mapped[str | None] = mapped_column(String(64))
    result_customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    result_connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("connections.id"))

    __table_args__ = (
        CheckConstraint(_in("status", C.IMPORT_ROW_STATUSES), name="status"),
        UniqueConstraint("session_id", "row_index"),
    )


class ImportRowDecision(Base):
    __tablename__ = "import_row_decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    row_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_rows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    edited_values: Mapped[dict | None] = mapped_column(JSONB)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (CheckConstraint(_in("decision", C.IMPORT_DECISIONS), name="decision"),)
