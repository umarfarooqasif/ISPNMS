"""Stage 6a: editable business settings, late fees and credits, changing a connection's package."""

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.models import AuditLog, Connection
from tests.test_billing_run import RUN, _overdue_invoice, conn_now, mk_conn, preview, run, statement
from tests.test_import import make_pdf, pdf_row, upload

API = "/api/v1"


@pytest.fixture(autouse=True)
def _pinned_today(monkeypatch):
    monkeypatch.setattr("app.services.billing.local_today", lambda: date(2026, 10, 4))


def put(client, h, values):
    return client.put(f"{API}/settings", headers=h, json={"values": values})


def settings(client, h):
    r = client.get(f"{API}/settings", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ settings
def test_settings_start_at_the_server_defaults(client, admin):
    s = settings(client, admin)
    assert s["overridden"] == [] and s["values"] == s["defaults"]
    assert set(s["values"]) == {"billing.lead_days", "late_fee.amount", "late_fee.grace_days", "late_fee.due_days",
                                "import.recharge_date_means", "company.name", "company.phone", "company.address"}
    assert s["labels"]["late_fee.amount"] == "Late fee per overdue bill"


def test_a_saved_value_overrides_and_null_goes_back_to_the_default(client, admin):
    default = settings(client, admin)["defaults"]["late_fee.amount"]
    s = put(client, admin, {"late_fee.amount": "75", "billing.lead_days": 9}).json()
    assert s["values"]["late_fee.amount"] == "75.00" and s["values"]["billing.lead_days"] == 9
    assert s["overridden"] == ["billing.lead_days", "late_fee.amount"]
    again = put(client, admin, {"late_fee.amount": None}).json()
    assert again["values"]["late_fee.amount"] == default and again["overridden"] == ["billing.lead_days"]


def test_nothing_is_saved_when_any_value_is_bad(client, admin):
    r = put(client, admin, {"billing.lead_days": 9, "late_fee.amount": "abc"})
    assert r.status_code == 422 and "Late fee" in r.json()["detail"]
    s = settings(client, admin)
    assert s["overridden"] == [] and s["values"]["billing.lead_days"] == s["defaults"]["billing.lead_days"]


def test_unknown_and_empty_requests_are_refused(client, admin):
    assert put(client, admin, {"billing.something_else": 1}).status_code == 422
    assert put(client, admin, {}).status_code == 422
    assert put(client, admin, {"billing.lead_days": 61}).status_code == 422
    assert put(client, admin, {"import.recharge_date_means": "SOMETIMES"}).status_code == 422


def test_only_settings_managers_can_read_or_change_settings(client, admin, make_user):
    for role in ("accountant", "manager", "collector", "technician"):
        h = make_user(role)[1]
        assert client.get(f"{API}/settings", headers=h).status_code == 403, role
        assert put(client, h, {"billing.lead_days": 1}).status_code == 403, role
    assert client.get(f"{API}/settings").status_code == 401


def test_changes_are_audited_with_before_and_after(client, admin, db):
    put(client, admin, {"late_fee.amount": "50"})
    put(client, admin, {"late_fee.amount": "80"})
    logs = db.scalars(select(AuditLog).where(AuditLog.action == "settings.update").order_by(AuditLog.id)).all()
    assert [(l.before, l.after) for l in logs] == [
        ({"late_fee.amount": None}, {"late_fee.amount": "50.00"}),
        ({"late_fee.amount": "50.00"}, {"late_fee.amount": "80.00"})]
    put(client, admin, {"late_fee.amount": "80"})            # saving the same value changes nothing, logs nothing
    assert len(db.scalars(select(AuditLog).where(AuditLog.action == "settings.update")).all()) == 2


def test_the_lead_days_setting_decides_what_the_bill_run_bills(client, admin, mk_customer):
    c = mk_customer()
    mk_conn(client, admin, c, due="2026-10-07")                      # due 3 days after the run date
    put(client, admin, {"billing.lead_days": 1})
    assert preview(client, admin)["invoices_created"] == 0
    put(client, admin, {"billing.lead_days": 5})
    assert preview(client, admin)["invoices_created"] == 1
    assert run(client, admin)["invoices_created"] == 1


def test_late_fee_settings_switch_late_fees_on_and_control_the_grace_period(client, admin, mk_customer):
    c = mk_customer()
    _overdue_invoice(client, admin, c)                               # due 2026-09-01
    off = client.post(f"{API}/billing/late-fees/preview", headers=admin, json={"run_date": "2026-09-20"})
    assert off.status_code == 409 and "disabled" in off.json()["detail"]

    put(client, admin, {"late_fee.amount": "50", "late_fee.grace_days": 5})
    on = client.post(f"{API}/billing/late-fees/preview", headers=admin, json={"run_date": "2026-09-20"}).json()
    assert on["counts"] == {"LATE_FEE": 1} and on["total_billed"] == "50.00"

    put(client, admin, {"late_fee.grace_days": 30})                  # grace now runs to 1 Oct, after the run date
    assert client.post(f"{API}/billing/late-fees/preview", headers=admin, json={"run_date": "2026-09-20"}).json()["items"] == []


def test_the_recharge_date_setting_applies_to_the_next_import(client, admin, db, tmp_path):
    put(client, admin, {"import.recharge_date_means": "LAST_RECHARGE"})
    pdf = make_pdf(tmp_path / "w.pdf", [pdf_row(1, ID="9001", **{"Recharge Date": "31/Aug/2026"})])
    sid = upload(client, admin, pdf).json()["id"]
    assert client.post(f"{API}/imports/{sid}/commit", json={"dry_run": False}, headers=admin).status_code == 200
    conn = db.scalar(select(Connection))
    assert str(conn.source_recharge_date) == "2026-08-31"            # the file is kept as given
    assert str(conn.next_due_date) == "2026-09-30"                   # one month after the last recharge


def test_company_details_are_readable_by_everyone_logged_in_but_only_changeable_by_managers(client, admin, make_user):
    collector = make_user("collector")[1]
    blank = client.get(f"{API}/settings/company", headers=collector).json()
    assert blank == {"name": "", "phone": "", "address": ""}
    put(client, admin, {"company.name": "  Fast   Net ", "company.phone": "042 1234567", "company.address": "Lahore"})
    assert client.get(f"{API}/settings/company", headers=collector).json() == {
        "name": "Fast Net", "phone": "042 1234567", "address": "Lahore"}
    assert client.get(f"{API}/settings/company").status_code == 401


def test_existing_roles_do_not_get_settings_access_by_accident(client, admin, make_user):
    # settings.manage is a new permission: admin has it, nobody else does
    assert client.get(f"{API}/settings", headers=admin).status_code == 200
    assert client.get(f"{API}/settings", headers=make_user("accountant")[1]).status_code == 403


# ------------------------------------------------------------------ late fees and credits
def _preview_fees(client, h, **kw):
    body = {"run_date": "2026-09-20", "amount": "50.00", "grace_days": 5, **kw}
    r = client.post(f"{API}/billing/late-fees/preview", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_customer_whose_account_is_in_credit_is_not_charged_a_late_fee(client, admin, mk_customer):
    covered, owes = mk_customer("Covered by credit"), mk_customer("Still owes")
    for c in (covered, owes):
        _overdue_invoice(client, admin, c)                           # 1,000 each, due 2026-09-01
    assert client.post(f"{API}/adjustments", headers=admin, json={
        "customer_id": covered["id"], "amount": "-1000.00", "reason": "waived by the manager"}).status_code == 201
    assert [i["customer_id"] for i in _preview_fees(client, admin)["items"]] == [owes["id"]]


def test_a_partial_credit_still_leaves_a_late_fee_because_money_is_still_owed(client, admin, mk_customer):
    c = mk_customer()
    _overdue_invoice(client, admin, c)
    client.post(f"{API}/adjustments", headers=admin, json={"customer_id": c["id"], "amount": "-400.00", "reason": "part waived"})
    assert len(_preview_fees(client, admin)["items"]) == 1


# ------------------------------------------------------------------ changing a package
def _packages(client, h):
    s3 = client.post(f"{API}/packages", headers=h, json={"code": "star3", "name": "Star3", "display_name": "Star 3", "internet_price": "1000.00"}).json()
    s6 = client.post(f"{API}/packages", headers=h, json={"code": "star6", "name": "Star6", "display_name": "Star 6", "internet_price": "1500.00"}).json()
    return s3, s6


def _connection(client, h, cust, pkg, due="2026-10-09", price="1000.00"):
    r = client.post(f"{API}/customers/{cust['id']}/connections", headers=h, json={
        "connection_type": "INTERNET", "next_due_date": due,
        "service_lines": [{"service": "INTERNET", "package_id": pkg["id"], "price": price}]})
    assert r.status_code == 201, r.text
    return r.json()


def change(client, h, conn, **body):
    return client.post(f"{API}/connections/{conn['id']}/package", headers=h, json={"service": "INTERNET", "reason": "customer asked", **body})


def next_run(client, h, run_date="2026-11-05"):
    r = client.post(f"{API}/billing/runs", headers=h, json={"run_date": run_date, "confirm": True})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_package_change_applies_to_the_next_bill_and_never_to_existing_ones(client, admin, mk_customer):
    s3, s6 = _packages(client, admin)
    c = mk_customer()
    conn = _connection(client, admin, c, s3)
    assert run(client, admin)["total_billed"] == "1000.00"            # October bill at the old price
    assert change(client, admin, conn, package_id=s6["id"]).status_code == 200
    assert statement(client, admin, c)["balance"] == "1000.00"        # the bill that exists is untouched
    assert next_run(client, admin)["total_billed"] == "1500.00"       # November uses the new package's price
    assert statement(client, admin, c)["balance"] == "2500.00"


def test_a_package_change_can_keep_a_special_price(client, admin, mk_customer):
    s3, s6 = _packages(client, admin)
    c = mk_customer()
    conn = _connection(client, admin, c, s3)
    assert change(client, admin, conn, package_id=s6["id"], price="1200.00").status_code == 200
    assert run(client, admin)["total_billed"] == "1200.00"


def test_a_price_alone_can_be_changed_without_a_package(client, admin, mk_customer):
    s3, _ = _packages(client, admin)
    c = mk_customer()
    conn = _connection(client, admin, c, s3)
    assert change(client, admin, conn, price="850.00").status_code == 200
    assert run(client, admin)["total_billed"] == "850.00"


def test_package_change_refuses_nonsense(client, admin, mk_customer):
    s3, s6 = _packages(client, admin)
    c = mk_customer()
    conn = _connection(client, admin, c, s3)
    assert change(client, admin, conn).status_code == 422                                     # neither package nor price
    assert change(client, admin, conn, package_id=str(uuid.uuid4())).status_code == 422      # unknown package
    assert client.post(f"{API}/connections/{conn['id']}/package", headers=admin,
                       json={"service": "CABLE", "price": "300", "reason": "wrong service"}).status_code == 422
    assert client.post(f"{API}/connections/{conn['id']}/package", headers=admin,
                       json={"service": "INTERNET", "price": "300", "reason": "x"}).status_code == 422      # reason too short
    client.patch(f"{API}/packages/{s6['id']}", headers=admin, json={"status": "INACTIVE"})
    assert change(client, admin, conn, package_id=s6["id"]).status_code == 422                # inactive package
    assert change(client, admin, {"id": str(uuid.uuid4())}, price="1").status_code == 404


def test_only_people_who_may_update_connections_can_change_a_package(client, admin, make_user, mk_customer):
    s3, _ = _packages(client, admin)
    conn = _connection(client, admin, mk_customer(), s3)
    assert change(client, make_user("collector")[1], conn, price="1").status_code == 403
    assert client.post(f"{API}/connections/{conn['id']}/package", json={"service": "INTERNET", "price": "1", "reason": "abc"}).status_code == 401


def test_a_package_change_is_audited(client, admin, db, mk_customer):
    s3, s6 = _packages(client, admin)
    conn = _connection(client, admin, mk_customer(), s3)
    change(client, admin, conn, package_id=s6["id"], reason="upgrade requested by phone")
    log = db.scalar(select(AuditLog).where(AuditLog.action == "connection.package_change"))
    assert log.before["package_id"] == s3["id"] and log.after["package_id"] == s6["id"]
    assert log.after["reason"] == "upgrade requested by phone"
