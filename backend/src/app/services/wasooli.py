"""Parsing and normalising the Wasooli "all connections" PDF export.

Pure functions only (no database), so the rules are easy to test and to change.

What the export looks like (59 pages, one table, the header repeated on every page):
    Sno | ID | Internet ID | Name | Address | Install Date | Recharge Date | Mobile No |
    Install Amount | Other Amount | Package-Cable | Amount-Cable | Package-Internet |
    Amount-Internet | Total

Things worth knowing, all handled below:
* "Total" is the customer's MONTHLY CHARGE, not a balance. The export carries no balances.
* "Address" is "<free text> - <Area>", wrapped over several lines.
* Areas "Dissconect" and "Free conections" are statuses typed into the area field, not places.
* Mobile is "<n> - <n>"; "0" means empty. Some numbers lack the leading 0 or are truncated.
* Urdu names come out of the PDF in visual order using Arabic presentation forms.
* "Internet ID" is NOT unique (different customers share e.g. "yousaf"); "ID" is.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.customers import normalize_alias, normalize_mobile

PARSER_VERSION = "wasooli-1"

EXPECTED_COLUMNS = [
    "Sno", "ID", "Internet ID", "Name", "Address", "Install Date", "Recharge Date", "Mobile No",
    "Install Amount", "Other Amount", "Package-Cable", "Amount-Cable", "Package-Internet",
    "Amount-Internet", "Total",
]

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# Area values that are really connection statuses (matched on letters only, typo tolerant).
_STATUS_AREAS = [
    (re.compile(r"^diss?c?onn?ect"), "DISCONNECTED"),
    (re.compile(r"^free"), "FREE"),
]

_STREET_RE = re.compile(r"\bst(?:reet)?\s*[#$]?\s*(\d{1,3})\b", re.IGNORECASE)
_RTL_CONTROLS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_PRESENTATION_FORMS = re.compile("[\ufb50-\ufdff\ufe70-\ufeff]")
_NAME_NOISE = {"sb", "sab", "sahib", "sahab", "sahb", "muhammad", "m", "mr", "ftth", "master", "hc", "sc"}


class ParseError(Exception):
    """The file is not a Wasooli export we understand (wrong columns, no table, unreadable)."""


@dataclass
class RawRow:
    page: int
    index: int          # 0-based position in the file
    cells: dict[str, str]


# ------------------------------------------------------------------ PDF extraction
def extract_rows(pdf_path: str) -> tuple[list[RawRow], dict[str, Any]]:
    """Reads every table row. Returns (rows, report). Raises ParseError if it is not the export."""
    import pdfplumber  # heavy import, only when parsing

    rows: list[RawRow] = []
    pages = 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = len(pdf.pages)
            for page_no, page in enumerate(pdf.pages, start=1):
                for table in page.extract_tables():
                    columns: list[str] | None = None
                    for line in table:
                        cells = [(c or "").strip() for c in line]
                        if cells and cells[0] == "Sno":
                            columns = [re.sub(r"\s*-\s*", "-", re.sub(r"\s+", " ", c)).strip() for c in cells]
                            continue
                        if columns is None:
                            continue  # table without our header on this page: ignore
                        if not any(cells):
                            continue  # the empty trailing row the export always has
                        rows.append(RawRow(page_no, len(rows), dict(zip(columns, cells, strict=False))))
    except ParseError:
        raise
    except Exception as exc:  # corrupt/encrypted/not a PDF
        raise ParseError(f"Could not read the PDF: {exc}") from exc

    if not rows:
        raise ParseError("No customer table found. Is this the Wasooli 'all connections' export?")
    missing = [c for c in EXPECTED_COLUMNS if c not in rows[0].cells]
    if missing:
        raise ParseError(f"The table is missing expected columns: {', '.join(missing)}")
    return rows, {"pages": pages, "rows": len(rows)}


# ------------------------------------------------------------------ small helpers
def _one_line(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\n", " ")).strip()


def clean_name(raw: str) -> tuple[str, bool]:
    """Returns (name, is_urdu). Repairs Urdu text extracted in visual order."""
    text = _RTL_CONTROLS.sub("", _one_line(raw))
    if _PRESENTATION_FORMS.search(text):
        logical = unicodedata.normalize("NFKC", text)
        # Visual order → logical order. Only safe for pure RTL text (letters/spaces).
        if re.fullmatch(r"[\u0600-\u06ff\s]+", logical):
            text = logical[::-1]
        else:
            text = logical
    return text, bool(re.search(r"[\u0600-\u06ff]", text))


def parse_date(value: str) -> date | None:
    m = re.fullmatch(r"(\d{1,2})/([A-Za-z]{3})/(\d{4})", (value or "").strip())
    if not m or m.group(2).lower() not in _MONTHS:
        return None
    try:
        return date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    except ValueError:
        return None


def parse_money(value: str) -> Decimal | None:
    v = (value or "").strip().replace(",", "")
    if v in ("", "-"):
        return Decimal("0")
    try:
        d = Decimal(v)
    except InvalidOperation:
        return None
    return d if d >= 0 and d == d.quantize(Decimal("0.01")) else None


def status_from_area(area: str | None) -> str | None:
    if not area:
        return None
    key = re.sub(r"[^a-z]", "", area.lower())
    for pattern, status in _STATUS_AREAS:
        if pattern.match(key):
            return status
    return None


def split_address(cell: str) -> tuple[str, str | None]:
    """'habib park St# 1 - Habib Park' → ('habib park St# 1', 'Habib Park')."""
    text = _one_line(cell)
    if " - " in text:
        head, tail = text.rsplit(" - ", 1)
        return head.strip(), tail.strip() or None
    return text, None


def parse_mobiles(cell: str) -> tuple[str | None, str | None, list[str]]:
    """'0 - 03008475445' → (primary, alternate, unrecognised_raw_values). Local format 03XXXXXXXXX."""
    good: list[str] = []
    bad: list[str] = []
    for part in _one_line(cell).split(" - "):
        digits = re.sub(r"\D", "", part)
        if not digits or set(digits) == {"0"}:
            continue
        norm = normalize_mobile(part)
        if norm:
            local = "0" + norm[3:]
            if local not in good:
                good.append(local)
        else:
            bad.append(part.strip())
    return (good[0] if good else None), (good[1] if len(good) > 1 else None), bad


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[^\W\d_]+", name.lower()) if t not in _NAME_NOISE and len(t) > 1}


def names_similar(a: str, b: str) -> bool:
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.5


# ------------------------------------------------------------------ normalisation
def normalize_row(raw: dict[str, str], known_areas: dict[str, str] | None = None
                  ) -> tuple[dict[str, Any], list[dict[str, str]], bool]:
    """Turns one raw row into the values we propose to store.

    `known_areas` maps lower-case area name → display spelling (built from the whole file) and is
    only used to guess the area of Disconnected/Free customers from their address text.
    Returns (normalized, issues, fatal). Issues are {"code","severity","message"}; fatal rows
    cannot be imported.
    """
    issues: list[dict[str, str]] = []

    def issue(code: str, severity: str, message: str) -> None:
        issues.append({"code": code, "severity": severity, "message": message})

    fatal = False
    wasooli_id = _one_line(raw.get("ID"))
    if not wasooli_id:
        issue("MISSING_ID", "error", "Row has no Wasooli ID")
        fatal = True

    name, is_urdu = clean_name(raw.get("Name", ""))
    if not name:
        issue("MISSING_NAME", "error", "Row has no customer name")
        fatal = True

    install = parse_date(raw.get("Install Date", ""))
    recharge = parse_date(raw.get("Recharge Date", ""))
    if raw.get("Install Date", "").strip() and install is None:
        issue("BAD_INSTALL_DATE", "warning", f"Unreadable install date '{raw.get('Install Date')}'")
    if raw.get("Recharge Date", "").strip() and recharge is None:
        issue("BAD_RECHARGE_DATE", "warning", f"Unreadable recharge date '{raw.get('Recharge Date')}'")
    if install and recharge and recharge < install:
        issue("RECHARGE_BEFORE_INSTALL", "info", "Recharge date is earlier than the install date")

    # Address / area / status
    address, area_raw = split_address(raw.get("Address", ""))
    status = "ACTIVE"
    area_name: str | None = area_raw
    area_inferred = False
    special = status_from_area(area_raw)
    if special:
        status = special
        area_name = None
        if known_areas:
            haystack = " " + re.sub(r"[^a-z0-9]+", " ", address.lower()) + " "
            for key in sorted(known_areas, key=len, reverse=True):
                if f" {re.sub(r'[^a-z0-9]+', ' ', key)} " in haystack:
                    area_name, area_inferred = known_areas[key], True
                    break
        if area_name is None:
            issue("AREA_UNKNOWN", "info", f"Area column says '{area_raw}'; real area not found in address")
        else:
            issue("AREA_INFERRED", "info", f"Area guessed from the address: {area_name}")
    elif area_raw is None:
        issue("NO_AREA", "warning", "Address has no '- Area' part")
    street = None
    m = _STREET_RE.search(address)
    if m and area_name:
        street = f"St# {int(m.group(1))}"

    # Mobiles
    mobile, alt_mobile, bad_mobiles = parse_mobiles(raw.get("Mobile No", ""))
    for b in bad_mobiles:
        issue("INVALID_MOBILE", "warning", f"Mobile '{b}' is not a valid Pakistani mobile number")
    if mobile is None and not bad_mobiles:
        issue("NO_MOBILE", "info", "No mobile number")

    # Services and money
    cable_pkg = _one_line(raw.get("Package-Cable"))
    inet_pkg = _one_line(raw.get("Package-Internet"))
    cable_pkg = "" if cable_pkg in ("-", "") else cable_pkg
    inet_pkg = "" if inet_pkg in ("-", "") else inet_pkg
    amounts = {k: parse_money(raw.get(col, "")) for k, col in (
        ("cable", "Amount-Cable"), ("internet", "Amount-Internet"), ("install", "Install Amount"),
        ("other", "Other Amount"), ("total", "Total"))}
    if any(v is None for v in amounts.values()):
        issue("BAD_AMOUNT", "error", "An amount is not a valid non-negative number")
        fatal = True
        amounts = {k: (v if v is not None else Decimal("0")) for k, v in amounts.items()}
    expected_total = amounts["cable"] + amounts["internet"] + amounts["install"] + amounts["other"]
    if expected_total != amounts["total"]:
        issue("TOTAL_MISMATCH", "warning",
              f"Total {amounts['total']} differs from the sum of its parts {expected_total}")
    if not cable_pkg and not inet_pkg:
        issue("NO_SERVICE", "error", "Row has neither a cable nor an internet package")
        fatal = True
    if status == "ACTIVE" and (cable_pkg or inet_pkg) and amounts["total"] == 0:
        issue("ZERO_PRICE_ACTIVE", "warning", "Active customer with a zero monthly charge")
    if (inet_pkg and amounts["internet"] == 0 and amounts["total"] != 0) or \
       (cable_pkg and amounts["cable"] == 0 and amounts["total"] != 0):
        issue("ZERO_LINE_PRICE", "info", "A service has no price while the other service does")

    connection_type = ("COMBINED" if cable_pkg and inet_pkg else "CABLE" if cable_pkg else "INTERNET")

    services: dict[str, dict[str, Any]] = {}
    if inet_pkg:
        services["internet"] = {"package": inet_pkg, "amount": str(amounts["internet"])}
    if cable_pkg:
        services["cable"] = {"package": cable_pkg, "amount": str(amounts["cable"])}

    normalized = {
        "wasooli_id": wasooli_id,
        "internet_id": _one_line(raw.get("Internet ID")) or None,
        "full_name": name,
        "full_name_ur": name if is_urdu else None,
        "address": address or None,
        "area": area_name,
        "area_inferred": area_inferred,
        "area_column": area_raw,
        "street": street,
        "mobile": mobile,
        "alt_mobile": alt_mobile,
        "unrecognised_mobiles": bad_mobiles,
        "install_date": install.isoformat() if install else None,
        "recharge_date": recharge.isoformat() if recharge else None,
        "connection_type": connection_type,
        "status": status,
        "services": services,
        "total": str(amounts["total"]),
        "install_amount": str(amounts["install"]),
        "other_amount": str(amounts["other"]),
    }
    return normalized, issues, fatal


def row_hash(normalized: dict[str, Any]) -> str:
    import json

    return hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def canonical_areas(rows: list[dict[str, str]]) -> dict[str, str]:
    """lower-case area → most common spelling, for every real (non-status) area in the file."""
    counts: dict[str, Counter] = {}
    for raw in rows:
        _, area = split_address(raw.get("Address", ""))
        if area and not status_from_area(area):
            counts.setdefault(re.sub(r"\s+", " ", area.lower()), Counter())[area] += 1
    return {k: c.most_common(1)[0][0] for k, c in counts.items()}


def package_alias_key(name: str) -> str:
    return normalize_alias(name)
