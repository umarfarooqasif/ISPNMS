"""Stage 5: dashboard numbers, collection reports and CSV exports."""

import csv
import io
from datetime import date

import pytest

from app.models import AuditLog  # noqa: F401  (imported so a missing model fails loudly)
from sqlalchemy import select

API = "/api/v1"
TODAY = date(2026, 10, 4)


@pytest.fixture(autouse=True)
def _pinned_today(monkeypatch):
    monkeypatch.setattr("app.services.billing.local_today", lambda: TODAY)


def invoice(client, h, cust, amount, issue="2026-10-01", due="2026-10-15"):
    r = client.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust["id"], "issue_date": issue, "due_date": due,
        "lines": [{"charge_type": "INTERNET", "amount": amount}]})
    assert r.status_code == 201, r.text
    return r.json()


def pay(client, h, cust, amount, when, method="CASH"):
    r = client.post(f"{API}/payments", headers=h, json={
        "customer_id": cust["id"], "amount": amount, "method": method, "collected_at": when})
    assert r.status_code == 201, r.text
    return r.json()


def rows_of(response):
    assert response.status_code == 200, response.text
    return list(csv.reader(io.StringIO(response.content.decode("utf-8").lstrip("\ufeff"))))


# ------------------------------------------------------------------ dashboard
def test_dashboard_numbers_are_right(client, admin, mk_customer):
    a, b = mk_customer("Ali"), mk_customer("Bilal")
    invoice(client, admin, a, "2000.00")
    invoice(client, admin, b, "1000.00")
    pay(client, admin, a, "500.00", "2026-10-04T10:00:00+05:00")      # today
    pay(client, admin, b, "300.00", "2026-10-02T10:00:00+05:00")      # earlier this month
    pay(client, admin, a, "9999.00", "2026-09-20T10:00:00+05:00")     # last month: not this month's collection

    d = client.get(f"{API}/reports/dashboard", headers=admin).json()
    assert d["as_of"] == "2026-10-04"
    assert d["today_collected"] == "500.00" and d["today_payments"] == 1
    assert d["month_label"] == "2026-10"
    assert d["month_billed"] == "3000.00" and d["month_collected"] == "800.00" and d["month_payments"] == 2
    assert d["collection_rate"] == "26.7"
    # balances: Ali 2000-500-9999 = credit (not owed), Bilal 1000-300 = 700
    assert d["outstanding_total"] == "700.00" and d["outstanding_customers"] == 1
    assert len(d["daily"]) == 30 and d["daily"][-1]["day"] == "2026-10-04" and d["daily"][-1]["total"] == "500.00"
    assert len(d["monthly"]) == 12 and d["monthly"][-1]["month"] == "2026-10-01"
    assert d["monthly"][-1] == {"month": "2026-10-01", "billed": "3000.00", "collected": "800.00"}
    assert d["monthly"][-2]["collected"] == "9999.00" and d["monthly"][-2]["billed"] == "0.00"


def test_dashboard_on_an_empty_system_is_all_zeros_not_an_error(client, admin):
    d = client.get(f"{API}/reports/dashboard", headers=admin).json()
    assert d["today_collected"] == "0.00" and d["month_billed"] == "0.00" and d["collection_rate"] is None
    assert d["outstanding_total"] == "0.00" and d["outstanding_customers"] == 0
    assert d["connections_by_status"] == {} and d["collectors_this_month"] == [] and d["outstanding_by_area"] == []
    assert len(d["daily"]) == 30 and all(x["total"] == "0.00" for x in d["daily"])


def test_cancelled_payments_never_count(client, admin, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, "1000.00")
    p = pay(client, admin, c, "400.00", "2026-10-04T09:00:00+05:00")
    assert client.post(f"{API}/payments/{p['id']}/void", headers=admin, json={"reason": "entered by mistake"}).status_code == 200
    d = client.get(f"{API}/reports/dashboard", headers=admin).json()
    assert d["today_collected"] == "0.00" and d["month_collected"] == "0.00" and d["outstanding_total"] == "1000.00"


def test_opening_balances_are_not_counted_as_billed(client, admin, mk_customer):
    c = mk_customer()
    r = client.post(f"{API}/billing/opening-balances", headers=admin, json={
        "dry_run": False, "as_of_date": "2026-10-02", "rows": [{"customer_id": c["id"], "amount": "5000.00"}]})
    assert r.json()["counts"] == {"CREATED": 1}
    invoice(client, admin, c, "1000.00")
    d = client.get(f"{API}/reports/dashboard", headers=admin).json()
    assert d["month_billed"] == "1000.00"                       # the carried-over 5,000 is not this month's billing
    assert d["outstanding_total"] == "6000.00"                  # but it is still owed


def test_outstanding_is_grouped_by_area_and_connections_by_status(client, admin, mk_customer):
    qadir = client.post(f"{API}/areas", headers=admin, json={"name": "Qadir Colony"}).json()
    a, b, c = mk_customer("A", area_id=qadir["id"]), mk_customer("B", area_id=qadir["id"]), mk_customer("C")
    for cust, amt in ((a, "1000.00"), (b, "500.00"), (c, "250.00")):
        invoice(client, admin, cust, amt)
    client.post(f"{API}/customers/{a['id']}/connections", headers=admin, json={"connection_type": "INTERNET", "status": "ACTIVE", "service_lines": []})
    client.post(f"{API}/customers/{b['id']}/connections", headers=admin, json={"connection_type": "INTERNET", "status": "DISCONNECTED", "service_lines": []})
    d = client.get(f"{API}/reports/dashboard", headers=admin).json()
    assert d["outstanding_by_area"] == [{"area": "Qadir Colony", "customers": 2, "total": "1500.00"},
                                        {"area": "No area", "customers": 1, "total": "250.00"}]
    assert d["connections_by_status"] == {"ACTIVE": 1, "DISCONNECTED": 1}


# ------------------------------------------------------------------ collection reports
def test_daily_report_has_a_row_for_every_day_in_local_time(client, admin, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, "5000.00")
    pay(client, admin, c, "100.00", "2026-10-02T09:00:00+05:00")
    pay(client, admin, c, "50.00", "2026-10-02T18:00:00+05:00")
    pay(client, admin, c, "70.00", "2026-10-03T23:30:00+05:00")      # 18:30 UTC, still the 3rd in Karachi
    pay(client, admin, c, "30.00", "2026-10-04T00:10:00+05:00")      # 19:10 UTC on the 3rd, but the 4th locally
    rows = client.get(f"{API}/reports/collections/daily", headers=admin,
                      params={"date_from": "2026-10-01", "date_to": "2026-10-05"}).json()
    assert [(r["day"], r["total"], r["count"]) for r in rows] == [
        ("2026-10-01", "0.00", 0), ("2026-10-02", "150.00", 2), ("2026-10-03", "70.00", 1),
        ("2026-10-04", "30.00", 1), ("2026-10-05", "0.00", 0)]


def test_range_defaults_and_validation(client, admin):
    ok = client.get(f"{API}/reports/collections/daily", headers=admin).json()
    assert ok[0]["day"] == "2026-10-01" and ok[-1]["day"] == "2026-10-04"      # this month so far
    bad = client.get(f"{API}/reports/collections/daily", headers=admin, params={"date_from": "2026-10-05", "date_to": "2026-10-01"})
    assert bad.status_code == 422 and "before the start" in bad.json()["detail"]
    long = client.get(f"{API}/reports/collections/daily", headers=admin, params={"date_from": "2024-01-01", "date_to": "2026-10-01"})
    assert long.status_code == 422 and "at most" in long.json()["detail"]


def test_by_method_and_by_collector(client, admin, make_user, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, "9000.00")
    pay(client, admin, c, "1000.00", "2026-10-03T10:00:00+05:00", "CASH")
    pay(client, admin, c, "500.00", "2026-10-03T11:00:00+05:00", "JAZZCASH")
    pay(client, admin, c, "250.00", "2026-10-03T12:00:00+05:00", "CASH")

    methods = client.get(f"{API}/reports/collections/by-method", headers=admin,
                         params={"date_from": "2026-10-01", "date_to": "2026-10-04"}).json()
    assert methods == [{"method": "CASH", "total": "1250.00", "count": 2}, {"method": "JAZZCASH", "total": "500.00", "count": 1}]

    by = client.get(f"{API}/reports/collections/by-collector", headers=admin,
                    params={"date_from": "2026-10-01", "date_to": "2026-10-04"}).json()
    assert by == [{"collector_id": None, "code": "OFFICE", "name": "Received at the office", "total": "1750.00", "count": 3}]


def test_monthly_report_lists_every_month(client, admin, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, "1000.00", issue="2026-08-05", due="2026-08-20")
    pay(client, admin, c, "400.00", "2026-09-10T10:00:00+05:00")
    rows = client.get(f"{API}/reports/monthly", headers=admin, params={"months": 3}).json()
    assert [r["month"] for r in rows] == ["2026-08-01", "2026-09-01", "2026-10-01"]
    assert [(r["billed"], r["collected"]) for r in rows] == [("1000.00", "0.00"), ("0.00", "400.00"), ("0.00", "0.00")]
    assert client.get(f"{API}/reports/monthly", headers=admin, params={"months": 99}).status_code == 422


# ------------------------------------------------------------------ CSV exports
def test_payments_export_is_a_real_excel_friendly_csv(client, admin, mk_customer):
    c = mk_customer("علی خان")
    invoice(client, admin, c, "2000.00")
    p = pay(client, admin, c, "500.00", "2026-10-03T15:20:00+05:00")
    r = client.get(f"{API}/reports/export/payments.csv", headers=admin, params={"date_from": "2026-10-01", "date_to": "2026-10-04"})
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="payments_2026-10-01_to_2026-10-04.csv"' in r.headers["content-disposition"]
    assert r.content.startswith("\ufeff".encode("utf-8"))               # Excel reads the Urdu correctly
    table = rows_of(r)
    assert table[0] == ["date_time", "receipt_no", "paper_receipt_no", "customer_id", "customer_name", "method", "amount", "status", "collector", "notes"]
    assert table[1] == ["2026-10-03 15:20", p["receipt_number"], "", c["customer_code"], "علی خان", "CASH", "500.00", "POSTED", "", ""]
    assert len(table) == 2


def test_cancelled_payments_appear_in_the_export_marked_void(client, admin, mk_customer):
    c = mk_customer()
    invoice(client, admin, c, "1000.00")
    p = pay(client, admin, c, "400.00", "2026-10-03T10:00:00+05:00")
    client.post(f"{API}/payments/{p['id']}/void", headers=admin, json={"reason": "mistake"})
    table = rows_of(client.get(f"{API}/reports/export/payments.csv", headers=admin, params={"date_from": "2026-10-01", "date_to": "2026-10-04"}))
    assert [row[7] for row in table[1:]] == ["VOID"]


def test_text_that_looks_like_a_formula_is_neutralised_but_money_is_not(client, admin, mk_customer):
    c = mk_customer("=HYPERLINK(\"http://evil\",\"x\")")
    invoice(client, admin, c, "100.00")
    client.post(f"{API}/adjustments", headers=admin, json={"customer_id": c["id"], "amount": "-25.00", "reason": "credit"})
    table = rows_of(client.get(f"{API}/reports/export/customers.csv", headers=admin))
    assert table[1][1].startswith("'=")                                   # the name cannot run as a formula
    assert table[1][-1] == "75.00"


def test_invoices_export_shows_paid_and_owed(client, admin, mk_customer):
    c = mk_customer()
    inv = invoice(client, admin, c, "1000.00", issue="2026-10-01", due="2026-10-15")
    pay(client, admin, c, "400.00", "2026-10-02T10:00:00+05:00")
    table = rows_of(client.get(f"{API}/reports/export/invoices.csv", headers=admin, params={"date_from": "2026-10-01", "date_to": "2026-10-31"}))
    assert table[0][:3] == ["invoice_no", "issue_date", "due_date"]
    assert table[1][0] == inv["invoice_number"] and table[1][6:10] == ["1000.00", "400.00", "600.00", "PARTIAL"]


def test_outstanding_export_lists_who_owes_with_days_overdue(client, admin, mk_customer):
    big, small = mk_customer("Big Debtor"), mk_customer("Small Debtor", mobile="03001234567")
    invoice(client, admin, big, "5000.00", issue="2026-08-01", due="2026-09-04")
    invoice(client, admin, small, "100.00", issue="2026-10-01", due="2026-10-15")
    table = rows_of(client.get(f"{API}/reports/export/outstanding.csv", headers=admin))
    assert [row[1] for row in table[1:]] == ["Big Debtor", "Small Debtor"]           # biggest first
    assert table[1][4:] == ["5000.00", "2026-09-04", "30"]
    assert table[2][2] == "03001234567" and table[2][6] == "0"                       # not yet due: 0 days late


def test_customer_export_never_contains_the_cnic(client, admin, mk_customer):
    mk_customer("Has Cnic", cnic="35202-1234567-1")
    body = client.get(f"{API}/reports/export/customers.csv", headers=admin).content.decode("utf-8")
    assert "Has Cnic" in body and "3520212345671" not in body and "35202-1234567-1" not in body


def test_too_many_rows_is_refused_not_truncated(client, admin, mk_customer, monkeypatch):
    for n in range(2):
        mk_customer(f"Cust {n}")
    monkeypatch.setattr("app.services.reports.MAX_EXPORT_ROWS", 1)
    r = client.get(f"{API}/reports/export/customers.csv", headers=admin)
    assert r.status_code == 413 and "shorter" in r.json()["detail"]


def test_every_export_is_audited(client, admin, db, mk_customer):
    mk_customer()
    client.get(f"{API}/reports/export/customers.csv", headers=admin)
    client.get(f"{API}/reports/export/payments.csv", headers=admin)
    logs = db.scalars(select(AuditLog).where(AuditLog.action == "report.export")).all()
    assert sorted(l.after["report"] for l in logs) == ["customers", "payments"]


# ------------------------------------------------------------------ permissions
def test_who_can_see_and_who_can_download(client, admin, make_user):
    manager = make_user("manager")[1]          # may view reports, not download customer data
    accountant = make_user("accountant")[1]    # may do both
    collector = make_user("collector")[1]
    technician = make_user("technician")[1]

    for h in (manager, accountant, admin):
        assert client.get(f"{API}/reports/dashboard", headers=h).status_code == 200
        assert client.get(f"{API}/reports/collections/daily", headers=h).status_code == 200
    for h in (collector, technician):
        assert client.get(f"{API}/reports/dashboard", headers=h).status_code == 403
        assert client.get(f"{API}/reports/export/customers.csv", headers=h).status_code == 403

    assert client.get(f"{API}/reports/export/customers.csv", headers=manager).status_code == 403
    assert client.get(f"{API}/reports/export/payments.csv", headers=manager).status_code == 403
    assert client.get(f"{API}/reports/export/customers.csv", headers=accountant).status_code == 200
    assert client.get(f"{API}/reports/dashboard").status_code == 401
    assert client.get(f"{API}/reports/export/customers.csv").status_code == 401
