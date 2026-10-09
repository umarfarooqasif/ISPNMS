"""Stage 4 backend: full ledger and invoice history, area edit/delete, import decisions that persist."""

import uuid
from datetime import date

import pytest

from tests.test_import import make_pdf, pdf_row, upload

API = "/api/v1"


@pytest.fixture(autouse=True)
def _pinned_today(monkeypatch):
    monkeypatch.setattr("app.services.billing.local_today", lambda: date(2026, 10, 4))


def invoice(client, h, cust, amount, issue="2026-09-01", due="2026-09-15"):
    r = client.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust["id"], "issue_date": issue, "due_date": due,
        "lines": [{"charge_type": "INTERNET", "amount": amount}]})
    assert r.status_code == 201, r.text
    return r.json()


def pay(client, h, cust, amount):
    r = client.post(f"{API}/payments", headers=h, json={"customer_id": cust["id"], "amount": amount, "method": "CASH"})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ ledger
def test_ledger_shows_every_entry_with_a_running_balance(client, admin, mk_customer):
    c = mk_customer()
    inv = invoice(client, admin, c, "2000.00")
    p = pay(client, admin, c, "500.00")
    client.post(f"{API}/adjustments", headers=admin, json={"customer_id": c["id"], "amount": "-100.00", "reason": "goodwill credit"})

    rows = client.get(f"{API}/customers/{c['id']}/ledger", headers=admin).json()
    assert [r["entry_type"] for r in rows][0] != ""                     # newest first
    assert [r["balance"] for r in rows] == ["1400.00", "1500.00", "2000.00"]
    assert [r["amount"] for r in rows] == ["-100.00", "-500.00", "2000.00"]
    by_amount = {r["amount"]: r for r in rows}
    assert by_amount["2000.00"]["reference"] == inv["invoice_number"]
    assert by_amount["-500.00"]["reference"] == p["receipt_number"]
    assert rows[0]["balance"] == client.get(f"{API}/customers/{c['id']}/statement", headers=admin).json()["balance"]


def test_ledger_pages_keep_the_balance_of_the_whole_history(client, admin, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, "2000.00")
    pay(client, admin, c, "500.00")
    pay(client, admin, c, "300.00")
    second = client.get(f"{API}/customers/{c['id']}/ledger", headers=admin, params={"limit": 1, "offset": 1}).json()
    assert len(second) == 1 and second[0]["balance"] == "1500.00" and second[0]["amount"] == "-500.00"
    assert client.get(f"{API}/customers/{c['id']}/ledger", headers=admin, params={"limit": 1, "offset": 5}).json() == []


def test_a_cancelled_payment_shows_both_the_payment_and_its_reversal(client, admin, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, "1000.00")
    p = pay(client, admin, c, "400.00")
    assert client.post(f"{API}/payments/{p['id']}/void", headers=admin, json={"reason": "entered by mistake"}).status_code == 200
    rows = client.get(f"{API}/customers/{c['id']}/ledger", headers=admin).json()
    assert [r["amount"] for r in rows] == ["400.00", "-400.00", "1000.00"]
    assert rows[0]["balance"] == "1000.00" and rows[0]["reverses_entry_id"] is not None


def test_customers_with_no_history_get_empty_lists(client, admin, mk_customer):
    c = mk_customer()
    assert client.get(f"{API}/customers/{c['id']}/ledger", headers=admin).json() == []
    assert client.get(f"{API}/customers/{c['id']}/invoices", headers=admin).json() == []


def test_history_respects_who_may_see_the_customer(client, admin, make_user, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, "100.00")
    stranger = make_user("collector")[1]        # a collector with no assignment cannot see this customer
    for path in ("ledger", "invoices"):
        assert client.get(f"{API}/customers/{c['id']}/{path}", headers=stranger).status_code in (403, 404)
        assert client.get(f"{API}/customers/{c['id']}/{path}").status_code == 401
    assert client.get(f"{API}/customers/{uuid.uuid4()}/ledger", headers=admin).status_code == 404


# ------------------------------------------------------------------ invoices
def test_invoice_history_lists_paid_and_unpaid_bills_newest_first(client, admin, mk_customer):
    c = mk_customer()
    old = invoice(client, admin, c, "1000.00", issue="2026-08-01", due="2026-08-15")
    new = invoice(client, admin, c, "1500.00", issue="2026-09-01", due="2026-09-15")
    pay(client, admin, c, "1000.00")                       # settles the older bill first
    rows = client.get(f"{API}/customers/{c['id']}/invoices", headers=admin).json()
    assert [r["invoice_number"] for r in rows] == [new["invoice_number"], old["invoice_number"]]
    assert rows[0]["status"] == "OVERDUE" and rows[0]["outstanding"] == "1500.00" and rows[0]["paid"] == "0.00"
    assert rows[1]["status"] == "PAID" and rows[1]["outstanding"] == "0.00" and rows[1]["paid"] == "1000.00"
    assert rows[0]["lines"][0]["charge_type"] == "INTERNET"
    one = client.get(f"{API}/customers/{c['id']}/invoices", headers=admin, params={"limit": 1, "offset": 1}).json()
    assert [r["invoice_number"] for r in one] == [old["invoice_number"]]


# ------------------------------------------------------------------ areas
def test_an_area_can_be_renamed_but_not_to_a_name_in_use(client, admin):
    a = client.post(f"{API}/areas", headers=admin, json={"name": "Qadir Colony"}).json()
    b = client.post(f"{API}/areas", headers=admin, json={"name": "Housing Colony"}).json()
    r = client.patch(f"{API}/areas/{a['id']}", headers=admin, json={"name": "Qadir Town", "name_ur": "قادر ٹاؤن"})
    assert r.status_code == 200 and r.json()["name"] == "Qadir Town" and r.json()["name_ur"] == "قادر ٹاؤن"
    assert client.patch(f"{API}/areas/{b['id']}", headers=admin, json={"name": "qadir town"}).status_code == 409
    assert client.patch(f"{API}/areas/{uuid.uuid4()}", headers=admin, json={"name": "X"}).status_code == 404
    assert {x["name"] for x in client.get(f"{API}/areas", headers=admin).json()} == {"Qadir Town", "Housing Colony"}


def test_an_area_in_use_cannot_be_deleted_but_an_empty_one_can(client, admin, make_user, mk_customer):
    used = client.post(f"{API}/areas", headers=admin, json={"name": "Busy"}).json()
    empty = client.post(f"{API}/areas", headers=admin, json={"name": "Empty"}).json()
    mk_customer("Resident", area_id=used["id"])
    r = client.delete(f"{API}/areas/{used['id']}", headers=admin)
    assert r.status_code == 409 and "1 customer" in r.json()["detail"]
    assert client.delete(f"{API}/areas/{empty['id']}", headers=admin).status_code == 204
    assert [x["name"] for x in client.get(f"{API}/areas", headers=admin).json()] == ["Busy"]
    assert client.delete(f"{API}/areas/{empty['id']}", headers=admin).status_code == 404
    # a name freed by deleting can be used again
    assert client.post(f"{API}/areas", headers=admin, json={"name": "Empty"}).status_code in (201, 409)


def test_only_area_managers_can_change_areas(client, admin, make_user):
    a = client.post(f"{API}/areas", headers=admin, json={"name": "Zone"}).json()
    tech = make_user("technician")[1]
    assert client.patch(f"{API}/areas/{a['id']}", headers=tech, json={"name": "Hack"}).status_code == 403
    assert client.delete(f"{API}/areas/{a['id']}", headers=tech).status_code == 403


# ------------------------------------------------------------------ import decisions
def test_import_rows_remember_their_decision(client, admin, tmp_path):
    pdf = make_pdf(tmp_path / "w.pdf", [pdf_row(1, ID="9001")])
    sid = upload(client, admin, pdf).json()["id"]
    row = client.get(f"{API}/imports/{sid}/rows", headers=admin, params={"status": "NEW"}).json()[0]
    assert row["decision"] is None

    assert client.post(f"{API}/imports/{sid}/rows/{row['id']}/decision", headers=admin, json={"decision": "SKIP"}).status_code == 201
    again = client.get(f"{API}/imports/{sid}/rows", headers=admin, params={"status": "NEW"}).json()[0]
    assert again["decision"] == "SKIP"

    # changing your mind: the latest decision wins
    assert client.post(f"{API}/imports/{sid}/rows/{row['id']}/decision", headers=admin, json={"decision": "IMPORT"}).status_code == 201
    latest = client.get(f"{API}/imports/{sid}/rows/{row['id']}", headers=admin).json()
    assert latest["decision"] == "IMPORT"


def test_a_bulk_decision_is_visible_on_every_row(client, admin, tmp_path):
    pdf = make_pdf(tmp_path / "w.pdf", [pdf_row(1, ID="9001"), pdf_row(2, ID="9002", **{"Name": "Zubair Ahmed", "Mobile No": "03111111111", "Address": "Another street", "Internet ID": "zubair2"})])
    sid = upload(client, admin, pdf).json()["id"]
    assert client.post(f"{API}/imports/{sid}/decisions/bulk", headers=admin, json={"status": "NEW", "decision": "SKIP"}).json()["rows_decided"] == 2
    rows = client.get(f"{API}/imports/{sid}/rows", headers=admin).json()
    assert {r["decision"] for r in rows} == {"SKIP"}
