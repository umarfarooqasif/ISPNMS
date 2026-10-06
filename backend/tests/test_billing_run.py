"""Phase 3: monthly bill run, late fees, opening balances, connection status, reports.

All dates are passed explicitly (run_date), so nothing here depends on the day the tests run.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import BillingRun, Connection, Customer, Invoice, LateFee, Permission, Role
from app.services.rbac import seed_rbac
from tests.test_import import make_pdf, pdf_row, upload

API = "/api/v1"
RUN = "2026-10-04"


@pytest.fixture(autouse=True)
def _pinned_today(monkeypatch):
    """Statuses such as DUE / PARTIAL / OVERDUE depend on today's date: pin it so these tests
    give the same answer on any day they are run."""
    monkeypatch.setattr("app.services.billing.local_today", lambda: date(2026, 10, 4))


# ------------------------------------------------------------------ helpers
def mk_conn(client, h, cust, price="1000.00", due="2026-10-09", service="INTERNET", ctype=None,
            status="ACTIVE", **extra):
    body = {"connection_type": ctype or service, "status": status,
            "service_lines": [{"service": service, "price": price}] if price is not None else [],
            **extra}
    if due:
        body["next_due_date"] = due
    r = client.post(f"{API}/customers/{cust['id']}/connections", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def preview(client, h, **kw):
    r = client.post(f"{API}/billing/runs/preview", headers=h, json={"run_date": RUN, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def run(client, h, **kw):
    r = client.post(f"{API}/billing/runs", headers=h, json={"run_date": RUN, "confirm": True, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def statement(client, h, cust):
    return client.get(f"{API}/customers/{cust['id']}/statement", headers=h).json()


def conn_now(client, h, conn):
    return client.get(f"{API}/connections/{conn['id']}", headers=h).json()


def outcomes(result):
    return sorted(i["outcome"] for i in result["items"])


# ------------------------------------------------------------------ preview / confirm
def test_preview_writes_nothing(client, admin, db, mk_customer):
    c = mk_customer()
    conn = mk_conn(client, admin, c)
    p = preview(client, admin)
    assert p["dry_run"] is True and p["run_id"] is None
    assert p["invoices_created"] == 1 and p["total_billed"] == "1000.00" and p["counts"] == {"INVOICED": 1}
    assert statement(client, admin, c)["balance"] == "0.00"
    assert conn_now(client, admin, conn)["next_due_date"] == "2026-10-09"
    assert db.scalar(select(func.count()).select_from(Invoice)) == 0
    assert db.scalar(select(func.count()).select_from(BillingRun)) == 0


def test_a_real_run_requires_explicit_confirmation(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c)
    r = client.post(f"{API}/billing/runs", headers=admin, json={"run_date": RUN})
    assert r.status_code == 422
    r = client.post(f"{API}/billing/runs", headers=admin, json={"run_date": RUN, "confirm": False})
    assert r.status_code == 422
    assert statement(client, admin, c)["balance"] == "0.00"


# ------------------------------------------------------------------ the run itself
def test_run_bills_a_due_connection_and_advances_the_due_date(client, admin, mk_customer):
    c = mk_customer()
    conn = mk_conn(client, admin, c, due="2026-10-09")
    result = run(client, admin)
    assert result["invoices_created"] == 1 and result["total_billed"] == "1000.00"

    st = statement(client, admin, c)
    assert st["balance"] == "1000.00" and st["billing_status"] == "DUE"
    inv = st["open_invoices"][0]
    assert inv["issue_date"] == RUN and inv["due_date"] == "2026-10-09" and inv["period"] == "2026-10-01"
    assert inv["total"] == "1000.00" and inv["lines"][0]["charge_type"] == "INTERNET"
    assert "09 Oct 2026 - 08 Nov 2026" in inv["lines"][0]["description"]
    assert conn_now(client, admin, conn)["next_due_date"] == "2026-11-09"

    runs = client.get(f"{API}/billing/runs", headers=admin).json()
    assert len(runs) == 1 and runs[0]["kind"] == "MONTHLY" and runs[0]["invoices_created"] == 1
    items = client.get(f"{API}/billing/runs/{result['run_id']}/items", headers=admin).json()
    assert [i["outcome"] for i in items] == ["INVOICED"] and items[0]["invoice_id"] == inv["id"]


def test_running_again_creates_nothing_new(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c)
    run(client, admin)
    again = run(client, admin)
    assert again["invoices_created"] == 0 and again["items"] == []
    assert statement(client, admin, c)["balance"] == "1000.00"


def test_connection_outside_the_lead_window_is_left_alone(client, admin, mk_customer):
    c = mk_customer()
    conn = mk_conn(client, admin, c, due="2026-10-20")
    assert run(client, admin)["invoices_created"] == 0
    assert run(client, admin, lead_days=20)["invoices_created"] == 1
    assert conn_now(client, admin, conn)["next_due_date"] == "2026-11-20"


def test_backlog_is_billed_one_cycle_per_run_and_reported(client, admin, mk_customer):
    c = mk_customer()
    conn = mk_conn(client, admin, c, due="2026-08-14")  # imported due date already in the past
    first = run(client, admin, lead_days=0)
    assert first["invoices_created"] == 1 and first["behind_connections"] == 1
    assert "1 more cycle(s) still due" in first["items"][0]["message"]
    inv = statement(client, admin, c)["open_invoices"][0]
    assert inv["due_date"] == RUN and inv["period"] == "2026-08-01"   # real cycle, due today
    assert conn_now(client, admin, conn)["next_due_date"] == "2026-09-14"

    second = run(client, admin, lead_days=0)
    assert second["invoices_created"] == 1 and second["behind_connections"] == 0
    assert run(client, admin, lead_days=0)["invoices_created"] == 0
    assert statement(client, admin, c)["balance"] == "2000.00"


def test_max_cycles_bills_all_missed_months_at_once(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c, due="2026-08-14")
    r = run(client, admin, lead_days=0, max_cycles=3)
    assert r["invoices_created"] == 2 and statement(client, admin, c)["balance"] == "2000.00"


def test_skip_remaining_reports_what_it_skipped(client, admin, mk_customer):
    c = mk_customer()
    conn = mk_conn(client, admin, c, due="2026-06-14")
    r = run(client, admin, lead_days=0, skip_remaining=True)
    assert r["skipped_cycles"] == 3 and r["invoices_created"] == 1
    assert "CYCLES_SKIPPED" in outcomes(r)
    skipped = next(i for i in r["items"] if i["outcome"] == "CYCLES_SKIPPED")
    assert "2026-07-14" in skipped["message"] and "2026-09-14" in skipped["message"]
    assert conn_now(client, admin, conn)["next_due_date"] == "2026-10-14"
    assert statement(client, admin, c)["balance"] == "1000.00"


def test_one_customer_with_two_connections_gets_one_invoice(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c, price="1000.00", due="2026-10-09")
    mk_conn(client, admin, c, price="300.00", service="CABLE", due="2026-10-09")
    r = run(client, admin)
    assert r["invoices_created"] == 1 and r["total_billed"] == "1300.00"
    inv = statement(client, admin, c)["open_invoices"]
    assert len(inv) == 1 and len(inv[0]["lines"]) == 2
    assert {ln["charge_type"] for ln in inv[0]["lines"]} == {"INTERNET", "CABLE"}


def test_combined_connection_bills_cable_and_internet_lines(client, admin, mk_customer):
    c = mk_customer()
    body = {"connection_type": "COMBINED", "next_due_date": "2026-10-09",
            "service_lines": [{"service": "INTERNET", "price": "1000.00"},
                              {"service": "CABLE", "price": "250.50"}]}
    assert client.post(f"{API}/customers/{c['id']}/connections", headers=admin, json=body).status_code == 201
    assert run(client, admin)["total_billed"] == "1250.50"


def test_special_price_override_wins(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c, price="1500.00", monthly_price_override="900.00")
    assert run(client, admin)["total_billed"] == "900.00"


def test_package_list_price_is_the_fallback(client, admin, mk_customer):
    pkg = client.post(f"{API}/packages", headers=admin, json={
        "code": "star3", "name": "Star3", "display_name": "Star 3", "internet_price": "1200.00"}).json()
    c = mk_customer()
    body = {"connection_type": "INTERNET", "next_due_date": "2026-10-09",
            "service_lines": [{"service": "INTERNET", "package_id": pkg["id"]}]}
    assert client.post(f"{API}/customers/{c['id']}/connections", headers=admin, json=body).status_code == 201
    assert run(client, admin)["total_billed"] == "1200.00"


def test_free_and_trial_connections_are_rolled_forward_without_a_charge(client, admin, mk_customer):
    c = mk_customer()
    free = mk_conn(client, admin, c, status="FREE")
    trial = mk_conn(client, admin, c, status="TRIAL")
    r = run(client, admin)
    assert r["invoices_created"] == 0 and outcomes(r) == ["FREE_SKIPPED", "FREE_SKIPPED"]
    assert statement(client, admin, c)["balance"] == "0.00"
    assert conn_now(client, admin, free)["next_due_date"] == "2026-11-09"
    assert conn_now(client, admin, trial)["next_due_date"] == "2026-11-09"
    assert statement(client, admin, c)["billing_status"] == "FREE"


def test_suspended_and_disconnected_connections_are_never_billed(client, admin, mk_customer):
    c = mk_customer()
    sus = mk_conn(client, admin, c, status="SUSPENDED")
    dis = mk_conn(client, admin, c, status="DISCONNECTED")
    r = run(client, admin)
    assert r["invoices_created"] == 0 and r["items"] == []
    assert conn_now(client, admin, sus)["next_due_date"] == "2026-10-09"
    assert conn_now(client, admin, dis)["next_due_date"] == "2026-10-09"


def test_archived_customers_are_not_billed(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c)
    assert client.post(f"{API}/customers/{c['id']}/archive", headers=admin).status_code == 200
    assert run(client, admin)["invoices_created"] == 0


def test_unpriced_connection_is_flagged_and_not_advanced(client, admin, mk_customer):
    c = mk_customer()
    conn = mk_conn(client, admin, c, price=None)
    r = run(client, admin)
    assert r["invoices_created"] == 0 and outcomes(r) == ["ZERO_PRICE"]
    assert "fix the price" in r["items"][0]["message"]
    assert conn_now(client, admin, conn)["next_due_date"] == "2026-10-09"  # shows up again next run


def test_active_connection_without_a_due_date_is_flagged(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c, due=None)
    r = run(client, admin)
    assert outcomes(r) == ["NO_DUE_DATE"] and r["invoices_created"] == 0


def test_one_bad_customer_does_not_stop_the_run(client, admin, db, mk_customer):
    good, bad = mk_customer("Good"), mk_customer("Bad")
    mk_conn(client, admin, good)
    conn = mk_conn(client, admin, bad, due="1900-01-01")   # implausible date: planning raises
    r = run(client, admin)   # default lead window: the good customer (due 9 Oct) is billed
    assert r["invoices_created"] == 1 and sorted(r["counts"]) == ["ERROR", "INVOICED"]
    assert statement(client, admin, good)["balance"] == "1000.00"
    assert statement(client, admin, bad)["balance"] == "0.00"
    assert conn_now(client, admin, conn)["next_due_date"] == "1900-01-01"


def test_concurrent_runs_never_double_bill(client, admin, mk_customer):
    customers = [mk_customer(f"Cust {i}") for i in range(5)]
    for c in customers:
        mk_conn(client, admin, c)

    def go(_):
        with TestClient(app) as cl:
            return cl.post(f"{API}/billing/runs", headers=admin,
                           json={"run_date": RUN, "confirm": True}).json()["invoices_created"]

    with ThreadPoolExecutor(max_workers=4) as ex:
        created = list(ex.map(go, range(4)))
    assert sum(created) == 5
    for c in customers:
        assert statement(client, admin, c)["balance"] == "1000.00"


# ------------------------------------------------------------------ advance payments
def test_an_advance_payment_settles_the_next_invoice(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c)
    pay = client.post(f"{API}/payments", headers=admin,
                      json={"customer_id": c["id"], "amount": "1000.00", "method": "CASH"})
    assert pay.json()["unallocated"] == "1000.00"
    run(client, admin)
    st = statement(client, admin, c)
    assert st["balance"] == "0.00" and st["open_invoices"] == [] and st["billing_status"] == "PAID"


def test_a_refunded_advance_is_not_applied_twice(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c)
    client.post(f"{API}/payments", headers=admin,
                json={"customer_id": c["id"], "amount": "1000.00", "method": "CASH"})
    client.post(f"{API}/refunds", headers=admin,
                json={"customer_id": c["id"], "amount": "1000.00", "reason": "customer left and returned"})
    run(client, admin)
    st = statement(client, admin, c)
    assert st["balance"] == "1000.00" and len(st["open_invoices"]) == 1


def test_a_partial_advance_leaves_the_rest_due(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c)
    client.post(f"{API}/payments", headers=admin,
                json={"customer_id": c["id"], "amount": "400.00", "method": "CASH"})
    run(client, admin)
    st = statement(client, admin, c)
    assert st["balance"] == "600.00" and st["open_invoices"][0]["outstanding"] == "600.00"
    assert st["billing_status"] == "PARTIAL"


# ------------------------------------------------------------------ late fees
def _overdue_invoice(client, h, cust, amount="1000.00", due="2026-09-01"):
    r = client.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust["id"], "issue_date": min(due, "2026-08-01"), "due_date": due,
        "lines": [{"charge_type": "INTERNET", "amount": amount}]})
    assert r.status_code == 201, r.text
    return r.json()


def _fees(client, h, execute=False, **kw):
    path = "/billing/late-fees" if execute else "/billing/late-fees/preview"
    body = {"run_date": "2026-09-20", "amount": "50.00", "grace_days": 5, **kw}
    if execute:
        body["confirm"] = True
    return client.post(f"{API}{path}", headers=h, json=body)


def test_late_fees_are_disabled_by_default(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c)
    r = client.post(f"{API}/billing/late-fees/preview", headers=admin, json={"run_date": "2026-09-20"})
    assert r.status_code == 409 and "disabled" in r.json()["detail"]


def test_late_fee_is_charged_once_per_overdue_invoice(client, admin, db, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c, due="2030-01-01")
    _overdue_invoice(client, admin, c)
    pv = _fees(client, admin).json()
    assert pv["dry_run"] is True and pv["counts"] == {"LATE_FEE": 1} and pv["total_billed"] == "50.00"
    assert statement(client, admin, c)["balance"] == "1000.00"   # preview wrote nothing

    done = _fees(client, admin, execute=True)
    assert done.status_code == 201 and done.json()["total_billed"] == "50.00"
    st = statement(client, admin, c)
    assert st["balance"] == "1050.00"
    assert {i["lines"][0]["charge_type"] for i in st["open_invoices"]} == {"INTERNET", "LATE_FEE"}
    assert db.scalar(select(func.count()).select_from(LateFee)) == 1

    again = _fees(client, admin, execute=True).json()        # never charged twice for one invoice
    assert again["items"] == [] and statement(client, admin, c)["balance"] == "1050.00"


def test_no_late_fee_inside_the_grace_period_or_when_paid(client, admin, mk_customer):
    a, b = mk_customer("Within grace"), mk_customer("Paid")
    mk_conn(client, admin, a, due="2030-01-01")
    mk_conn(client, admin, b, due="2030-01-01")
    _overdue_invoice(client, admin, a, due="2026-09-18")          # only 2 days late on the 20th
    _overdue_invoice(client, admin, b)
    client.post(f"{API}/payments", headers=admin,
                json={"customer_id": b["id"], "amount": "1000.00", "method": "CASH"})
    assert _fees(client, admin).json()["items"] == []


def test_fully_disconnected_customers_and_opening_balances_are_not_charged(client, admin, mk_customer):
    gone, old = mk_customer("Gone"), mk_customer("Old dues")
    mk_conn(client, admin, gone, status="DISCONNECTED", due="2030-01-01")
    _overdue_invoice(client, admin, gone)
    mk_conn(client, admin, old, due="2030-01-01")
    load = client.post(f"{API}/billing/opening-balances", headers=admin, json={
        "dry_run": False, "as_of_date": "2026-08-01",
        "rows": [{"customer_id": old["id"], "amount": "700.00"}]})
    assert load.json()["counts"] == {"CREATED": 1}
    assert _fees(client, admin).json()["items"] == []


def test_late_fee_invoices_do_not_earn_late_fees(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c, due="2030-01-01")
    _overdue_invoice(client, admin, c)
    _fees(client, admin, execute=True)
    later = _fees(client, admin, run_date="2026-12-01", execute=True).json()
    assert later["items"] == []
    assert statement(client, admin, c)["balance"] == "1050.00"


# ------------------------------------------------------------------ opening balances (optional)
def test_opening_balances_preview_then_load(client, admin, db, mk_customer):
    c = mk_customer()
    rows = [{"customer_id": c["id"], "amount": "2500.00", "note": "old register"}]
    pv = client.post(f"{API}/billing/opening-balances", headers=admin, json={"rows": rows}).json()
    assert pv["dry_run"] is True and pv["counts"] == {"WOULD_CREATE": 1}
    assert statement(client, admin, c)["balance"] == "0.00"

    done = client.post(f"{API}/billing/opening-balances", headers=admin,
                       json={"rows": rows, "dry_run": False, "as_of_date": "2026-09-30"}).json()
    assert done["counts"] == {"CREATED": 1}
    st = statement(client, admin, c)
    assert st["balance"] == "2500.00" and st["open_invoices"][0]["lines"][0]["charge_type"] == "OTHER"

    again = client.post(f"{API}/billing/opening-balances", headers=admin,
                        json={"rows": rows, "dry_run": False}).json()
    assert again["counts"] == {"ALREADY_EXISTS": 1} and statement(client, admin, c)["balance"] == "2500.00"
    # and a later payment pays the old dues like any invoice
    client.post(f"{API}/payments", headers=admin,
                json={"customer_id": c["id"], "amount": "2500.00", "method": "CASH"})
    assert statement(client, admin, c)["balance"] == "0.00"


def test_opening_balance_rows_are_validated_not_guessed(client, admin, mk_customer):
    c = mk_customer()
    rows = [{"customer_id": c["id"], "amount": "-5.00"},
            {"customer_id": c["id"], "amount": "10.555"},
            {"customer_id": c["id"], "amount": "abc"},
            {"wasooli_id": "no-such-id", "amount": "10.00"},
            {"amount": "10.00"}]
    r = client.post(f"{API}/billing/opening-balances", headers=admin, json={"rows": rows}).json()
    assert r["counts"] == {"INVALID": 3, "NOT_FOUND": 2}
    assert statement(client, admin, c)["balance"] == "0.00"


def test_duplicate_rows_in_one_load_create_one_balance(client, admin, mk_customer):
    c = mk_customer()
    rows = [{"customer_id": c["id"], "amount": "100.00"}, {"customer_id": c["id"], "amount": "200.00"}]
    r = client.post(f"{API}/billing/opening-balances", headers=admin,
                    json={"rows": rows, "dry_run": False}).json()
    assert r["counts"] == {"CREATED": 1, "ALREADY_EXISTS": 1}
    assert statement(client, admin, c)["balance"] == "100.00"


# ------------------------------------------------------------------ connection status
def test_suspend_then_reconnect_with_fee(client, admin, mk_customer):
    c = mk_customer()
    conn = mk_conn(client, admin, c, due="2026-10-09")
    url = f"{API}/connections/{conn['id']}/status"

    r = client.post(url, headers=admin, json={"status": "SUSPENDED", "reason": "non-payment"})
    assert r.status_code == 200 and r.json()["previous_status"] == "ACTIVE"
    assert run(client, admin)["invoices_created"] == 0          # suspended: not billed

    r = client.post(url, headers=admin, json={"status": "ACTIVE", "reason": "paid up",
                                              "reconnection_fee": "500.00", "next_due_date": RUN})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["connection"]["status"] == "ACTIVE" and out["connection"]["next_due_date"] == RUN
    assert out["reconnection_invoice"]["total"] == "500.00"
    assert out["reconnection_invoice"]["lines"][0]["charge_type"] == "RECONNECTION"
    assert statement(client, admin, c)["balance"] == "500.00"
    assert run(client, admin)["total_billed"] == "1000.00"       # billing resumes


def test_status_change_rules(client, admin, mk_customer):
    c = mk_customer()
    conn = mk_conn(client, admin, c)
    url = f"{API}/connections/{conn['id']}/status"
    assert client.post(url, headers=admin, json={"status": "ACTIVE", "reason": "same"}).status_code == 409
    assert client.post(url, headers=admin, json={"status": "SUSPENDED", "reason": "x"}).status_code == 422
    assert client.post(url, headers=admin, json={
        "status": "SUSPENDED", "reason": "no payment", "reconnection_fee": "100.00"}).status_code == 422
    assert client.post(url, headers=admin, json={
        "status": "DISCONNECTED", "reason": "no payment", "next_due_date": RUN}).status_code == 422
    assert client.post(f"{API}/connections/{c['id']}/status", headers=admin, json={
        "status": "SUSPENDED", "reason": "no payment"}).status_code == 404


# ------------------------------------------------------------------ reports
def test_outstanding_and_suspension_reports(client, admin, mk_customer):
    owes, clear = mk_customer("Owes"), mk_customer("Clear")
    conn = mk_conn(client, admin, owes, due="2030-01-01")
    mk_conn(client, admin, clear, due="2030-01-01")
    _overdue_invoice(client, admin, owes, amount="1500.00", due="2026-06-01")

    rows = client.get(f"{API}/billing/outstanding", headers=admin).json()
    assert [r["customer_id"] for r in rows] == [owes["id"]]
    assert rows[0]["balance"] == "1500.00" and rows[0]["oldest_due_date"] == "2026-06-01"
    assert rows[0]["billing_status"] == "OVERDUE" and rows[0]["days_overdue"] > 0

    cands = client.get(f"{API}/billing/suspension-candidates", headers=admin,
                       params={"overdue_days": 30}).json()
    assert [r["customer_id"] for r in cands] == [owes["id"]] and cands[0]["connection_ids"] == [conn["id"]]
    assert cands[0]["outstanding"] == "1500.00"
    # reading the report suspends nobody
    assert conn_now(client, admin, conn)["status"] == "ACTIVE"


def test_customer_status_for_disconnected_customer(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c, status="DISCONNECTED")
    assert statement(client, admin, c)["billing_status"] == "DISCONNECTED"


# ------------------------------------------------------------------ permissions & audit
def test_permissions(client, admin, make_user, mk_customer):
    c = mk_customer()
    conn = mk_conn(client, admin, c)
    collector = make_user("collector")[1]
    manager = make_user("manager")[1]
    accountant = make_user("accountant")[1]
    for h in (collector, manager):
        assert client.post(f"{API}/billing/runs/preview", headers=h, json={}).status_code == 403
        assert client.post(f"{API}/billing/runs", headers=h, json={"confirm": True}).status_code == 403
        assert client.post(f"{API}/billing/late-fees", headers=h, json={"confirm": True}).status_code == 403
        assert client.post(f"{API}/billing/opening-balances", headers=h, json={
            "rows": [{"amount": "1.00"}]}).status_code == 403
        assert client.post(f"{API}/connections/{conn['id']}/status", headers=h, json={
            "status": "SUSPENDED", "reason": "nope nope"}).status_code == 403
    assert client.get(f"{API}/billing/outstanding", headers=collector).status_code == 403
    assert client.get(f"{API}/billing/outstanding", headers=manager).status_code == 200
    assert client.post(f"{API}/billing/runs/preview", headers=accountant, json={"run_date": RUN}).status_code == 200
    # accountants run billing but do not change service status
    assert client.post(f"{API}/connections/{conn['id']}/status", headers=accountant, json={
        "status": "SUSPENDED", "reason": "nope nope"}).status_code == 403
    assert client.post(f"{API}/billing/runs/preview", json={}).status_code == 401


def test_runs_and_status_changes_are_audited(client, admin, mk_customer):
    c = mk_customer()
    conn = mk_conn(client, admin, c)
    run(client, admin)
    client.post(f"{API}/connections/{conn['id']}/status", headers=admin,
                json={"status": "SUSPENDED", "reason": "non-payment"})
    actions = {a["action"] for a in client.get(f"{API}/audit-logs", headers=admin, params={"limit": 200}).json()}
    assert {"billing.run", "connection.status"} <= actions


def test_new_permissions_reach_existing_roles_without_undoing_admin_choices(db):
    # Simulate a database created before Phase 3: the new permissions do not exist yet.
    for code in ("billing.run", "billing.opening_balance", "connection.status"):
        perm = db.scalar(select(Permission).where(Permission.code == code))
        for role in db.scalars(select(Role)):
            if perm in role.permissions:
                role.permissions.remove(perm)
        db.delete(perm)
    # ...and an admin had deliberately removed an older permission from accountants.
    accountant = db.scalar(select(Role).where(Role.code == "accountant"))
    accountant.permissions = [p for p in accountant.permissions if p.code != "invoice.create"]
    db.commit()

    seed_rbac(db)
    db.commit()
    db.expire_all()
    roles = {r.code: {p.code for p in r.permissions} for r in db.scalars(select(Role))}
    assert {"billing.run", "billing.opening_balance"} <= roles["accountant"]
    assert "connection.status" in roles["admin"] and "connection.status" not in roles["accountant"]
    assert "billing.run" in roles["super_admin"] and "billing.run" not in roles["collector"]
    assert "invoice.create" not in roles["accountant"]            # the admin's choice is respected


# ------------------------------------------------------------------ importer feeds the cycle
def test_import_sets_the_next_due_date_and_billing_can_use_it(client, admin, db, tmp_path):
    pdf = make_pdf(tmp_path / "w.pdf", [pdf_row(1, ID="9001", **{"Recharge Date": "31/Aug/2026"})])
    sid = upload(client, admin, pdf).json()["id"]
    assert client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=admin).status_code == 200
    conn = db.scalar(select(Connection))
    assert conn.next_due_date == date(2026, 8, 31) and conn.billing_day == 31
    assert conn.source_recharge_date == date(2026, 8, 31)

    r = run(client, admin, lead_days=0)
    assert r["invoices_created"] == 1 and r["total_billed"] == "1000.00"
    db.expire_all()
    assert db.scalar(select(Connection)).next_due_date == date(2026, 9, 30)  # month-end clamp, anchored on 31
    assert db.scalar(select(func.count()).select_from(Customer)) == 1


# ------------------------------------------------------------------ "what does Recharge Date mean?"
def _import_one(client, admin, tmp_path, recharge="31/Aug/2026"):
    pdf = make_pdf(tmp_path / "w.pdf", [pdf_row(1, ID="9001", **{"Recharge Date": recharge})])
    sid = upload(client, admin, pdf).json()["id"]
    assert client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=admin).status_code == 200


def test_last_recharge_setting_moves_the_imported_due_date_a_month_forward(
        client, admin, db, tmp_path, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "recharge_date_means", "LAST_RECHARGE")
    _import_one(client, admin, tmp_path)
    conn = db.scalar(select(Connection))
    assert conn.source_recharge_date == date(2026, 8, 31)       # the export is kept exactly as given
    assert conn.next_due_date == date(2026, 9, 30) and conn.billing_day == 31


def test_rebase_cli_previews_then_moves_unbilled_due_dates_once(client, admin, db, tmp_path):
    from app.rebase_due_dates_cli import main
    _import_one(client, admin, tmp_path)
    assert main([]) == 0                                         # preview writes nothing
    db.expire_all()
    assert db.scalar(select(Connection)).next_due_date == date(2026, 8, 31)
    assert main(["--commit"]) == 0
    db.expire_all()
    assert db.scalar(select(Connection)).next_due_date == date(2026, 9, 30)
    assert main(["--commit"]) == 0                               # a second run changes nothing
    db.expire_all()
    assert db.scalar(select(Connection)).next_due_date == date(2026, 9, 30)


def test_rebase_cli_never_touches_a_connection_that_was_already_billed(client, admin, db, tmp_path):
    from app.rebase_due_dates_cli import main
    _import_one(client, admin, tmp_path)
    run(client, admin, lead_days=0)
    db.expire_all()
    after_billing = db.scalar(select(Connection)).next_due_date
    assert main(["--commit"]) == 0
    db.expire_all()
    assert db.scalar(select(Connection)).next_due_date == after_billing
