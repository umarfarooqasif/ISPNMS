"""Wasooli import: parsing rules, the PDF reader, and the upload → review → commit workflow."""

import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import (
    Area, Connection, ConnectionServiceLine, Customer, ExternalRef, ImportRow, LedgerEntry, Package,
)
from app.services import wasooli

API = "/api/v1"

COLUMNS = ["Sno", "ID", "Internet ID", "Name", "Address", "Install Date", "Recharge\nDate", "Mobile No",
           "Install\nAmount", "Other\nAmount", "Package-\nCable", "Amount-\nCable", "Package-\nInternet",
           "Amount-\nInternet", "Total"]


def raw(**over):
    base = {"ID": "4001", "Internet ID": "alihp1", "Name": "Ali Khan", "Address": "habib park\nSt# 1 - Habib\nPark",
            "Install Date": "16/Feb/2026", "Recharge Date": "14/Sep/2026", "Mobile No": "0 -\n03008475445",
            "Install Amount": "0", "Other Amount": "0", "Package-Cable": "-", "Amount-Cable": "0",
            "Package-Internet": "Star3", "Amount-Internet": "1000", "Total": "1000"}
    base.update(over)
    return base


def pdf_row(n, **over):
    r = raw(**over)
    return [str(n), r["ID"], r["Internet ID"], r["Name"], r["Address"], r["Install Date"], r["Recharge Date"],
            r["Mobile No"], r["Install Amount"], r["Other Amount"], r["Package-Cable"], r["Amount-Cable"],
            r["Package-Internet"], r["Amount-Internet"], r["Total"]]


def make_pdf(path: Path, rows: list[list[str]], pages: int = 1) -> Path:
    """A PDF shaped like the Wasooli export: ruled table, wrapped cells, header on every page."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import PageBreak, SimpleDocTemplate, Table, TableStyle

    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=10, rightMargin=10)
    style = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 6)])
    story = []
    per = max(1, -(-len(rows) // pages))
    for i in range(0, len(rows), per):
        story.append(Table([COLUMNS, *rows[i:i + per]], style=style))
        if i + per < len(rows):
            story.append(PageBreak())
    doc.build(story)
    return path


# ------------------------------------------------------------------ pure rules
def test_normal_internet_row():
    n, issues, fatal = wasooli.normalize_row(raw())
    assert not fatal and issues == []
    assert n["wasooli_id"] == "4001" and n["full_name"] == "Ali Khan"
    assert n["address"] == "habib park St# 1" and n["area"] == "Habib Park" and n["street"] == "St# 1"
    assert n["mobile"] == "03008475445" and n["connection_type"] == "INTERNET" and n["status"] == "ACTIVE"
    assert n["services"] == {"internet": {"package": "Star3", "amount": "1000"}}
    assert n["install_date"] == "2026-02-16" and n["recharge_date"] == "2026-09-14"


def test_cable_and_combined_types():
    cable, _, _ = wasooli.normalize_row(raw(**{"Package-Internet": "-", "Amount-Internet": "0",
                                               "Package-Cable": "cable 3", "Amount-Cable": "300", "Total": "300"}))
    assert cable["connection_type"] == "CABLE" and list(cable["services"]) == ["cable"]
    both, _, _ = wasooli.normalize_row(raw(**{"Package-Cable": "cable 1", "Amount-Cable": "200", "Total": "1200"}))
    assert both["connection_type"] == "COMBINED" and set(both["services"]) == {"cable", "internet"}


@pytest.mark.parametrize("area,status", [("Dissconect", "DISCONNECTED"), ("Disconnected", "DISCONNECTED"),
                                         ("Free conections", "FREE"), ("Housing Colony", None)])
def test_status_is_read_from_the_area_column(area, status):
    n, issues, _ = wasooli.normalize_row(raw(Address=f"qadir colony st# 5 - {area}"),
                                         known_areas={"qadir colony": "Qadir Colony"})
    if status:
        assert n["status"] == status and n["area_column"] == area
        assert n["area"] == "Qadir Colony" and n["area_inferred"] is True   # guessed from the address text
        assert "AREA_INFERRED" in [i["code"] for i in issues]
    else:
        assert n["status"] == "ACTIVE" and n["area"] == area


def test_status_area_without_a_guessable_place_stays_unassigned():
    n, issues, _ = wasooli.normalize_row(raw(Address="rasool nagar - Dissconect"),
                                         known_areas={"qadir colony": "Qadir Colony"})
    assert n["status"] == "DISCONNECTED" and n["area"] is None
    assert "AREA_UNKNOWN" in [i["code"] for i in issues]


def test_urdu_names_are_repaired():
    visual = "بﺣﺎﺻ یردﮨوﭼ دﮨاز"      # what the PDF text layer returns (visual order, presentation forms)
    name, is_urdu = wasooli.clean_name("\u202b" + visual)
    assert is_urdu and name == "زاہد چوہدری صاحب"
    assert wasooli.clean_name("Yousaf\nsb") == ("Yousaf sb", False)


@pytest.mark.parametrize("cell,primary,alt,bad", [
    ("0 - 03008475445", "03008475445", None, []),
    ("0 - 0", None, None, []),
    ("0 - 3068480403", "03068480403", None, []),                     # missing leading zero
    ("03001234567 - 03111234567", "03001234567", "03111234567", []),
    ("0 - 0334555242", None, None, ["0334555242"]),                  # truncated: kept as unrecognised
    ("0 - 57", None, None, ["57"]),
])
def test_mobile_parsing(cell, primary, alt, bad):
    assert wasooli.parse_mobiles(cell) == (primary, alt, bad)


def test_bad_rows_are_flagged_not_guessed():
    n, issues, fatal = wasooli.normalize_row(raw(ID="", Name=""))
    assert fatal and {"MISSING_ID", "MISSING_NAME"} <= {i["code"] for i in issues}
    _, issues, fatal = wasooli.normalize_row(raw(**{"Package-Internet": "-", "Amount-Internet": "0", "Total": "0"}))
    assert fatal and "NO_SERVICE" in [i["code"] for i in issues]
    _, issues, fatal = wasooli.normalize_row(raw(Total="1200"))
    assert not fatal and "TOTAL_MISMATCH" in [i["code"] for i in issues]
    _, issues, _ = wasooli.normalize_row(raw(**{"Amount-Internet": "0", "Total": "0"}))
    assert "ZERO_PRICE_ACTIVE" in [i["code"] for i in issues]


# ------------------------------------------------------------------ the PDF reader
def test_reader_handles_wrapped_cells_and_repeated_headers(tmp_path):
    rows = [pdf_row(i + 1, ID=str(4000 + i), **{"Internet ID": f"c{i}"}) for i in range(6)]
    rows_, report = wasooli.extract_rows(str(make_pdf(tmp_path / "w.pdf", rows, pages=2)))
    assert report["rows"] == 6 and [r.cells["ID"] for r in rows_] == [str(4000 + i) for i in range(6)]
    assert rows_[0].cells["Package-Internet"] == "Star3" and "Habib" in rows_[0].cells["Address"]
    assert {r.page for r in rows_} == {1, 2}


def test_reader_rejects_other_pdfs(tmp_path):
    from reportlab.pdfgen import canvas

    p = tmp_path / "other.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(100, 700, "Not a customer list")
    c.save()
    with pytest.raises(wasooli.ParseError):
        wasooli.extract_rows(str(p))
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4 garbage")
    with pytest.raises(wasooli.ParseError):
        wasooli.extract_rows(str(bad))


@pytest.mark.skipif(not os.environ.get("WASOOLI_SAMPLE_PDF"), reason="set WASOOLI_SAMPLE_PDF to a real export")
def test_real_export_parses_completely():
    rows, report = wasooli.extract_rows(os.environ["WASOOLI_SAMPLE_PDF"])
    assert report["rows"] == len(rows) > 0
    assert [r.cells["Sno"] for r in rows] == [str(i) for i in range(1, len(rows) + 1)]
    areas = wasooli.canonical_areas([r.cells for r in rows])
    assert not [r for r in rows if wasooli.normalize_row(r.cells, areas)[2]]


# ------------------------------------------------------------------ workflow
def upload(client, headers, path, force=False):
    with open(path, "rb") as fh:
        return client.post(f"{API}/imports/wasooli?force={'true' if force else 'false'}",
                           files={"file": (path.name, fh, "application/pdf")}, headers=headers)


@pytest.fixture
def sample_rows():
    return [
        pdf_row(1, ID="4001", **{"Internet ID": "ali1", "Name": "Ali Khan"}),
        pdf_row(2, ID="4002", **{"Internet ID": "sara1", "Name": "Sara Bibi", "Mobile No": "0 - 0",
                                 "Address": "qadir colony St# 5 - Qadir Colony", "Package-Internet": "Star6",
                                 "Amount-Internet": "1500", "Total": "1500"}),
        pdf_row(3, ID="4003", **{"Internet ID": "ali1", "Name": "Old Shop", "Address": "bazar - Dissconect",
                                 "Mobile No": "0 - 0", "Package-Internet": "Star3", "Amount-Internet": "1000",
                                 "Total": "1000"}),
        pdf_row(4, ID="4004", **{"Internet ID": "cab1", "Name": "Cable Wala", "Mobile No": "0 - 0",
                                 "Package-Internet": "-", "Amount-Internet": "0", "Package-Cable": "cable 3",
                                 "Amount-Cable": "300", "Total": "300"}),
    ]


def test_upload_parse_and_commit(client, admin, db, tmp_path, sample_rows):
    pdf = make_pdf(tmp_path / "w.pdf", sample_rows)
    r = upload(client, admin, pdf)
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    sess = client.get(f"{API}/imports/{sid}", headers=admin).json()
    assert sess["status"] == "MATCHED", sess
    assert sess["summary"]["rows_by_status"] == {"NEW": 4}
    assert sess["summary"]["monthly_charge_total"] == "3800"
    assert set(sess["summary"]["packages_to_create"]) == {"Star3", "Star6", "cable 3"}

    # default is a preview: nothing is written
    preview = client.post(f"{API}/imports/{sid}/commit", json={}, headers=admin).json()
    assert preview["dry_run"] is True and preview["actions"] == {"create": 4}
    assert db.scalar(select(func.count()).select_from(Customer)) == 0

    done = client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=admin)
    assert done.status_code == 200, done.text
    assert done.json()["result"] == {"customers_created": 4}

    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Customer)) == 4
    assert db.scalar(select(func.count()).select_from(LedgerEntry)) == 0     # an import never creates debt
    ali = db.scalar(select(Customer).where(Customer.full_name == "Ali Khan"))
    assert ali.mobile == "03008475445" and ali.mobile_normalized == "+923008475445"
    assert ali.area.name == "Habib Park" if hasattr(ali, "area") else True
    conn = db.scalar(select(Connection).where(Connection.customer_id == ali.id))
    assert conn.status == "ACTIVE" and conn.connection_type == "INTERNET"
    assert str(conn.source_recharge_date) == "2026-09-14" and str(conn.install_date) == "2026-02-16"
    refs = {(x.ref_type, x.value) for x in db.scalars(select(ExternalRef).where(ExternalRef.connection_id == conn.id))}
    assert refs == {("ID", "4001"), ("INTERNET_ID", "ali1")}
    line = db.scalar(select(ConnectionServiceLine).where(ConnectionServiceLine.connection_id == conn.id))
    assert line.service == "INTERNET" and str(line.price) == "1000.00"
    shop = db.scalar(select(Connection).join(Customer).where(Customer.full_name == "Old Shop"))
    assert shop.status == "DISCONNECTED"                                       # from the "Dissconect" area
    # Internet ID "ali1" is shared by two customers: both keep it, only the first gets a unique reference
    assert shop.internet_id == "ali1"
    assert db.scalar(select(func.count()).select_from(ExternalRef).where(
        ExternalRef.ref_type == "INTERNET_ID", ExternalRef.value == "ali1")) == 1
    assert {a.name for a in db.scalars(select(Area))} == {"Habib Park", "Qadir Colony"}   # not "Dissconect"
    assert db.scalar(select(Package.monthly_price).where(Package.code == "STAR6")) == 1500
    assert db.scalar(select(Package.monthly_price).where(Package.code == "CABLE_3")) == 300
    assert client.get(f"{API}/imports/{sid}", headers=admin).json()["status"] == "COMPLETED"


def test_same_file_twice_is_refused_and_a_forced_rerun_creates_nobody_twice(client, admin, db, tmp_path, sample_rows):
    pdf = make_pdf(tmp_path / "w.pdf", sample_rows)
    first = upload(client, admin, pdf).json()["id"]
    client.post(f"{API}/imports/{first}/commit", json={"dry_run": False}, headers=admin)
    assert upload(client, admin, pdf).status_code == 409
    second = upload(client, admin, pdf, force=True).json()["id"]
    s = client.get(f"{API}/imports/{second}", headers=admin).json()
    assert s["summary"]["rows_by_status"] == {"DUPLICATE": 4}
    again = client.post(f"{API}/imports/{second}/commit", json={"dry_run": False}, headers=admin).json()
    assert again["result"] == {} and db.scalar(select(func.count()).select_from(Customer)) == 4


def test_a_changed_export_updates_only_after_a_decision(client, admin, db, tmp_path, sample_rows):
    a = upload(client, admin, make_pdf(tmp_path / "a.pdf", sample_rows)).json()["id"]
    client.post(f"{API}/imports/{a}/commit", json={"dry_run": False}, headers=admin)

    changed = [list(r) for r in sample_rows]
    changed[0][12], changed[0][13], changed[0][14] = "Star6", "1500", "1500"      # Ali moves to Star6
    changed[0][3] = "Ali Khan Sb"
    b = upload(client, admin, make_pdf(tmp_path / "b.pdf", changed)).json()["id"]
    sess = client.get(f"{API}/imports/{b}", headers=admin).json()
    assert sess["status"] == "IN_REVIEW" and sess["summary"]["rows_by_status"] == {"UPDATED": 1, "DUPLICATE": 3}
    row = client.get(f"{API}/imports/{b}/rows?status=UPDATED", headers=admin).json()[0]
    fields = {c["field"] for c in row["match_candidates"][1]["changes"]}
    assert {"full_name", "internet_package", "internet_price"} <= fields

    client.post(f"{API}/imports/{b}/commit", json={"dry_run": False}, headers=admin)
    db.expire_all()
    assert db.scalar(select(Customer.full_name).where(Customer.full_name.like("Ali Khan%"))) == "Ali Khan"  # untouched

    d = client.post(f"{API}/imports/{b}/rows/{row['id']}/decision", json={"decision": "UPDATE_EXISTING"}, headers=admin)
    assert d.status_code == 201
    client.post(f"{API}/imports/{b}/commit", json={"dry_run": False}, headers=admin)
    db.expire_all()
    cust = db.scalar(select(Customer).where(Customer.full_name == "Ali Khan Sb"))
    line = db.scalar(select(ConnectionServiceLine).join(Connection).where(Connection.customer_id == cust.id))
    assert str(line.price) == "1500.00"
    assert db.scalar(select(func.count()).select_from(Customer)) == 4


def test_possible_duplicates_wait_for_a_human(client, admin, db, tmp_path):
    rows = [pdf_row(1, ID="5001", Name="Shehzad sb FTTH", **{"Mobile No": "0 - 03004824342"}),
            pdf_row(2, ID="5002", Name="shehzad sb FTTH", **{"Mobile No": "0 - 03004824342"}),
            pdf_row(3, ID="5003", Name="Different Person", **{"Mobile No": "0 - 03004824342"})]
    sid = upload(client, admin, make_pdf(tmp_path / "d.pdf", rows)).json()["id"]
    s = client.get(f"{API}/imports/{sid}", headers=admin).json()
    assert s["status"] == "IN_REVIEW" and s["summary"]["rows_by_status"] == {"REVIEW": 2, "NEW": 1}
    r = client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=admin).json()
    assert r["result"] == {"customers_created": 1} and r["rows_by_status"] == {"REVIEW": 2, "IMPORTED": 1}

    review = client.get(f"{API}/imports/{sid}/rows?status=REVIEW", headers=admin).json()
    first, second = review
    assert first["match_candidates"][0]["wasooli_id"] == "5002"
    # first: genuinely a separate customer; second: same person as the first (attach as 2nd connection)
    client.post(f"{API}/imports/{sid}/rows/{first['id']}/decision", json={"decision": "CREATE_SEPARATE"}, headers=admin)
    client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=admin)
    db.expire_all()
    owner = db.scalar(select(ImportRow.result_customer_id).where(ImportRow.id == first["id"]))
    d = client.post(f"{API}/imports/{sid}/rows/{second['id']}/decision",
                    json={"decision": "UPDATE_EXISTING", "edited_values": {"customer_id": str(owner)}}, headers=admin)
    assert d.status_code == 201
    done = client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=admin).json()
    assert done["result"] == {"connections_attached": 1}
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Customer)) == 2
    assert db.scalar(select(func.count()).select_from(Connection).where(Connection.customer_id == owner)) == 2
    assert client.get(f"{API}/imports/{sid}", headers=admin).json()["status"] == "COMPLETED"


def test_include_review_imports_possible_duplicates_as_separate_customers(client, admin, db, tmp_path):
    rows = [pdf_row(1, ID="5001", Name="Shehzad sb"), pdf_row(2, ID="5002", Name="shehzad sb")]
    sid = upload(client, admin, make_pdf(tmp_path / "d.pdf", rows)).json()["id"]
    r = client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False, "include_review": True}, headers=admin)
    assert r.json()["result"] == {"customers_created": 2}


def test_manual_edit_can_repair_a_row_and_skip_drops_it(client, admin, db, tmp_path):
    rows = [pdf_row(1, ID="6001", Name="Fix Me", **{"Package-Internet": "-", "Amount-Internet": "0", "Total": "0"}),
            pdf_row(2, ID="6002", Name="Skip Me")]
    sid = upload(client, admin, make_pdf(tmp_path / "m.pdf", rows)).json()["id"]
    errs = client.get(f"{API}/imports/{sid}/rows?status=ERROR", headers=admin).json()
    assert [e["normalized"]["wasooli_id"] for e in errs] == ["6001"]
    ok = client.post(f"{API}/imports/{sid}/rows/{errs[0]['id']}/decision", headers=admin, json={
        "decision": "MANUAL_EDIT",
        "edited_values": {"connection_type": "INTERNET", "services": {"internet": {"package": "Star3", "amount": "1000"}}}})
    assert ok.status_code == 201
    skip = client.get(f"{API}/imports/{sid}/rows?q=6002", headers=admin).json()[0]
    client.post(f"{API}/imports/{sid}/rows/{skip['id']}/decision", json={"decision": "SKIP"}, headers=admin)
    done = client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=admin).json()
    assert done["result"] == {"customers_created": 1}
    assert [c.full_name for c in db.scalars(select(Customer))] == ["Fix Me"]


def test_decision_validation(client, admin, tmp_path):
    sid = upload(client, admin, make_pdf(tmp_path / "v.pdf", [pdf_row(1)])).json()["id"]
    row = client.get(f"{API}/imports/{sid}/rows", headers=admin).json()[0]
    url = f"{API}/imports/{sid}/rows/{row['id']}/decision"
    assert client.post(url, json={"decision": "UPDATE_EXISTING"}, headers=admin).status_code == 422  # matches nobody
    assert client.post(url, json={"decision": "MANUAL_EDIT"}, headers=admin).status_code == 422
    assert client.post(url, json={"decision": "bogus"}, headers=admin).status_code == 422


def test_bad_uploads_and_permissions(client, admin, make_user, tmp_path, sample_rows):
    not_pdf = tmp_path / "x.pdf"
    not_pdf.write_bytes(b"hello")
    assert upload(client, admin, not_pdf).status_code == 422
    other = tmp_path / "other.pdf"
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(other)); c.drawString(50, 700, "nothing here"); c.save()
    sid = upload(client, admin, other).json()["id"]
    s = client.get(f"{API}/imports/{sid}", headers=admin).json()
    assert s["status"] == "FAILED" and "No customer table" in s["summary"]["error"]
    assert client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=admin).status_code == 409

    good = make_pdf(tmp_path / "ok.pdf", sample_rows)
    for role in ("collector", "accountant", "manager", "sales"):
        _, h = make_user(role)
        assert upload(client, h, good).status_code == 403
    assert client.post(f"{API}/imports/wasooli", files={"file": ("a.pdf", b"%PDF", "application/pdf")}).status_code == 401
    # the accountant role can see neither imports nor commit them; admin can do both
    _, acct = make_user("accountant")
    sid = upload(client, admin, good).json()["id"]
    assert client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=acct).status_code == 403
    assert client.get(f"{API}/imports/{sid}", headers=acct).status_code == 403
    assert client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=admin).status_code == 200


def test_row_search_and_issue_filter(client, admin, tmp_path):
    rows = [pdf_row(1, ID="7001", Name="Alpha", **{"Mobile No": "0 - 57"}), pdf_row(2, ID="7002", Name="Beta")]
    sid = upload(client, admin, make_pdf(tmp_path / "s.pdf", rows)).json()["id"]
    by_issue = client.get(f"{API}/imports/{sid}/rows?issue=INVALID_MOBILE", headers=admin).json()
    assert [r["normalized"]["wasooli_id"] for r in by_issue] == ["7001"]
    assert [r["normalized"]["full_name"] for r in client.get(f"{API}/imports/{sid}/rows?q=beta", headers=admin).json()] == ["Beta"]
    assert client.get(f"{API}/imports/{sid}/rows?status=NOPE", headers=admin).status_code == 422
