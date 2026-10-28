from fastapi.testclient import TestClient

from botmanager.models import User
from conftest import PASSWORD, login


def test_login_and_me(env):
    c = login(env["app"], "viewer")
    r = c.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["role"] == "viewer"
    assert "password_hash" not in r.json()


def test_cookie_is_httponly_strict(env):
    c = TestClient(env["app"])
    r = c.post("/api/auth/login", json={"username": "viewer", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_bad_password_and_unknown_user_same_error(env):
    c = TestClient(env["app"])
    r1 = c.post("/api/auth/login", json={"username": "viewer", "password": "wrong-password-1"})
    r2 = c.post("/api/auth/login", json={"username": "ghost", "password": "wrong-password-1"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()


def test_lockout_after_failures(env):
    c = TestClient(env["app"])
    for _ in range(5):
        c.post("/api/auth/login", json={"username": "operator", "password": "nope-nope-nope"})
    r = c.post("/api/auth/login", json={"username": "operator", "password": PASSWORD})
    assert r.status_code == 429


def test_requires_authentication(env):
    c = TestClient(env["app"])
    for path in ("/api/bots", "/api/runs", "/api/dashboard", "/api/admin/users"):
        assert c.get(path).status_code == 401


def test_csrf_header_required_for_mutations(env):
    c = login(env["app"], "operator")
    del c.headers["X-Requested-With"]
    r = c.post("/api/bots/low-bot/run", json={"parameters": {}, "idempotency_key": "abcdefgh1"})
    assert r.status_code == 403


def test_logout_invalidates_session(env):
    c = login(env["app"], "viewer")
    stolen = dict(c.cookies)
    assert c.post("/api/auth/logout").status_code == 200
    c2 = TestClient(env["app"], cookies=stolen)
    assert c2.get("/api/auth/me").status_code == 401


def test_deactivated_user_loses_access(env, clients):
    db = env["db"]
    viewer = db.query(User).filter_by(username="viewer").one()
    session = clients["viewer"]  # sessão aberta antes da desativação
    r = clients["admin"].patch(f"/api/admin/users/{viewer.id}", json={"is_active": False})
    assert r.status_code == 200
    assert session.get("/api/bots").status_code == 401


def test_tampered_token_rejected(env):
    c = TestClient(env["app"], cookies={"bm_session": "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0."})
    assert c.get("/api/auth/me").status_code == 401


def test_cli_reset_password_unlocks(env, monkeypatch):
    from datetime import timedelta

    from botmanager import cli
    from botmanager.models import User, utcnow

    db = env["db"]
    u = db.query(User).filter_by(username="admin").one()
    u.locked_until, u.failed_logins = utcnow() + timedelta(minutes=15), 3
    db.commit()
    answers = iter(["nova-password-segura-1", "nova-password-segura-1"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    assert cli.main(["reset-password", "--username", "Admin"]) == 0
    db.expire_all()
    u = db.query(User).filter_by(username="admin").one()
    assert u.locked_until is None and u.failed_logins == 0
    from fastapi.testclient import TestClient

    c = TestClient(env["app"])
    assert c.post("/api/auth/login", json={"username": "admin", "password": "nova-password-segura-1"}).status_code == 200
