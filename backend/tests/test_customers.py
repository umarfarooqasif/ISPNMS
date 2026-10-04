import pytest

from app.services.customers import normalize_alias, normalize_mobile

API = "/api/v1"


@pytest.mark.parametrize("raw,expected", [
    ("0300-1234567", "+923001234567"),
    ("03001234567", "+923001234567"),
    ("+92 300 1234567", "+923001234567"),
    ("923001234567", "+923001234567"),
    ("00923001234567", "+923001234567"),
    ("3001234567", "+923001234567"),
    ("-", None), ("", None), (None, None), ("12345", None), ("041-2345678", None),
])
def test_normalize_mobile(raw, expected):
    assert normalize_mobile(raw) == expected


def test_alias_normalisation():
    assert normalize_alias("Star 3") == normalize_alias("STAR3") == normalize_alias("star-3") == "star3"


def test_customer_needs_only_a_name(client, admin):
    r = client.post(f"{API}/customers", headers=admin, json={"full_name": "Only Name"})
    assert r.status_code == 201
    c = r.json()
    assert c["customer_code"] == "C-000001" and c["mobile"] is None and c["cnic_masked"] is None
    assert client.post(f"{API}/customers", headers=admin, json={}).status_code == 422
    assert client.post(f"{API}/customers", headers=admin, json={"full_name": ""}).status_code == 422


def test_customer_search(client, admin, mk_customer):
    a = mk_customer("Ahmed Raza", mobile="0300-1112223", house_no="B-12")
    mk_customer("Bilal Shah", mobile="0321 9998887")
    conn = client.post(f"{API}/customers/{a['id']}/connections", headers=admin, json={
        "connection_type": "INTERNET", "internet_id": "NET-777"}).json()
    assert conn["status"] == "ACTIVE"

    def names(**params):
        return [c["full_name"] for c in client.get(f"{API}/customers", headers=admin, params=params).json()]

    assert names(q="ahmed") == ["Ahmed Raza"]
    assert names(q="+92 300 1112223") == ["Ahmed Raza"]
    assert names(q="03219998887") == ["Bilal Shah"]
    assert names(q="NET-777") == ["Ahmed Raza"]
    assert names(internet_id="NET-777") == ["Ahmed Raza"]
    assert names(q="B-12") == ["Ahmed Raza"]
    assert names(q=a["customer_code"]) == ["Ahmed Raza"]
    assert len(names()) == 2


def test_update_is_audited_with_before_and_after(client, admin, mk_customer):
    c = mk_customer("Old Name", mobile="0300-1112223")
    r = client.patch(f"{API}/customers/{c['id']}", headers=admin, json={"full_name": "New Name", "mobile": "0333-5556667"})
    assert r.status_code == 200 and r.json()["mobile_normalized"] == "+923335556667"
    log = client.get(f"{API}/audit-logs", headers=admin, params={"action": "customer.update"}).json()[0]
    assert log["before"]["full_name"] == "Old Name" and log["after"]["full_name"] == "New Name"
    assert client.patch(f"{API}/customers/{c['id']}", headers=admin, json={"full_name": None}).status_code == 422


def test_archive_keeps_record_and_history(client, admin, mk_customer):
    c = mk_customer("Leaving")
    client.post(f"{API}/invoices", headers=admin, json={
        "customer_id": c["id"], "due_date": "2099-01-01", "lines": [{"charge_type": "INTERNET", "amount": "100.00"}]})
    r = client.post(f"{API}/customers/{c['id']}/archive", headers=admin)
    assert r.json()["status"] == "ARCHIVED"
    assert client.get(f"{API}/customers", headers=admin).json() == []  # hidden by default
    archived = client.get(f"{API}/customers", headers=admin, params={"status": "ARCHIVED"}).json()
    assert [x["id"] for x in archived] == [c["id"]]
    st = client.get(f"{API}/customers/{c['id']}/statement", headers=admin).json()
    assert st["balance"] == "100.00"  # billing history survives archival


def test_multiple_connections_and_statuses_preserved(client, admin, mk_customer):
    c = mk_customer("Two Lines")
    base = f"{API}/customers/{c['id']}/connections"
    a = client.post(base, headers=admin, json={"connection_type": "INTERNET", "status": "DISCONNECTED"}).json()
    b = client.post(base, headers=admin, json={
        "connection_type": "COMBINED", "service_lines": [
            {"service": "CABLE", "price": "800.00"}, {"service": "INTERNET", "price": "1500.00"}]}).json()
    assert a["status"] == "DISCONNECTED"  # never silently turned into ACTIVE
    assert a["connection_code"] != b["connection_code"]
    assert {s["service"]: s["price"] for s in b["service_lines"]} == {"CABLE": "800.00", "INTERNET": "1500.00"}
    assert len(client.get(base, headers=admin).json()) == 2


def test_external_ids_are_preserved_and_unique(client, admin, mk_customer):
    c1, c2 = mk_customer("A"), mk_customer("B")
    refs = [{"system": "WASOOLI", "ref_type": "ID", "value": "1001"},
            {"system": "WASOOLI", "ref_type": "INTERNET_ID", "value": "5001"}]
    r = client.post(f"{API}/customers/{c1['id']}/connections", headers=admin,
                    json={"connection_type": "INTERNET", "external_refs": refs})
    assert r.status_code == 201 and len(r.json()["external_refs"]) == 2
    dup = client.post(f"{API}/customers/{c2['id']}/connections", headers=admin,
                      json={"connection_type": "INTERNET", "external_refs": refs[:1]})
    assert dup.status_code == 409


def test_connection_update_audited(client, admin, mk_customer):
    c = mk_customer()
    conn = client.post(f"{API}/customers/{c['id']}/connections", headers=admin, json={"connection_type": "INTERNET"}).json()
    r = client.patch(f"{API}/connections/{conn['id']}", headers=admin, json={"status": "SUSPENDED"})
    assert r.json()["status"] == "SUSPENDED"
    log = client.get(f"{API}/audit-logs", headers=admin, params={"action": "connection.update"}).json()[0]
    assert log["before"]["status"] == "ACTIVE" and log["after"]["status"] == "SUSPENDED"


def test_packages_are_database_driven(client, admin):
    r = client.post(f"{API}/packages", headers=admin, json={
        "code": "STAR3", "name": "Star3", "display_name": "Star 3", "speed_mbps": 3,
        "monthly_price": "1200.00", "aliases": ["star-3"]})
    assert r.status_code == 201
    p = r.json()
    assert p["monthly_price"] == "1200.00" and p["display_name"] == "Star 3"
    # every spelling normalises to the same key, so exactly one alias row is stored
    assert len(p["aliases"]) == 1 and normalize_alias(p["aliases"][0]) == "star3"
    # price changes are data, not code, and are audited
    client.patch(f"{API}/packages/{p['id']}", headers=admin, json={"monthly_price": "1500.00"})
    assert client.get(f"{API}/packages/{p['id']}", headers=admin).json()["monthly_price"] == "1500.00"
    log = client.get(f"{API}/audit-logs", headers=admin, params={"action": "package.update"}).json()[0]
    assert log["before"]["monthly_price"] == "1200.00"


def test_package_alias_collisions_rejected(client, admin):
    client.post(f"{API}/packages", headers=admin, json={"code": "S3", "name": "Star3", "display_name": "Star 3"})
    dup = client.post(f"{API}/packages", headers=admin, json={"code": "S3B", "name": "Star 3", "display_name": "Star-3"})
    assert dup.status_code == 409
    assert client.post(f"{API}/packages", headers=admin, json={"code": "S3", "name": "z", "display_name": "z"}).status_code == 409


def test_packages_with_negative_price_rejected(client, admin):
    r = client.post(f"{API}/packages", headers=admin, json={
        "code": "BAD", "name": "bad", "display_name": "bad", "monthly_price": "-1.00"})
    assert r.status_code == 422


def test_areas_and_streets(client, admin):
    a = client.post(f"{API}/areas", headers=admin, json={"name": "Madina Town", "name_ur": "مدینہ ٹاؤن"}).json()
    assert client.post(f"{API}/areas", headers=admin, json={"name": "madina town"}).status_code == 409
    s = client.post(f"{API}/streets", headers=admin, json={"area_id": a["id"], "name": "Street 5"})
    assert s.status_code == 201
    assert client.post(f"{API}/streets", headers=admin, json={"area_id": a["id"], "name": "Street 5"}).status_code == 409
    assert len(client.get(f"{API}/areas/{a['id']}/streets", headers=admin).json()) == 1
    assert client.get(f"{API}/areas", headers=admin).json()[0]["name_ur"] == "مدینہ ٹاؤن"


def test_urdu_fields_roundtrip(client, admin, mk_customer):
    c = mk_customer("Muhammad Ali", full_name_ur="محمد علی", address_ur="مکان نمبر ۱۲")
    got = client.get(f"{API}/customers/{c['id']}", headers=admin).json()
    assert got["full_name_ur"] == "محمد علی" and got["address_ur"] == "مکان نمبر ۱۲"


def test_import_tracking_tables_exist_and_constrain(db):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    cols = "(id, source_system, file_name, file_size, file_sha256, status)"
    db.execute(text(f"INSERT INTO import_sessions {cols} "
                    "VALUES (gen_random_uuid(), 'WASOOLI', 'x.pdf', 1, 'abc', 'UPLOADED')"))
    db.commit()
    with pytest.raises(DBAPIError):
        db.execute(text(f"INSERT INTO import_sessions {cols} "
                        "VALUES (gen_random_uuid(), 'WASOOLI', 'x.pdf', 1, 'abc', 'BOGUS')"))
        db.commit()
    db.rollback()
