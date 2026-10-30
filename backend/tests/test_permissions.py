from botmanager.models import Bot, User
from conftest import run_bot


def test_viewer_sees_but_cannot_run(clients):
    keys = {b["key"] for b in clients["viewer"].get("/api/bots").json()}
    assert "low-bot" in keys
    r = run_bot(clients["viewer"], "low-bot")
    assert r.status_code == 403


def test_operator_can_run(clients):
    r = run_bot(clients["operator"], "low-bot")
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "QUEUED"


def test_restricted_bot_hidden(clients):
    keys = {b["key"] for b in clients["operator"].get("/api/bots").json()}
    assert "secret-bot" not in keys
    assert clients["operator"].get("/api/bots/secret-bot").status_code == 404
    assert run_bot(clients["operator"], "secret-bot").status_code == 404


def test_explicit_grant(env, clients):
    db = env["db"]
    op = db.query(User).filter_by(username="operator").one()
    r = clients["admin"].post("/api/admin/permissions", json={"user_id": op.id, "bot_key": "secret-bot",
                                                              "permission": "execute"})
    assert r.status_code == 201
    assert clients["operator"].get("/api/bots/secret-bot").status_code == 200  # execute implica view
    assert run_bot(clients["operator"], "secret-bot").status_code == 202
    assert run_bot(clients["operator2"], "secret-bot").status_code == 404


def test_admin_endpoints_require_admin(clients):
    for role in ("viewer", "operator", "approver"):
        assert clients[role].get("/api/admin/users").status_code == 403
        assert clients[role].post("/api/admin/workers", json={"name": "x-worker"}).status_code == 403
    assert clients["admin"].get("/api/admin/users").status_code == 200


def test_operator_cannot_configure_rules(clients):
    r = clients["operator"].post("/api/admin/rules", json={"bot_key": "low-bot", "name": "regra x",
                                                           "trigger_type": "schedule", "config": {"cron": "0 6 * * *"}})
    assert r.status_code == 403


def test_denied_access_is_audited(env, clients):
    run_bot(clients["viewer"], "low-bot")
    audits = clients["admin"].get("/api/admin/audit", params={"action": "bot.execute.denied"}).json()
    assert audits and audits[0]["actor_id"] == "viewer"


def test_admin_cannot_demote_self(env, clients):
    admin = env["db"].query(User).filter_by(username="admin").one()
    r = clients["admin"].patch(f"/api/admin/users/{admin.id}", json={"role": "viewer"})
    assert r.status_code == 409


def test_role_change_ends_sessions(env, clients):
    op = env["db"].query(User).filter_by(username="operator").one()
    session = clients["operator"]
    clients["admin"].patch(f"/api/admin/users/{op.id}", json={"role": "viewer"})
    assert session.get("/api/bots").status_code == 401
