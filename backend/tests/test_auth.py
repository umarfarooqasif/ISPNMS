API = "/api/v1"
PW = "correct-horse-battery"


def login(client, username, password=PW):
    return client.post(f"{API}/auth/login", json={"username": username, "password": password})


def test_login_and_me(client, make_user):
    make_user("accountant", username="Sara", password=PW)
    r = login(client, "sara")  # case-insensitive username
    assert r.status_code == 200
    tok = r.json()
    assert tok["token_type"] == "bearer" and tok["refresh_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok['access_token']}"}).json()
    assert me["roles"] == ["accountant"] and "payment.void" in me["permissions"]


def test_wrong_password_and_unknown_user(client, make_user):
    make_user("accountant", username="sara", password=PW)
    assert login(client, "sara", "wrong-password-xx").status_code == 401
    assert login(client, "nobody", PW).status_code == 401


def test_lockout_after_repeated_failures(client, make_user):
    make_user("accountant", username="sara", password=PW)
    for _ in range(5):
        assert login(client, "sara", "wrong-password-xx").status_code == 401
    assert login(client, "sara", PW).status_code == 423  # even the right password is refused


def test_login_history_and_audit_written(client, admin, make_user):
    make_user("accountant", username="sara", password=PW)
    login(client, "sara", "bad-password-xxx")
    login(client, "sara")
    acts = [a["action"] for a in client.get(f"{API}/audit-logs", headers=admin).json()]
    assert "auth.login" in acts


def test_refresh_rotation_and_reuse_detection(client, make_user):
    make_user("accountant", username="sara", password=PW)
    t1 = login(client, "sara").json()
    t2 = client.post(f"{API}/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert t2.status_code == 200
    t2 = t2.json()
    assert t2["refresh_token"] != t1["refresh_token"]
    # replaying the already-rotated token = theft signal: it fails AND revokes the whole family
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t1["refresh_token"]}).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh_token(client, make_user):
    make_user("accountant", username="sara", password=PW)
    t = login(client, "sara").json()
    assert client.post(f"{API}/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 204
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_inactive_user_cannot_login(client, admin, make_user):
    uid, _ = make_user("accountant", username="sara", password=PW)
    client.patch(f"{API}/users/{uid}", headers=admin, json={"is_active": False})
    assert login(client, "sara").status_code == 401


def test_password_reset_revokes_sessions(client, admin, make_user):
    uid, _ = make_user("accountant", username="sara", password=PW)
    t = login(client, "sara").json()
    assert client.post(f"{API}/users/{uid}/password", headers=admin, json={"password": "brand-new-password"}).status_code == 204
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert login(client, "sara").status_code == 401
    assert login(client, "sara", "brand-new-password").status_code == 200


def test_password_policy_minimum_length(client, admin):
    r = client.post(f"{API}/users", headers=admin, json={"username": "abc", "password": "short", "full_name": "A"})
    assert r.status_code == 422


def test_health_endpoints(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
