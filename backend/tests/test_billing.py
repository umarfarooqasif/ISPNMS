import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.main import app

API = "/api/v1"
FUTURE = (date.today() + timedelta(days=30)).isoformat()
PAST = (date.today() - timedelta(days=10)).isoformat()


def invoice(client, h, cust, lines, due=FUTURE, **kw):
    r = client.post(f"{API}/invoices", headers=h,
                    json={"customer_id": cust["id"], "lines": lines, "due_date": due, **kw})
    return r


def internet(amount):
    return {"charge_type": "INTERNET", "amount": amount}


def pay(client, h, cust, amount, **kw):
    return client.post(f"{API}/payments", headers=h,
                       json={"customer_id": cust["id"], "amount": amount, "method": "CASH", **kw})


def statement(client, h, cust):
    return client.get(f"{API}/customers/{cust['id']}/statement", headers=h).json()


def test_invoice_creates_balance_and_due_status(client, admin, mk_customer):
    c = mk_customer()
    r = invoice(client, admin, c, [internet("2000.00")])
    assert r.status_code == 201
    body = r.json()
    assert body["total"] == "2000.00" and body["status"] == "DUE" and body["invoice_number"] == "INV-000001"
    assert statement(client, admin, c)["balance"] == "2000.00"


def test_full_payment(client, admin, mk_customer):
    c = mk_customer()
    inv = invoice(client, admin, c, [internet("2000.00")]).json()
    r = pay(client, admin, c, "2000.00")
    assert r.status_code == 201
    p = r.json()
    assert p["receipt_number"] == "RC-000001" and p["unallocated"] == "0.00" and p["balance"] == "0.00"
    assert client.get(f"{API}/invoices/{inv['id']}", headers=admin).json()["status"] == "PAID"


def test_partial_payment(client, admin, mk_customer):
    c = mk_customer()
    inv = invoice(client, admin, c, [internet("2000.00")]).json()
    pay(client, admin, c, "500.00")
    got = client.get(f"{API}/invoices/{inv['id']}", headers=admin).json()
    assert got["status"] == "PARTIAL" and got["paid"] == "500.00" and got["outstanding"] == "1500.00"
    assert statement(client, admin, c)["balance"] == "1500.00"


def test_advance_payment_becomes_credit(client, admin, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, [internet("2000.00")])
    p = pay(client, admin, c, "3000.00").json()
    assert p["unallocated"] == "1000.00" and p["balance"] == "-1000.00"
    st = statement(client, admin, c)
    assert st["credit"] == "1000.00" and st["amount_due"] == "0.00"


def test_previous_balance_paid_oldest_first(client, admin, mk_customer):
    c = mk_customer()
    old = invoice(client, admin, c, [internet("500.00")], due=PAST,
                  issue_date=(date.today() - timedelta(days=40)).isoformat()).json()
    new = invoice(client, admin, c, [internet("2000.00")]).json()
    p = pay(client, admin, c, "700.00").json()
    by_inv = {a["invoice_id"]: a["amount"] for a in p["allocations"]}
    assert by_inv == {old["id"]: "500.00", new["id"]: "200.00"}
    assert statement(client, admin, c)["balance"] == "1800.00"


def test_discount_line(client, admin, mk_customer):
    c = mk_customer()
    r = invoice(client, admin, c, [internet("2000.00"), {"charge_type": "DISCOUNT", "amount": "-300.00"}])
    assert r.json()["total"] == "1700.00"
    assert statement(client, admin, c)["balance"] == "1700.00"


def test_discount_rules_rejected(client, admin, mk_customer):
    c = mk_customer()
    assert invoice(client, admin, c, [{"charge_type": "DISCOUNT", "amount": "100.00"}]).status_code == 422
    assert invoice(client, admin, c, [internet("-5.00")]).status_code == 422
    r = invoice(client, admin, c, [internet("100.00"), {"charge_type": "DISCOUNT", "amount": "-200.00"}])
    assert r.status_code == 422


def test_refund_limited_to_credit(client, admin, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, [internet("2000.00")])
    pay(client, admin, c, "3000.00")  # 1000 credit
    ok = client.post(f"{API}/refunds", headers=admin,
                     json={"customer_id": c["id"], "amount": "400.00", "reason": "customer request"})
    assert ok.status_code == 201
    assert statement(client, admin, c)["balance"] == "-600.00"
    too_much = client.post(f"{API}/refunds", headers=admin,
                           json={"customer_id": c["id"], "amount": "700.00", "reason": "customer request"})
    assert too_much.status_code == 409


def test_refund_without_credit_rejected(client, admin, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, [internet("2000.00")])
    r = client.post(f"{API}/refunds", headers=admin,
                    json={"customer_id": c["id"], "amount": "10.00", "reason": "no credit exists"})
    assert r.status_code == 409


def test_adjustment(client, admin, mk_customer):
    c = mk_customer()
    r = client.post(f"{API}/adjustments", headers=admin,
                    json={"customer_id": c["id"], "amount": "250.00", "reason": "opening balance"})
    assert r.status_code == 201
    assert statement(client, admin, c)["balance"] == "250.00"
    client.post(f"{API}/adjustments", headers=admin,
                json={"customer_id": c["id"], "amount": "-50.00", "reason": "goodwill credit"})
    assert statement(client, admin, c)["balance"] == "200.00"
    assert client.post(f"{API}/adjustments", headers=admin,
                       json={"customer_id": c["id"], "amount": "0.00", "reason": "nothing"}).status_code == 422
    assert client.post(f"{API}/adjustments", headers=admin,
                       json={"customer_id": c["id"], "amount": "5.00", "reason": ""}).status_code == 422


def test_overdue_status(client, admin, mk_customer):
    c = mk_customer()
    r = invoice(client, admin, c, [internet("1000.00")], due=PAST, issue_date=(date.today() - timedelta(days=40)).isoformat())
    assert r.json()["status"] == "OVERDUE"


def test_free_account_zero_invoice(client, admin, mk_customer):
    c = mk_customer()
    r = invoice(client, admin, c, [internet("0.00")])
    assert r.status_code == 201 and r.json()["status"] == "FREE" and r.json()["total"] == "0.00"
    st = statement(client, admin, c)
    assert st["balance"] == "0.00" and st["recent_entries"] == []


def test_cable_plus_internet_lines(client, admin, mk_customer):
    c = mk_customer()
    r = invoice(client, admin, c, [{"charge_type": "CABLE", "amount": "800.00"}, internet("1500.00")])
    body = r.json()
    assert body["total"] == "2300.00"
    assert {ln["charge_type"] for ln in body["lines"]} == {"CABLE", "INTERNET"}


def test_decimal_exactness(client, admin, mk_customer):
    c = mk_customer()
    r = invoice(client, admin, c, [internet("0.10"), {"charge_type": "OTHER", "amount": "0.20"}])
    assert r.json()["total"] == "0.30"  # 0.1 + 0.2 != 0.30000000000000004


def test_more_than_two_decimals_rejected(client, admin, mk_customer):
    c = mk_customer()
    assert invoice(client, admin, c, [internet("10.005")]).status_code == 422
    assert pay(client, admin, c, "10.005").status_code == 422
    assert pay(client, admin, c, "0.00").status_code == 422
    assert pay(client, admin, c, "-5.00").status_code == 422


def test_void_restores_balance_and_voids_receipt(client, admin, mk_customer):
    c = mk_customer()
    inv = invoice(client, admin, c, [internet("2000.00")]).json()
    p = pay(client, admin, c, "2000.00").json()
    r = client.post(f"{API}/payments/{p['id']}/void", headers=admin, json={"reason": "entered by mistake"})
    assert r.status_code == 200
    v = r.json()
    assert v["status"] == "VOID" and v["receipt_status"] == "VOID" and v["balance"] == "2000.00"
    got = client.get(f"{API}/invoices/{inv['id']}", headers=admin).json()
    assert got["outstanding"] == "2000.00" and got["status"] == "DUE"
    assert client.post(f"{API}/payments/{p['id']}/void", headers=admin,
                       json={"reason": "again"}).status_code == 409
    # after a void, a new payment can settle the invoice again
    pay(client, admin, c, "2000.00")
    assert statement(client, admin, c)["balance"] == "0.00"


def test_audit_records_financial_actions(client, admin, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, [internet("100.00")])
    p = pay(client, admin, c, "100.00").json()
    client.post(f"{API}/payments/{p['id']}/void", headers=admin, json={"reason": "test void"})
    actions = {a["action"] for a in client.get(f"{API}/audit-logs", headers=admin).json()}
    assert {"customer.create", "invoice.create", "payment.create", "payment.void"} <= actions


# ---------------------------------------------------------------- DB-level immutability
def _raises(db, sql):
    with pytest.raises(DBAPIError):
        db.execute(text(sql))
        db.commit()
    db.rollback()


def test_financial_history_is_immutable_in_db(client, admin, mk_customer, db):
    c = mk_customer()
    invoice(client, admin, c, [internet("100.00")])
    pay(client, admin, c, "100.00")
    _raises(db, "UPDATE ledger_entries SET amount = 1")
    _raises(db, "DELETE FROM ledger_entries")
    _raises(db, "DELETE FROM payments")
    _raises(db, "UPDATE payments SET amount = 1")
    _raises(db, "DELETE FROM receipts")
    _raises(db, "UPDATE invoices SET total = 1")
    _raises(db, "DELETE FROM invoice_lines")
    _raises(db, "DELETE FROM payment_allocations")
    _raises(db, "UPDATE audit_logs SET action = 'x'")
    _raises(db, "DELETE FROM audit_logs")
    _raises(db, "DELETE FROM customers")


def test_voided_payment_cannot_be_reinstated(client, admin, mk_customer, db):
    c = mk_customer()
    p = pay(client, admin, c, "100.00").json()
    client.post(f"{API}/payments/{p['id']}/void", headers=admin, json={"reason": "test void"})
    _raises(db, f"UPDATE payments SET status = 'POSTED' WHERE id = '{p['id']}'")


def test_no_floating_point_money_columns(db):
    n = db.execute(text(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' "
        "AND data_type IN ('real','double precision')")).scalar()
    assert n == 0


# ---------------------------------------------------------------- idempotent offline sync
def _collector(make_user, client, admin, cust):
    uid, headers = make_user("collector")
    col = client.post(f"{API}/collectors", headers=admin, json={"user_id": str(uid), "code": "C01"}).json()
    r = client.put(f"{API}/collectors/{col['id']}/customers", headers=admin,
                   json={"customers": [{"customer_id": cust["id"], "sort_order": 1}]})
    assert r.status_code == 204
    return col, headers


def test_duplicate_sync_is_idempotent(client, admin, make_user, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, [internet("2000.00")])
    col, ch = _collector(make_user, client, admin, c)
    txn = str(uuid.uuid4())
    first = pay(client, ch, c, "1000.00", client_txn_id=txn)
    second = pay(client, ch, c, "1000.00", client_txn_id=txn)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["receipt_number"] == second.json()["receipt_number"]
    assert second.json()["replayed"] is True
    assert statement(client, admin, c)["balance"] == "1000.00"  # charged once
    payments = client.get(f"{API}/payments", headers=admin).json()
    assert len(payments) == 1


def test_txn_id_reuse_with_different_data_conflicts(client, admin, make_user, mk_customer):
    c = mk_customer()
    col, ch = _collector(make_user, client, admin, c)
    txn = str(uuid.uuid4())
    assert pay(client, ch, c, "100.00", client_txn_id=txn).status_code == 201
    assert pay(client, ch, c, "999.00", client_txn_id=txn).status_code == 409


def test_concurrent_duplicate_sync_writes_once(client, admin, make_user, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, [internet("2000.00")])
    col, ch = _collector(make_user, client, admin, c)
    txn = str(uuid.uuid4())

    def go(_):
        with TestClient(app) as cl:
            return pay(cl, ch, c, "500.00", client_txn_id=txn).status_code

    with ThreadPoolExecutor(max_workers=6) as ex:
        codes = list(ex.map(go, range(6)))
    assert sorted(codes).count(201) == 1 and all(code in (200, 201) for code in codes)
    assert statement(client, admin, c)["balance"] == "1500.00"


def test_txn_id_requires_collector(client, admin, mk_customer):
    c = mk_customer()
    assert pay(client, admin, c, "10.00", client_txn_id=str(uuid.uuid4())).status_code == 422
