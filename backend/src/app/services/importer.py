"""Wasooli import workflow: parse → match → (human review) → commit.

Nothing here touches ledgers: the export has no balances, so an import creates customers,
connections, service lines, areas, streets, packages and Wasooli references only.

Safe to re-run: rows are keyed by the Wasooli ID stored as an external reference, so importing
the same file (or a newer export) twice never creates a customer twice.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import session_factory
from app.models import (
    Area,
    Connection,
    ConnectionServiceLine,
    Customer,
    ExternalRef,
    ImportRow,
    ImportRowDecision,
    ImportSession,
    Package,
    PackageAlias,
    Street,
)
from app.services import audit, wasooli
from app.services.billing import get_or_create_account
from app.services.customers import next_code, normalize_alias, normalize_mobile

STALE_IMPORT_AFTER = timedelta(minutes=30)
COMMIT_EVERY = 100


class ImportBusy(Exception):
    pass


# ------------------------------------------------------------------ parse + match
def parse_session(session_id: uuid.UUID) -> None:
    """Background job: read the stored PDF, create one ImportRow per customer, then match.

    Uses its own database session because it outlives the HTTP request that started it.
    """
    with session_factory()() as db:
        sess = db.get(ImportSession, session_id)
        if sess is None:
            return
        try:
            sess.started_at = datetime.now(UTC)
            sess.parser_version = wasooli.PARSER_VERSION
            db.commit()
            raw_rows, report = wasooli.extract_rows(sess.storage_path)
            _create_rows(db, sess, raw_rows, report)
            sess.status = "PARSED"
            db.commit()
            match_session(db, sess)
        except Exception as exc:  # recorded for the operator; the upload stays for retry
            db.rollback()
            sess = db.get(ImportSession, session_id)
            sess.status = "FAILED"
            sess.summary = {"error": str(exc)[:500]}
            sess.finished_at = datetime.now(UTC)
            db.commit()


def _create_rows(db: Session, sess: ImportSession, raw_rows: list[wasooli.RawRow],
                 report: dict[str, Any]) -> None:
    areas = wasooli.canonical_areas([r.cells for r in raw_rows])
    seen_ids: dict[str, int] = {}
    snos = [r.cells.get("Sno", "") for r in raw_rows]
    for r in raw_rows:
        normalized, issues, fatal = wasooli.normalize_row(r.cells, areas)
        wid = normalized["wasooli_id"]
        if wid:
            if wid in seen_ids:
                issues.append({"code": "DUPLICATE_ID_IN_FILE", "severity": "error",
                               "message": f"Wasooli ID {wid} already appears on row {seen_ids[wid] + 1}"})
                fatal = True
            else:
                seen_ids[wid] = r.index
        db.add(ImportRow(
            session_id=sess.id, page=r.page, row_index=r.index, raw_cells=r.cells,
            normalized=normalized, issues=issues, status="ERROR" if fatal else "NEW",
            row_hash=wasooli.row_hash(normalized),
        ))
    sess.summary = {
        **report,
        "serial_numbers_contiguous": snos == [str(i) for i in range(1, len(snos) + 1)],
    }
    db.flush()


def _codes(row: ImportRow) -> list[str]:
    return [i["code"] for i in (row.issues or [])]


def _add_issue(row: ImportRow, code: str, severity: str, message: str) -> None:
    row.issues = [*(row.issues or []), {"code": code, "severity": severity, "message": message}]


def match_session(db: Session, sess: ImportSession) -> None:
    """Classifies every row: NEW, DUPLICATE (already imported, unchanged), UPDATED (already
    imported, source changed) or REVIEW (might be a person we already have)."""
    rows = list(db.scalars(select(ImportRow).where(ImportRow.session_id == sess.id)
                           .order_by(ImportRow.row_index)))
    usable = [r for r in rows if r.status != "ERROR"]

    ids = [r.normalized["wasooli_id"] for r in usable]
    existing = _existing_by_wasooli_id(db, ids)
    alias_map = {a.alias_normalized: a.package_id for a in db.scalars(select(PackageAlias))}

    # candidates by mobile: other rows in this file, and customers already in the database
    by_mobile: dict[str, list[ImportRow]] = defaultdict(list)
    for r in usable:
        if r.normalized.get("mobile"):
            by_mobile[normalize_mobile(r.normalized["mobile"])].append(r)
    db_by_mobile: dict[str, list[Customer]] = defaultdict(list)
    if by_mobile:
        for c in db.scalars(select(Customer).where(Customer.mobile_normalized.in_(list(by_mobile)),
                                                   Customer.deleted_at.is_(None))):
            db_by_mobile[c.mobile_normalized].append(c)

    for r in usable:
        n = r.normalized
        conn = existing.get(n["wasooli_id"])
        if conn is not None:
            changes = _diff_against_db(conn, n, alias_map)
            r.result_customer_id, r.result_connection_id = conn.customer_id, conn.id
            r.match_candidates = [{"kind": "connection", "connection_id": str(conn.id),
                                   "customer_id": str(conn.customer_id),
                                   "connection_code": conn.connection_code}]
            if changes:
                r.status = "UPDATED"
                r.match_candidates = [*r.match_candidates, {"kind": "changes", "changes": changes}]
            else:
                r.status = "DUPLICATE"
            continue

        cands: list[dict[str, Any]] = []
        mob = normalize_mobile(n.get("mobile"))
        if mob:
            for other in by_mobile.get(mob, []):
                if other.id != r.id and wasooli.names_similar(n["full_name"], other.normalized["full_name"]):
                    cands.append({"kind": "same_file", "wasooli_id": other.normalized["wasooli_id"],
                                  "name": other.normalized["full_name"], "row_index": other.row_index})
            for c in db_by_mobile.get(mob, []):
                if wasooli.names_similar(n["full_name"], c.full_name):
                    cands.append({"kind": "customer", "customer_id": str(c.id),
                                  "customer_code": c.customer_code, "name": c.full_name})
        if cands:
            r.status = "REVIEW"
            r.match_candidates = cands
            r.confidence = Decimal("0.600")
            _add_issue(r, "POSSIBLE_DUPLICATE", "warning",
                       "Same mobile number and a similar name as another record")

    counts = Counter(r.status for r in rows)
    sess.status = "IN_REVIEW" if counts["REVIEW"] or counts["UPDATED"] or counts["ERROR"] else "MATCHED"
    sess.summary = {**(sess.summary or {}), **session_summary(db, sess, rows)}
    sess.finished_at = datetime.now(UTC)
    db.commit()


def _existing_by_wasooli_id(db: Session, ids: list[str]) -> dict[str, Connection]:
    out: dict[str, Connection] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = (select(ExternalRef.value, Connection)
             .join(Connection, Connection.id == ExternalRef.connection_id)
             .where(ExternalRef.system == "WASOOLI", ExternalRef.ref_type == "ID",
                    ExternalRef.value.in_(chunk)))
        for value, conn in db.execute(q):
            out[value] = conn
    return out


def _diff_against_db(conn: Connection, n: dict[str, Any], alias_map: dict[str, uuid.UUID]
                     ) -> list[dict[str, Any]]:
    cust = conn.customer
    changes: list[dict[str, Any]] = []

    def cmp(field: str, old: Any, new: Any) -> None:
        # Compare as strings so dates (date vs ISO text) and money (1000.00 vs 1000) line up.
        def canon(v: Any) -> str | None:
            if v is None or v == "":
                return None
            if isinstance(v, Decimal):
                return str(v.quantize(Decimal("0.01")))
            return str(v)

        if canon(old) != canon(new):
            changes.append({"field": field, "old": canon(old), "new": canon(new)})

    cmp("full_name", cust.full_name, n["full_name"])
    cmp("mobile", cust.mobile_normalized, normalize_mobile(n.get("mobile")))
    cmp("address", cust.address, n.get("address"))
    cmp("status", conn.status, n["status"])
    cmp("install_date", conn.install_date, n.get("install_date"))
    cmp("recharge_date", conn.source_recharge_date, n.get("recharge_date"))
    lines = {sl.service.lower(): sl for sl in conn.service_lines}
    for service, spec in n["services"].items():
        line = lines.get(service)
        want_pkg = alias_map.get(normalize_alias(spec["package"]))
        if line is None:
            changes.append({"field": f"{service}_line", "old": None, "new": spec["package"]})
            continue
        cmp(f"{service}_price", line.price, Decimal(spec["amount"]))
        if want_pkg is not None and line.package_id != want_pkg:
            changes.append({"field": f"{service}_package", "old": str(line.package_id), "new": spec["package"]})
    for service in lines:
        if service not in n["services"]:
            changes.append({"field": f"{service}_line", "old": "present", "new": "absent in source (not applied)"})
    return changes


def session_summary(db: Session, sess: ImportSession, rows: list[ImportRow] | None = None) -> dict[str, Any]:
    if rows is None:
        rows = list(db.scalars(select(ImportRow).where(ImportRow.session_id == sess.id)))
    issue_counts: Counter = Counter()
    for r in rows:
        for code in set(_codes(r)):
            issue_counts[code] += 1
    alias_known = {a.alias_normalized for a in db.scalars(select(PackageAlias))}
    pkgs = Counter()
    for r in rows:
        if r.status == "ERROR":
            continue
        for spec in (r.normalized or {}).get("services", {}).values():
            if normalize_alias(spec["package"]) not in alias_known:
                pkgs[spec["package"]] += 1
    area_known = {a.lower() for a in db.scalars(select(func.lower(Area.name)))}
    new_areas = sorted({r.normalized["area"] for r in rows
                        if r.status != "ERROR" and r.normalized.get("area")
                        and r.normalized["area"].lower() not in area_known})
    return {
        "rows_by_status": dict(Counter(r.status for r in rows)),
        "issue_counts": dict(issue_counts),
        "connection_status": dict(Counter(r.normalized.get("status") for r in rows if r.normalized)),
        "connection_type": dict(Counter(r.normalized.get("connection_type") for r in rows if r.normalized)),
        "packages_to_create": dict(pkgs),
        "areas_to_create": new_areas,
        "monthly_charge_total": str(sum((Decimal(r.normalized["total"]) for r in rows
                                         if r.status != "ERROR" and r.normalized), Decimal("0"))),
    }


# ------------------------------------------------------------------ decisions
def latest_decisions(db: Session, session_id: uuid.UUID) -> dict[uuid.UUID, ImportRowDecision]:
    out: dict[uuid.UUID, ImportRowDecision] = {}
    q = (select(ImportRowDecision).join(ImportRow, ImportRow.id == ImportRowDecision.row_id)
         .where(ImportRow.session_id == session_id).order_by(ImportRowDecision.decided_at))
    for d in db.scalars(q):
        out[d.row_id] = d
    return out


def effective_values(row: ImportRow, decision: ImportRowDecision | None) -> dict[str, Any]:
    """Normalised values with any reviewer edits applied."""
    values = dict(row.normalized or {})
    if decision and decision.edited_values:
        edits = {k: v for k, v in decision.edited_values.items() if k != "customer_id"}
        values.update(edits)
    return values


def validate_values(values: dict[str, Any]) -> list[str]:
    problems = []
    if not (values.get("wasooli_id") or "").strip():
        problems.append("wasooli_id is required")
    if not (values.get("full_name") or "").strip():
        problems.append("full_name is required")
    if not values.get("services"):
        problems.append("at least one service (internet or cable) is required")
    return problems


# ------------------------------------------------------------------ commit
def plan_commit(db: Session, sess: ImportSession, include_review: bool
                ) -> tuple[list[tuple[ImportRow, str, dict[str, Any]]], Counter]:
    """Decides, row by row, what a commit would do. Returns ([(row, action, values)], counts)."""
    rows = list(db.scalars(select(ImportRow).where(ImportRow.session_id == sess.id)
                           .order_by(ImportRow.row_index)))
    decisions = latest_decisions(db, sess.id)
    plan: list[tuple[ImportRow, str, dict[str, Any]]] = []
    counts: Counter = Counter()
    for r in rows:
        d = decisions.get(r.id)
        choice = d.decision if d else None
        values = effective_values(r, d)
        action = "none"
        if r.status in ("IMPORTED", "SKIPPED", "DUPLICATE") and choice not in ("UPDATE_EXISTING",):
            action = "skip"
        elif choice == "SKIP":
            action = "skip"
        elif choice == "UPDATE_EXISTING":
            target = (d.edited_values or {}).get("customer_id")
            if r.result_connection_id and r.status in ("UPDATED", "DUPLICATE", "IMPORTED"):
                action = "update"
            elif target:
                action = "attach"
            else:
                action = "blocked"
        elif choice in ("IMPORT", "CREATE_SEPARATE", "MANUAL_EDIT"):
            action = "create"
        elif r.status == "NEW":
            action = "create"
        elif r.status == "REVIEW":
            action = "create" if include_review else "blocked"
        elif r.status in ("UPDATED", "ERROR"):
            action = "blocked"
        if action in ("create", "attach", "update"):
            problems = validate_values(values)
            if problems:
                action = "blocked"
        counts[action] += 1
        plan.append((r, action, values))
    return plan, counts


def commit_session(db: Session, sess: ImportSession, *, user_id: uuid.UUID | None,
                   include_review: bool = False, dry_run: bool = False) -> dict[str, Any]:
    if sess.status not in ("MATCHED", "IN_REVIEW", "APPROVED", "COMPLETED", "IMPORTING"):
        raise ValueError(f"Import is {sess.status}; it cannot be committed")
    if sess.status == "IMPORTING" and not dry_run:
        stale = sess.updated_at and datetime.now(UTC) - sess.updated_at > STALE_IMPORT_AFTER
        if not stale:
            raise ImportBusy("This import is already running")

    plan, counts = plan_commit(db, sess, include_review)
    todo = [(r, a, v) for r, a, v in plan if a in ("create", "attach", "update")]
    preview = _preview_creations(db, todo)
    if dry_run:
        return {"dry_run": True, "actions": dict(counts), **preview}

    previous_status = sess.status
    sess.status = "IMPORTING"
    db.commit()
    result: Counter = Counter()
    try:
        ctx = _CommitContext(db, user_id, sess.id)
        ctx.prepare(todo)
        for n, (row, action, values) in enumerate(todo, start=1):
            try:
                with db.begin_nested():
                    if action == "create":
                        ctx.create(row, values)
                        result["customers_created"] += 1
                    elif action == "attach":
                        ctx.attach(row, values)
                        result["connections_attached"] += 1
                    else:
                        ctx.update(row, values)
                        result["updated"] += 1
                    row.status = "IMPORTED"
            except Exception as exc:
                row.status = "ERROR"
                _add_issue(row, "IMPORT_FAILED", "error", str(exc)[:300])
                result["failed"] += 1
            if n % COMMIT_EVERY == 0:
                db.commit()
        for row, action, _ in plan:
            if action == "skip" and row.status not in ("IMPORTED", "DUPLICATE", "SKIPPED"):
                row.status = "SKIPPED"
        db.commit()
    except Exception:
        db.rollback()
        sess = db.get(ImportSession, sess.id)
        sess.status = previous_status if previous_status != "IMPORTING" else "FAILED"
        db.commit()
        raise

    rows = list(db.scalars(select(ImportRow).where(ImportRow.session_id == sess.id)))
    remaining = Counter(r.status for r in rows)
    needs_attention = remaining["NEW"] + remaining["REVIEW"] + remaining["UPDATED"] + remaining["ERROR"]
    sess.status = "IN_REVIEW" if needs_attention else "COMPLETED"
    sess.summary = {**(sess.summary or {}), "rows_by_status": dict(remaining),
                    "last_commit": {**result, "at": datetime.now(UTC).isoformat(),
                                    "include_review": include_review}}
    audit.log(db, user_id=user_id, action="import.commit", entity="import_session", entity_id=sess.id,
              after={"result": dict(result), "remaining": dict(remaining)})
    db.commit()
    return {"dry_run": False, "actions": dict(counts), "result": dict(result),
            "rows_by_status": dict(remaining), **preview}


def _preview_creations(db: Session, todo: list[tuple[ImportRow, str, dict[str, Any]]]) -> dict[str, Any]:
    alias_known = {a.alias_normalized for a in db.scalars(select(PackageAlias))}
    area_known = {a.lower() for a in db.scalars(select(func.lower(Area.name)))}
    pk, ar = set(), set()
    for _, _, v in todo:
        for spec in v.get("services", {}).values():
            if normalize_alias(spec["package"]) not in alias_known:
                pk.add(spec["package"])
        if v.get("area") and v["area"].lower() not in area_known:
            ar.add(v["area"])
    return {"packages_to_create": sorted(pk), "areas_to_create": sorted(ar)}


class _CommitContext:
    """Holds caches so a 1,250-row import does not repeat the same lookups."""

    def __init__(self, db: Session, user_id: uuid.UUID | None, session_id: uuid.UUID):
        self.db, self.user_id, self.session_id = db, user_id, session_id
        self.areas: dict[str, Area] = {}
        self.streets: dict[tuple[uuid.UUID, str], Street] = {}
        self.alias_to_package: dict[str, Package] = {}
        self.used_internet_ids: set[str] = set()

    # -- setup: create every missing package/area once, with prices taken from the data
    def prepare(self, todo: list[tuple[ImportRow, str, dict[str, Any]]]) -> None:
        db = self.db
        for a in db.scalars(select(Area).where(Area.deleted_at.is_(None))):
            self.areas[a.name.lower()] = a
        for s in db.scalars(select(Street).where(Street.deleted_at.is_(None))):
            self.streets[(s.area_id, s.name.lower())] = s
        for al in db.scalars(select(PackageAlias)):
            self.alias_to_package[al.alias_normalized] = al.package
        self.used_internet_ids = set(db.scalars(select(ExternalRef.value).where(
            ExternalRef.system == "WASOOLI", ExternalRef.ref_type == "INTERNET_ID")))

        prices: dict[str, Counter] = defaultdict(Counter)
        raw_names: dict[str, str] = {}
        for _, _, v in todo:
            for spec in v.get("services", {}).values():
                key = normalize_alias(spec["package"])
                prices[key][Decimal(spec["amount"])] += 1
                raw_names.setdefault(key, spec["package"])
        existing_codes = set(db.scalars(select(Package.code)))
        for key, name in raw_names.items():
            if key in self.alias_to_package:
                continue
            nonzero = Counter({p: c for p, c in prices[key].items() if p > 0})
            price = (nonzero or prices[key]).most_common(1)[0][0]
            code = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "PKG"
            base, i = code, 2
            while code in existing_codes:
                code, i = f"{base}_{i}", i + 1
            existing_codes.add(code)
            pkg = Package(code=code, name=name, display_name=name, monthly_price=price, status="ACTIVE",
                          description="Created by the Wasooli import; price is the most common amount")
            pkg.aliases = [PackageAlias(alias=name, alias_normalized=key, source="WASOOLI")]
            db.add(pkg)
            db.flush()
            self.alias_to_package[key] = pkg
        db.commit()

    def _area(self, name: str | None) -> Area | None:
        if not name:
            return None
        key = re.sub(r"\s+", " ", name.strip()).lower()
        area = self.areas.get(key)
        if area is None:
            area = Area(name=re.sub(r"\s+", " ", name.strip()))
            self.db.add(area)
            self.db.flush()
            self.areas[key] = area
        return area

    def _street(self, area: Area | None, name: str | None) -> Street | None:
        if not area or not name:
            return None
        street = self.streets.get((area.id, name.lower()))
        if street is None:
            street = Street(area_id=area.id, name=name)
            self.db.add(street)
            self.db.flush()
            self.streets[(area.id, name.lower())] = street
        return street

    def _package(self, name: str) -> Package:
        return self.alias_to_package[normalize_alias(name)]

    def _make_connection(self, customer: Customer, v: dict[str, Any], area: Area | None) -> Connection:
        if (self.db.scalar(select(ExternalRef.id).where(
                ExternalRef.system == "WASOOLI", ExternalRef.ref_type == "ID",
                ExternalRef.value == v["wasooli_id"]))):
            raise ValueError(f"Wasooli ID {v['wasooli_id']} is already in the system")
        services = v["services"]
        main = services.get("internet") or services.get("cable")
        conn = Connection(
            customer_id=customer.id,
            connection_code=next_code(self.db, "connection_code_seq", "CN"),
            internet_id=v.get("internet_id"),
            package_id=self._package(main["package"]).id,
            connection_type=("COMBINED" if len(services) == 2 else "INTERNET" if "internet" in services else "CABLE"),
            install_date=_d(v.get("install_date")),
            source_recharge_date=_d(v.get("recharge_date")),
            status=v["status"],
            area_id=area.id if area else None,
        )
        conn.service_lines = [
            ConnectionServiceLine(service=svc.upper(), package_id=self._package(spec["package"]).id,
                                  price=Decimal(spec["amount"]))
            for svc, spec in services.items()
        ]
        refs = [ExternalRef(system="WASOOLI", ref_type="ID", value=v["wasooli_id"])]
        iid = v.get("internet_id")
        if iid and iid not in self.used_internet_ids:
            refs.append(ExternalRef(system="WASOOLI", ref_type="INTERNET_ID", value=iid))
            self.used_internet_ids.add(iid)
        conn.external_refs = refs
        self.db.add(conn)
        self.db.flush()
        return conn

    def _customer_fields(self, v: dict[str, Any], area: Area | None) -> dict[str, Any]:
        notes = None
        if v.get("unrecognised_mobiles"):
            notes = "Wasooli mobile not recognised: " + ", ".join(v["unrecognised_mobiles"])
        return dict(
            full_name=v["full_name"], full_name_ur=v.get("full_name_ur"),
            mobile=v.get("mobile"), mobile_normalized=normalize_mobile(v.get("mobile")),
            alt_contact=v.get("alt_mobile"), address=v.get("address"),
            area_id=area.id if area else None,
            street_id=(self._street(area, v.get("street")).id if self._street(area, v.get("street")) else None),
            notes=notes,
        )

    def create(self, row: ImportRow, v: dict[str, Any]) -> None:
        area = self._area(v.get("area"))
        customer = Customer(customer_code=next_code(self.db, "customer_code_seq", "C"), status="ACTIVE",
                            **self._customer_fields(v, area))
        self.db.add(customer)
        self.db.flush()
        get_or_create_account(self.db, customer.id)
        conn = self._make_connection(customer, v, area)
        row.result_customer_id, row.result_connection_id = customer.id, conn.id
        audit.log(self.db, user_id=self.user_id, action="import.customer_create", entity="customer",
                  entity_id=customer.id, after={"wasooli_id": v["wasooli_id"],
                                                "import_session": str(self.session_id)})

    def attach(self, row: ImportRow, v: dict[str, Any]) -> None:
        d = self.db.scalar(select(ImportRowDecision).where(ImportRowDecision.row_id == row.id)
                           .order_by(ImportRowDecision.decided_at.desc()))
        customer = self.db.get(Customer, uuid.UUID(str(d.edited_values["customer_id"])))
        if customer is None or customer.deleted_at:
            raise ValueError("The chosen customer does not exist")
        conn = self._make_connection(customer, v, self._area(v.get("area")))
        row.result_customer_id, row.result_connection_id = customer.id, conn.id
        audit.log(self.db, user_id=self.user_id, action="import.connection_attach", entity="connection",
                  entity_id=conn.id, after={"wasooli_id": v["wasooli_id"], "customer_id": str(customer.id),
                                            "import_session": str(self.session_id)})

    def update(self, row: ImportRow, v: dict[str, Any]) -> None:
        conn = self.db.get(Connection, row.result_connection_id)
        cust = conn.customer
        area = self._area(v.get("area"))
        before = {"full_name": cust.full_name, "mobile": cust.mobile, "address": cust.address,
                  "status": conn.status}
        for k, val in self._customer_fields(v, area).items():
            if k == "notes" and val is None:
                continue
            setattr(cust, k, val)
        conn.status = v["status"]
        conn.install_date = _d(v.get("install_date"))
        conn.source_recharge_date = _d(v.get("recharge_date"))
        conn.area_id = area.id if area else None
        lines = {sl.service.lower(): sl for sl in conn.service_lines}
        for svc, spec in v["services"].items():
            pkg = self._package(spec["package"])
            if svc in lines:
                lines[svc].package_id, lines[svc].price = pkg.id, Decimal(spec["amount"])
            else:
                conn.service_lines.append(ConnectionServiceLine(
                    service=svc.upper(), package_id=pkg.id, price=Decimal(spec["amount"])))
        kinds = {sl.service for sl in conn.service_lines}
        conn.connection_type = "COMBINED" if len(kinds) == 2 else ("INTERNET" if "INTERNET" in kinds else "CABLE")
        self.db.flush()
        audit.log(self.db, user_id=self.user_id, action="import.connection_update", entity="connection",
                  entity_id=conn.id, before=before, after={"wasooli_id": v["wasooli_id"],
                                                           "import_session": str(self.session_id)})


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
