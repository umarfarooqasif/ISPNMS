import uuid
from datetime import date, timedelta

API = "/api/v1"
FUTURE = (date.today() + timedelta(days=30)).isoformat()


def setup_collector(client, admin, make_user, customers=(), areas=(), code="C01"):
    uid, headers = make_user("collector")
    col = client.post(f"{API}/collectors", headers=admin, json={"user_id": str(uid), "code": code}).json()
    if customers:
        client.put(f"{API}/collectors/{col['id']}/customers", headers=admin,
                   json={"customers": [{"customer_id": c["id"], "sort_order": i} for i, c in enumerate(customers)]})
    if areas:
        client.put(f"{API}/collectors/{col['id']}/areas", headers=admin, json={"area_ids": [a["id"] for a in areas]})
    return col, headers


def test_unauthenticated_requests_rejected(client):
    for path in ("/customers", "/packages", "/users", "/payments", "/audit-logs", "/auth/me"):
        assert client.get(f"{API}{path}").status_code == 401
    assert client.get(f"{API}/customers", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_collector_cannot_do_privileged_things(client, admin, make_user, mk_customer):
    c = mk_customer()
    col, ch = setup_collector(client, admin, make_user, customers=[c])
    assert client.post(f"{API}/customers", headers=ch, json={"full_name": "X"}).status_code == 403
    assert client.patch(f"{API}/customers/{c['id']}", headers=ch, json={"full_name": "Y"}).status_code == 403
    assert client.post(f"{API}/customers/{c['id']}/archive", headers=ch).status_code == 403
    assert client.get(f"{API}/customers/{c['id']}/cnic", headers=ch).status_code == 403
    assert client.post(f"{API}/packages", headers=ch, json={"code": "x", "name": "x", "display_name": "x"}).status_code == 403
    assert client.get(f"{API}/users", headers=ch).status_code == 403
    assert client.get(f"{API}/audit-logs", headers=ch).status_code == 403
    assert client.post(f"{API}/invoices", headers=ch, json={
        "customer_id": c["id"], "due_date": FUTURE, "lines": [{"charge_type": "INTERNET", "amount": "1.00"}]}).status_code == 403
    assert client.post(f"{API}/adjustments", headers=ch, json={
        "customer_id": c["id"], "amount": "5.00", "reason": "sneaky"}).status_code == 403
    assert client.post(f"{API}/refunds", headers=ch, json={
        "customer_id": c["id"], "amount": "5.00", "reason": "sneaky"}).status_code == 403


def test_collector_cannot_void_payments(client, admin, make_user, mk_customer):
    c = mk_customer()
    col, ch = setup_collector(client, admin, make_user, customers=[c])
    p = client.post(f"{API}/payments", headers=ch, json={"customer_id": c["id"], "amount": "100.00", "method": "CASH"}).json()
    assert client.post(f"{API}/payments/{p['id']}/void", headers=ch, json={"reason": "undo it"}).status_code == 403


def test_collector_sees_only_assigned_customers(client, admin, make_user, mk_customer):
    mine, other = mk_customer("Mine"), mk_customer("Other")
    col, ch = setup_collector(client, admin, make_user, customers=[mine])
    assert client.get(f"{API}/customers/{mine['id']}", headers=ch).status_code == 200
    assert client.get(f"{API}/customers/{other['id']}", headers=ch).status_code == 404  # no existence leak
    names = [c["full_name"] for c in client.get(f"{API}/customers", headers=ch).json()]
    assert names == ["Mine"]
    assert client.get(f"{API}/customers/{other['id']}/statement", headers=ch).status_code == 404


def test_collector_area_assignment_grants_access(client, admin, make_user, mk_customer):
    area = client.post(f"{API}/areas", headers=admin, json={"name": "Block A"}).json()
    in_area = mk_customer("InArea", area_id=area["id"])
    outside = mk_customer("Outside")
    col, ch = setup_collector(client, admin, make_user, areas=[area])
    names = {c["full_name"] for c in client.get(f"{API}/customers", headers=ch).json()}
    assert names == {"InArea"}
    assert client.get(f"{API}/customers/{outside['id']}", headers=ch).status_code == 404
    assert client.get(f"{API}/customers/{in_area['id']}", headers=ch).status_code == 200


def test_collector_cannot_collect_for_unassigned_customer(client, admin, make_user, mk_customer):
    mine, other = mk_customer("Mine"), mk_customer("Other")
    col, ch = setup_collector(client, admin, make_user, customers=[mine])
    r = client.post(f"{API}/payments", headers=ch, json={"customer_id": other["id"], "amount": "10.00", "method": "CASH"})
    assert r.status_code == 404
    ok = client.post(f"{API}/payments", headers=ch, json={"customer_id": mine["id"], "amount": "10.00", "method": "CASH"})
    assert ok.status_code == 201 and ok.json()["collector_id"] == col["id"]


def test_collector_sees_only_own_payments_and_receipts(client, admin, make_user, mk_customer):
    c = mk_customer()
    col1, h1 = setup_collector(client, admin, make_user, customers=[c], code="C01")
    col2, h2 = setup_collector(client, admin, make_user, customers=[c], code="C02")
    p1 = client.post(f"{API}/payments", headers=h1, json={"customer_id": c["id"], "amount": "10.00", "method": "CASH"}).json()
    p2 = client.post(f"{API}/payments", headers=h2, json={"customer_id": c["id"], "amount": "20.00", "method": "CASH"}).json()
    assert [p["id"] for p in client.get(f"{API}/payments", headers=h1).json()] == [p1["id"]]
    assert client.get(f"{API}/payments/{p2['id']}", headers=h1).status_code == 404
    assert client.get(f"{API}/receipts/{p2['receipt_number']}", headers=h1).status_code == 404
    assert client.get(f"{API}/receipts/{p1['receipt_number']}", headers=h1).status_code == 200
    assert len(client.get(f"{API}/payments", headers=admin).json()) == 2


def test_inactive_collector_cannot_collect(client, admin, make_user, mk_customer, db):
    from sqlalchemy import text
    c = mk_customer()
    col, ch = setup_collector(client, admin, make_user, customers=[c])
    db.execute(text("UPDATE collectors SET status='INACTIVE'"))
    db.commit()
    r = client.post(f"{API}/payments", headers=ch, json={"customer_id": c["id"], "amount": "10.00", "method": "CASH"})
    assert r.status_code in (403, 404)
    assert client.get(f"{API}/customers", headers=ch).json() == []


def test_accountant_can_void_but_not_manage_users(client, accountant, admin, mk_customer):
    c = mk_customer()
    p = client.post(f"{API}/payments", headers=accountant, json={"customer_id": c["id"], "amount": "10.00", "method": "CASH"}).json()
    assert client.post(f"{API}/payments/{p['id']}/void", headers=accountant, json={"reason": "wrong amount"}).status_code == 200
    assert client.get(f"{API}/users", headers=accountant).status_code == 403


def test_sales_can_create_customers_but_not_take_payments(client, make_user):
    _, sh = make_user("sales")
    r = client.post(f"{API}/customers", headers=sh, json={"full_name": "New Lead"})
    assert r.status_code == 201
    assert client.post(f"{API}/payments", headers=sh, json={"customer_id": r.json()["id"], "amount": "1.00", "method": "CASH"}).status_code == 403


def test_cnic_masked_by_default_and_reveal_is_audited(client, admin, mk_customer):
    c = mk_customer(cnic="35202-1234567-1")
    assert c["cnic_masked"].endswith("5671") and "3520" not in c["cnic_masked"]
    assert "cnic" not in c
    got = client.get(f"{API}/customers/{c['id']}", headers=admin).json()
    assert "cnic" not in got
    r = client.get(f"{API}/customers/{c['id']}/cnic", headers=admin)
    assert r.json()["cnic"] == "35202-1234567-1"
    logs = client.get(f"{API}/audit-logs", headers=admin, params={"action": "customer.cnic.view"}).json()
    assert len(logs) == 1


def test_cnic_encrypted_at_rest_and_not_in_audit(client, admin, mk_customer, db):
    from sqlalchemy import text
    c = mk_customer(cnic="35202-1234567-1")
    raw = db.execute(text("SELECT cnic FROM customers")).scalar()
    assert "35202" not in raw and "1234567" not in raw
    audit_dump = str(client.get(f"{API}/audit-logs", headers=admin).json())
    assert "35202-1234567-1" not in audit_dump
    client.patch(f"{API}/customers/{c['id']}", headers=admin, json={"cnic": "11111-1111111-1"})
    assert "11111-1111111-1" not in str(client.get(f"{API}/audit-logs", headers=admin).json())


def test_admin_cannot_grant_super_admin_or_touch_super_admin(client, make_user):
    _, ah = make_user("admin")
    r = client.post(f"{API}/users", headers=ah, json={
        "username": "sneaky", "password": "long-enough-password", "full_name": "S", "role_codes": ["super_admin"]})
    assert r.status_code == 403
    ok = client.post(f"{API}/users", headers=ah, json={
        "username": "clerk", "password": "long-enough-password", "full_name": "C", "role_codes": ["collector"]})
    assert ok.status_code == 201
    root_id, _ = make_user("super_admin", username="boss")
    assert client.patch(f"{API}/users/{root_id}", headers=ah, json={"is_active": False}).status_code == 403
    assert client.post(f"{API}/users/{root_id}/password", headers=ah, json={"password": "another-long-pass"}).status_code == 403


def test_cannot_deactivate_self(client, make_user):
    uid, h = make_user("super_admin", username="solo")
    assert client.patch(f"{API}/users/{uid}", headers=h, json={"is_active": False}).status_code == 409


def test_deactivated_user_token_stops_working(client, admin, make_user):
    uid, uh = make_user("collector")
    assert client.get(f"{API}/auth/me", headers=uh).status_code == 200
    assert client.patch(f"{API}/users/{uid}", headers=admin, json={"is_active": False}).status_code == 200
    assert client.get(f"{API}/auth/me", headers=uh).status_code == 401
