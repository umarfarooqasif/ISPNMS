"""Phase 4 backend: the collector's snapshot, the offline payment sync, and today's summary."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.main import app
from app.models import Collector, Payment

API = "/api/v1"


@pytest.fixture(autouse=True)
def _pinned_today(monkeypatch):
    monkeypatch.setattr("app.services.billing.local_today", lambda: date(2026, 10, 4))


# ------------------------------------------------------------------ helpers
def mk_collector(make_user, client, admin, customers, code="C01"):
    uid, headers = make_user("collector")
    col = client.post(f"{API}/collectors", headers=admin, json={"user_id": str(uid), "code": code}).json()
    r = client.put(f"{API}/collectors/{col['id']}/customers", headers=admin, json={
        "customers": [{"customer_id": c["id"], "sort_order": i} for i, c in enumerate(customers)]})
    assert r.status_code == 204, r.text
    return col, headers


def invoice(client, h, cust, amount="2000.00", due="2026-10-20"):
    r = client.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust["id"], "issue_date": "2026-10-01", "due_date": due,
        "lines": [{"charge_type": "INTERNET", "amount": amount}]})
    assert r.status_code == 201, r.text
    return r.json()


def item(cust, amount="500.00", txn=None, **kw):
    return {"client_txn_id": txn or str(uuid.uuid4()), "customer_id": cust["id"], "amount": amount,
            "method": "COLLECTOR_CASH", "collected_at": "2026-10-03T10:00:00+05:00", **kw}


def sync(client, h, *items):
    r = client.post(f"{API}/collector/payments/sync", headers=h, json={"payments": list(items)})
    assert r.status_code == 200, r.text
    return r.json()


def snapshot(client, h, **params):
    r = client.get(f"{API}/collector/snapshot", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ snapshot
def test_snapshot_has_only_assigned_customers_with_their_bills(client, admin, make_user, mk_customer):
    mine = mk_customer("Ali Khan", full_name_ur="علی خان", mobile="03001234567",
                       address="House 5, Habib Park", house_no="5")
    other = mk_customer("Not Mine")
    pkg = client.post(f"{API}/packages", headers=admin, json={
        "code": "star3", "name": "Star3", "display_name": "Star 3",
        "display_name_ur": "اسٹار 3"}).json()
    conn = client.post(f"{API}/customers/{mine['id']}/connections", headers=admin, json={
        "connection_type": "INTERNET", "internet_id": "ali1", "next_due_date": "2026-10-20",
        "service_lines": [{"service": "INTERNET", "package_id": pkg["id"], "price": "1000.00"}]}).json()
    invoice(client, admin, mine, "1000.00")
    invoice(client, admin, other, "777.00")
    _, ch = mk_collector(make_user, client, admin, [mine])

    snap = snapshot(client, ch)
    assert snap["total"] == 1 and [c["id"] for c in snap["customers"]] == [mine["id"]]
    c = snap["customers"][0]
    assert c["full_name_ur"] == "علی خان" and c["house_no"] == "5" and c["mobile"] == "03001234567"
    assert c["balance"] == "1000.00" and c["amount_due"] == "1000.00" and c["credit"] == "0.00"
    assert c["billing_status"] == "DUE" and c["oldest_due_date"] == "2026-10-20"
    assert len(c["open_invoices"]) == 1 and c["open_invoices"][0]["outstanding"] == "1000.00"
    cn = c["connections"][0]
    assert cn["id"] == conn["id"] and cn["internet_id"] == "ali1"
    assert cn["package_name"] == "Star 3" and cn["package_name_ur"] == "اسٹار 3"
    assert cn["monthly_charge"] == "1000.00" and cn["next_due_date"] == "2026-10-20"


def test_snapshot_follows_area_assignments_and_hides_archived(client, admin, make_user, mk_customer):
    area = client.post(f"{API}/areas", headers=admin, json={"name": "Housing Colony"}).json()
    a = mk_customer("In Area", area_id=area["id"])
    gone = mk_customer("Archived", area_id=area["id"])
    mk_customer("Elsewhere")
    client.post(f"{API}/customers/{gone['id']}/archive", headers=admin)
    uid, ch = make_user("collector")
    col = client.post(f"{API}/collectors", headers=admin, json={"user_id": str(uid), "code": "C09"}).json()
    client.put(f"{API}/collectors/{col['id']}/areas", headers=admin, json={"area_ids": [area["id"]]})
    snap = snapshot(client, ch)
    assert [c["id"] for c in snap["customers"]] == [a["id"]]
    assert snap["customers"][0]["area_name"] == "Housing Colony"


def test_snapshot_pages_cover_everyone_exactly_once(client, admin, make_user, mk_customer):
    custs = [mk_customer(f"Cust {i:02d}") for i in range(5)]
    _, ch = mk_collector(make_user, client, admin, custs)
    seen = []
    for offset in (0, 2, 4):
        page = snapshot(client, ch, limit=2, offset=offset)
        assert page["total"] == 5
        seen += [c["id"] for c in page["customers"]]
    assert sorted(seen) == sorted(c["id"] for c in custs)


def test_snapshot_access_rules(client, admin, make_user, mk_customer, db):
    c = mk_customer()
    col, ch = mk_collector(make_user, client, admin, [c])
    assert client.get(f"{API}/collector/snapshot").status_code == 401
    assert client.get(f"{API}/collector/snapshot", headers=make_user("accountant")[1]).status_code == 403
    assert client.get(f"{API}/collector/snapshot", headers=admin).status_code == 403  # no collector profile
    db.execute(text("UPDATE collectors SET status='INACTIVE'"))
    db.commit()
    assert client.get(f"{API}/collector/snapshot", headers=ch).status_code == 403


# ------------------------------------------------------------------ sync
def test_offline_payment_syncs_and_keeps_the_receipt_number_printed_on_paper(
        client, admin, make_user, mk_customer, db):
    c = mk_customer()
    invoice(client, admin, c, "2000.00")
    _, ch = mk_collector(make_user, client, admin, [c])
    txn = str(uuid.uuid4())
    out = sync(client, ch, item(c, "500.00", txn, client_receipt_no="OFF-C01-0001"))
    assert out["counts"] == {"SYNCED": 1}
    r = out["results"][0]
    assert r["status"] == "SYNCED" and r["receipt_number"] == "RC-000001"
    assert r["allocated"] == "500.00" and r["unallocated"] == "0.00" and r["balance"] == "1500.00"

    pay = db.scalar(select(Payment))
    assert pay.client_receipt_no == "OFF-C01-0001" and pay.collected_at.date() == date(2026, 10, 3)
    history = client.get(f"{API}/payments", headers=ch).json()
    assert history[0]["client_receipt_no"] == "OFF-C01-0001" and history[0]["receipt_number"] == "RC-000001"


def test_syncing_the_same_payment_again_never_creates_a_second_one(client, admin, make_user, mk_customer, db):
    c = mk_customer()
    invoice(client, admin, c)
    _, ch = mk_collector(make_user, client, admin, [c])
    it = item(c, "500.00", client_receipt_no="OFF-C01-0001")
    first = sync(client, ch, it)["results"][0]
    again = sync(client, ch, it)
    assert again["counts"] == {"DUPLICATE": 1}
    dup = again["results"][0]
    assert dup["payment_id"] == first["payment_id"] and dup["receipt_number"] == first["receipt_number"]
    assert db.scalar(select(func.count()).select_from(Payment)) == 1
    st = client.get(f"{API}/customers/{c['id']}/statement", headers=admin).json()
    assert st["balance"] == "1500.00"


def test_resending_a_whole_batch_is_harmless(client, admin, make_user, mk_customer, db):
    cs = [mk_customer(f"C{i}") for i in range(3)]
    for c in cs:
        invoice(client, admin, c)
    _, ch = mk_collector(make_user, client, admin, cs)
    batch = [item(c, "100.00") for c in cs]
    assert sync(client, ch, *batch)["counts"] == {"SYNCED": 3}
    assert sync(client, ch, *batch)["counts"] == {"DUPLICATE": 3}
    assert db.scalar(select(func.count()).select_from(Payment)) == 3


def test_reusing_a_transaction_id_for_a_different_payment_is_rejected(client, admin, make_user, mk_customer):
    c = mk_customer()
    invoice(client, admin, c)
    _, ch = mk_collector(make_user, client, admin, [c])
    txn = str(uuid.uuid4())
    sync(client, ch, item(c, "500.00", txn))
    r = sync(client, ch, item(c, "999.00", txn))["results"][0]
    assert r["status"] == "REJECTED" and r["code"] == "CONFLICT"


def test_a_bad_item_never_blocks_the_good_ones(client, admin, make_user, mk_customer, db):
    mine, stranger = mk_customer("Mine"), mk_customer("Stranger")
    invoice(client, admin, mine)
    _, ch = mk_collector(make_user, client, admin, [mine])
    out = sync(
        client, ch,
        item(mine, "100.00"),                                  # fine
        item(stranger, "100.00"),                              # not assigned
        item(mine, "10.555"),                                  # too many decimals
        item(mine, "abc"),                                     # not a number
        item(mine, "-5.00"),                                   # negative
        item(mine, "0"),                                       # zero
        {**item(mine, "5.00"), "method": "BARTER"},            # unknown method
        {**item(mine, "5.00"), "customer_id": "not-a-uuid"},   # malformed id
        {**item(mine, "5.00"), "collected_at": "yesterday"},   # malformed time
        item(mine, "5.00", txn="short"),                       # txn id too short
        item(mine, "200.00"),                                  # fine, after the bad ones
    )
    codes = [(r["status"], r["code"]) for r in out["results"]]
    assert codes == [("SYNCED", None), ("REJECTED", "NOT_ASSIGNED")] + [("REJECTED", "INVALID")] * 8 \
        + [("SYNCED", None)]
    assert out["counts"] == {"SYNCED": 2, "REJECTED": 9}
    assert db.scalar(select(func.count()).select_from(Payment)) == 2
    st = client.get(f"{API}/customers/{mine['id']}/statement", headers=admin).json()
    assert st["balance"] == "1700.00"        # 2000 - 100 - 200
    assert all(r["reason"] for r in out["results"] if r["status"] == "REJECTED")


def test_a_collector_cannot_sync_for_someone_elses_customer(client, admin, make_user, mk_customer):
    a, b = mk_customer("A"), mk_customer("B")
    invoice(client, admin, b)
    _, ch = mk_collector(make_user, client, admin, [a], code="C01")
    r = sync(client, ch, item(b, "100.00"))["results"][0]
    assert r["status"] == "REJECTED" and r["code"] == "NOT_ASSIGNED"
    assert client.get(f"{API}/customers/{b['id']}/statement", headers=admin).json()["balance"] == "2000.00"


def test_future_collected_at_is_corrected_not_lost(client, admin, make_user, mk_customer, db):
    c = mk_customer()
    invoice(client, admin, c)
    _, ch = mk_collector(make_user, client, admin, [c])
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    r = sync(client, ch, item(c, "100.00", collected_at=future))["results"][0]
    assert r["status"] == "SYNCED" and r["collected_at_adjusted"] is True
    pay = db.scalar(select(Payment))
    assert pay.collected_at <= datetime.now(timezone.utc) + timedelta(minutes=1)
    assert "phone clock" in pay.notes


def test_old_offline_payments_keep_their_real_collection_time(client, admin, make_user, mk_customer, db):
    c = mk_customer()
    invoice(client, admin, c)
    _, ch = mk_collector(make_user, client, admin, [c])
    r = sync(client, ch, item(c, "100.00", collected_at="2026-09-01T09:30:00+05:00"))["results"][0]
    assert r["collected_at_adjusted"] is False
    assert db.scalar(select(Payment)).collected_at == datetime(2026, 9, 1, 4, 30, tzinfo=timezone.utc)


def test_overpayment_is_recorded_and_reported_as_advance_credit(client, admin, make_user, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, "300.00")
    _, ch = mk_collector(make_user, client, admin, [c])
    r = sync(client, ch, item(c, "1000.00"))["results"][0]
    assert r["status"] == "SYNCED" and r["allocated"] == "300.00"
    assert r["unallocated"] == "700.00" and r["balance"] == "-700.00"


def test_receipt_numbers_are_unique_per_collector(client, admin, make_user, mk_customer, db):
    c = mk_customer()
    invoice(client, admin, c)
    _, ch = mk_collector(make_user, client, admin, [c])
    sync(client, ch, item(c, "100.00", client_receipt_no="OFF-C01-0007"))
    r = sync(client, ch, item(c, "100.00", client_receipt_no="OFF-C01-0007"))["results"][0]
    assert r["status"] == "REJECTED" and r["code"] == "RECEIPT_REF_IN_USE"
    assert db.scalar(select(func.count()).select_from(Payment)) == 1


def test_the_offline_receipt_number_cannot_be_changed_later(client, admin, make_user, mk_customer, db):
    c = mk_customer()
    invoice(client, admin, c)
    _, ch = mk_collector(make_user, client, admin, [c])
    sync(client, ch, item(c, "100.00", client_receipt_no="OFF-C01-0001"))
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE payments SET client_receipt_no = 'OFF-C01-9999'"))
        db.commit()
    db.rollback()


def test_inactive_collectors_cannot_sync(client, admin, make_user, mk_customer, db):
    c = mk_customer()
    invoice(client, admin, c)
    _, ch = mk_collector(make_user, client, admin, [c])
    db.execute(text("UPDATE collectors SET status='INACTIVE'"))
    db.commit()
    r = sync(client, ch, item(c, "100.00"))["results"][0]
    assert r["status"] == "REJECTED" and r["code"] == "COLLECTOR_INACTIVE"
    assert db.scalar(select(func.count()).select_from(Payment)) == 0


def test_sync_access_rules(client, admin, make_user, mk_customer):
    c = mk_customer()
    body = {"payments": [item(c)]}
    assert client.post(f"{API}/collector/payments/sync", json=body).status_code == 401
    assert client.post(f"{API}/collector/payments/sync", headers=admin, json=body).status_code == 403
    assert client.post(f"{API}/collector/payments/sync", headers=make_user("technician")[1],
                       json=body).status_code == 403
    _, ch = mk_collector(make_user, client, admin, [c])
    too_many = {"payments": [item(c) for _ in range(201)]}
    assert client.post(f"{API}/collector/payments/sync", headers=ch, json=too_many).status_code == 422


def test_the_same_payment_arriving_from_several_requests_is_stored_once(
        client, admin, make_user, mk_customer, db):
    c = mk_customer()
    invoice(client, admin, c)
    _, ch = mk_collector(make_user, client, admin, [c])
    it = item(c, "500.00", client_receipt_no="OFF-C01-0001")

    def go(_):
        with TestClient(app) as cl:
            return cl.post(f"{API}/collector/payments/sync", headers=ch,
                           json={"payments": [it]}).json()["results"][0]["status"]

    with ThreadPoolExecutor(max_workers=5) as ex:
        statuses = list(ex.map(go, range(5)))
    assert statuses.count("SYNCED") == 1 and set(statuses) <= {"SYNCED", "DUPLICATE"}
    assert db.scalar(select(func.count()).select_from(Payment)) == 1


def test_synced_payments_show_up_in_the_audit_trail(client, admin, make_user, mk_customer):
    c = mk_customer()
    invoice(client, admin, c)
    _, ch = mk_collector(make_user, client, admin, [c])
    sync(client, ch, item(c, "100.00"))
    logs = client.get(f"{API}/audit-logs", headers=admin, params={"action": "payment.create"}).json()
    assert logs and logs[0]["after"]["via"] == "offline_sync"


# ------------------------------------------------------------------ today's collection
def test_daily_summary_counts_own_payments_by_method_and_ignores_voids(client, admin, make_user, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, "5000.00")
    _, ch = mk_collector(make_user, client, admin, [c])
    sync(client, ch,
         item(c, "1000.00", collected_at="2026-10-04T09:00:00+05:00"),
         item(c, "500.00", collected_at="2026-10-04T11:00:00+05:00"),
         {**item(c, "250.00", collected_at="2026-10-04T12:00:00+05:00"), "method": "JAZZCASH"},
         item(c, "300.00", collected_at="2026-10-03T12:00:00+05:00"))        # yesterday
    voided = sync(client, ch, item(c, "40.00", collected_at="2026-10-04T13:00:00+05:00"))["results"][0]
    assert client.post(f"{API}/payments/{voided['payment_id']}/void", headers=admin,
                       json={"reason": "entered by mistake"}).status_code == 200

    s = client.get(f"{API}/collector/summary", headers=ch, params={"day": "2026-10-04"}).json()
    assert s["count"] == 3 and s["total"] == "1750.00" and s["voided_count"] == 1
    assert {m["method"]: (m["count"], m["total"]) for m in s["by_method"]} == {
        "COLLECTOR_CASH": (2, "1500.00"), "JAZZCASH": (1, "250.00")}
    # defaults to today (pinned to 4 Oct) and other days are separate
    assert client.get(f"{API}/collector/summary", headers=ch).json()["total"] == "1750.00"
    assert client.get(f"{API}/collector/summary", headers=ch,
                      params={"day": "2026-10-03"}).json()["total"] == "300.00"


def test_summary_only_counts_the_callers_own_payments(client, admin, make_user, mk_customer):
    a, b = mk_customer("A"), mk_customer("B")
    invoice(client, admin, a)
    invoice(client, admin, b)
    _, ch1 = mk_collector(make_user, client, admin, [a], code="C01")
    _, ch2 = mk_collector(make_user, client, admin, [b], code="C02")
    sync(client, ch1, item(a, "100.00", collected_at="2026-10-04T09:00:00+05:00"))
    sync(client, ch2, item(b, "700.00", collected_at="2026-10-04T09:00:00+05:00"))
    assert client.get(f"{API}/collector/summary", headers=ch1).json()["total"] == "100.00"
    assert client.get(f"{API}/collector/summary", headers=ch2).json()["total"] == "700.00"
    assert client.get(f"{API}/collector/summary", headers=admin).status_code == 403
