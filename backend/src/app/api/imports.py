import hashlib
import uuid
from pathlib import Path
from typing import Literal

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core import constants as C
from app.core.config import get_settings
from app.core.db import get_db
from app.models import ImportRow, ImportRowDecision, ImportSession, User
from app.services import audit, importer

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_system: str
    file_name: str
    file_size: int
    status: str
    parser_version: str | None
    summary: dict | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class RowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    page: int | None
    row_index: int
    status: str
    raw_cells: dict | None
    normalized: dict | None
    issues: list | None
    match_candidates: list | None
    result_customer_id: uuid.UUID | None
    result_connection_id: uuid.UUID | None


class DecisionIn(BaseModel):
    decision: Literal["IMPORT", "SKIP", "UPDATE_EXISTING", "CREATE_SEPARATE", "MANUAL_EDIT"]
    # MANUAL_EDIT: any normalised field to override (full_name, mobile, area, services, ...).
    # UPDATE_EXISTING on a possible-duplicate row: {"customer_id": "<uuid>"} to attach to them.
    edited_values: dict | None = None


class BulkDecisionIn(BaseModel):
    status: Literal["NEW", "REVIEW", "UPDATED"]
    decision: Literal["IMPORT", "SKIP", "UPDATE_EXISTING", "CREATE_SEPARATE"]
    issue_code: str | None = None


class CommitIn(BaseModel):
    dry_run: bool = True          # safe by default: preview first, then send dry_run=false
    include_review: bool = False  # import "possible duplicate" rows as separate customers


def _load(db: Session, session_id: uuid.UUID) -> ImportSession:
    sess = db.get(ImportSession, session_id)
    if sess is None:
        raise HTTPException(404, "Import not found")
    return sess


@router.post("/wasooli", response_model=SessionOut, status_code=202)
async def upload_wasooli(
    request: Request, background: BackgroundTasks, file: UploadFile = File(...),
    force: bool = Query(False, description="Upload even if this exact file was uploaded before"),
    db: Session = Depends(get_db), user: User = Depends(require("import.upload")),
):
    """Stores the PDF and parses it in the background (about 30 s for 1,250 customers).
    Poll GET /imports/{id} until status is MATCHED or IN_REVIEW (or FAILED)."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 50 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(422, "That is not a PDF file")
    digest = hashlib.sha256(data).hexdigest()
    if not force:
        previous = db.scalar(select(ImportSession).where(
            ImportSession.file_sha256 == digest, ImportSession.status != "FAILED"))
        if previous is not None:
            raise HTTPException(409, f"This exact file was already uploaded (import {previous.id}). "
                                     "Use ?force=true to import it again.")
    folder = Path(get_settings().storage_dir) / "imports"
    folder.mkdir(parents=True, exist_ok=True)
    session_id = uuid.uuid4()
    path = folder / f"{session_id}.pdf"
    path.write_bytes(data)
    sess = ImportSession(
        id=session_id, source_system="WASOOLI", file_name=(file.filename or "wasooli.pdf")[:300],
        file_size=len(data), file_sha256=digest, storage_path=str(path), status="UPLOADED",
        uploaded_by=user.id,
    )
    db.add(sess)
    audit.log(db, user_id=user.id, action="import.upload", entity="import_session", entity_id=session_id,
              after={"file_name": sess.file_name, "size": len(data)}, request=request)
    db.commit()
    background.add_task(importer.parse_session, session_id)
    return sess


@router.get("", response_model=list[SessionOut])
def list_imports(db: Session = Depends(get_db), user: User = Depends(require("import.upload"))):
    return list(db.scalars(select(ImportSession).order_by(ImportSession.created_at.desc()).limit(50)))


@router.get("/{session_id}", response_model=SessionOut)
def get_import(session_id: uuid.UUID, db: Session = Depends(get_db),
               user: User = Depends(require("import.upload"))):
    return _load(db, session_id)


@router.get("/{session_id}/rows", response_model=list[RowOut])
def list_rows(
    session_id: uuid.UUID,
    status: str | None = Query(None, description="NEW, DUPLICATE, UPDATED, ERROR, REVIEW, IMPORTED, SKIPPED"),
    issue: str | None = Query(None, description="Only rows carrying this issue code, e.g. INVALID_MOBILE"),
    q: str | None = Query(None, description="Search name, Wasooli ID, Internet ID or mobile"),
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), user: User = Depends(require("import.upload")),
):
    _load(db, session_id)
    if status and status not in C.IMPORT_ROW_STATUSES:
        raise HTTPException(422, "Unknown status")
    query = select(ImportRow).where(ImportRow.session_id == session_id)
    if status:
        query = query.where(ImportRow.status == status)
    if issue:
        query = query.where(ImportRow.issues.contains([{"code": issue}]))
    if q:
        like = f"%{q.lower()}%"
        query = query.where(
            func.lower(ImportRow.normalized["full_name"].astext).like(like)
            | (ImportRow.normalized["wasooli_id"].astext == q)
            | func.lower(ImportRow.normalized["internet_id"].astext).like(like)
            | ImportRow.normalized["mobile"].astext.like(f"%{q}%")
        )
    return list(db.scalars(query.order_by(ImportRow.row_index).limit(limit).offset(offset)))


@router.get("/{session_id}/rows/{row_id}", response_model=RowOut)
def get_row(session_id: uuid.UUID, row_id: uuid.UUID, db: Session = Depends(get_db),
            user: User = Depends(require("import.upload"))):
    row = db.get(ImportRow, row_id)
    if row is None or row.session_id != session_id:
        raise HTTPException(404, "Row not found")
    return row


@router.post("/{session_id}/rows/{row_id}/decision", status_code=201)
def decide(session_id: uuid.UUID, row_id: uuid.UUID, body: DecisionIn, request: Request,
           db: Session = Depends(get_db), user: User = Depends(require("import.review"))):
    sess = _load(db, session_id)
    if sess.status == "IMPORTING":
        raise HTTPException(409, "Import is running")
    row = db.get(ImportRow, row_id)
    if row is None or row.session_id != session_id:
        raise HTTPException(404, "Row not found")
    if row.status == "IMPORTED":
        raise HTTPException(409, "Row is already imported")
    if body.decision == "UPDATE_EXISTING" and not row.result_connection_id and not (
            body.edited_values or {}).get("customer_id"):
        raise HTTPException(422, "UPDATE_EXISTING needs an existing record: this row matched nobody. "
                                 "Send edited_values.customer_id to attach it to a customer.")
    if body.decision == "MANUAL_EDIT" and not body.edited_values:
        raise HTTPException(422, "MANUAL_EDIT needs edited_values")
    merged = importer.effective_values(row, ImportRowDecision(decision=body.decision,
                                                              edited_values=body.edited_values))
    if body.decision in ("IMPORT", "CREATE_SEPARATE", "MANUAL_EDIT") and importer.validate_values(merged):
        raise HTTPException(422, "; ".join(importer.validate_values(merged)))
    db.add(ImportRowDecision(row_id=row.id, decision=body.decision, edited_values=body.edited_values,
                             decided_by=user.id))
    audit.log(db, user_id=user.id, action="import.decision", entity="import_row", entity_id=row.id,
              after={"decision": body.decision, "edited_values": body.edited_values}, request=request)
    db.commit()
    return {"row_id": row.id, "decision": body.decision}


@router.post("/{session_id}/decisions/bulk")
def bulk_decide(session_id: uuid.UUID, body: BulkDecisionIn, request: Request,
                db: Session = Depends(get_db), user: User = Depends(require("import.review"))):
    """Same decision for every row with a given status (optionally also carrying an issue code)."""
    sess = _load(db, session_id)
    if sess.status == "IMPORTING":
        raise HTTPException(409, "Import is running")
    if body.decision == "UPDATE_EXISTING" and body.status == "REVIEW":
        raise HTTPException(422, "Possible duplicates must be attached one by one (they need a customer_id)")
    query = select(ImportRow).where(ImportRow.session_id == session_id, ImportRow.status == body.status)
    if body.issue_code:
        query = query.where(ImportRow.issues.contains([{"code": body.issue_code}]))
    rows = list(db.scalars(query))
    for row in rows:
        db.add(ImportRowDecision(row_id=row.id, decision=body.decision, decided_by=user.id))
    audit.log(db, user_id=user.id, action="import.bulk_decision", entity="import_session",
              entity_id=session_id, after={**body.model_dump(), "rows": len(rows)}, request=request)
    db.commit()
    return {"rows_decided": len(rows)}


@router.post("/{session_id}/commit")
def commit(session_id: uuid.UUID, body: CommitIn, db: Session = Depends(get_db),
           user: User = Depends(require("import.commit"))):
    """Creates the customers and connections. `dry_run` (the default) only reports what would happen."""
    sess = _load(db, session_id)
    try:
        return importer.commit_session(db, sess, user_id=user.id, include_review=body.include_review,
                                       dry_run=body.dry_run)
    except importer.ImportBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
