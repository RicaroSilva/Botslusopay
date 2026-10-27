from botmanager.models import Run
from botmanager.states import RunStatus
from conftest import run_bot


def test_duplicate_click_is_idempotent(clients):
    r1 = run_bot(clients["operator"], "low-bot", idem="click-0001")
    r2 = run_bot(clients["operator"], "low-bot", idem="click-0001")
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["run_id"] == r2.json()["run_id"]
    assert r2.json()["deduplicated"] is True


def test_second_active_run_rejected(clients):
    assert run_bot(clients["operator"], "low-bot").status_code == 202
    r = run_bot(clients["operator2"], "low-bot")
    assert r.status_code == 409 and r.json()["code"] == "conflicting_run"


def test_parallel_policy_allows_multiple(clients):
    p = {"data_inicio": "2026-01-01"}
    assert run_bot(clients["operator"], "param-bot", p).status_code == 202
    assert run_bot(clients["operator"], "param-bot", p).status_code == 202


def test_parameters_validated_and_sensitive_not_stored(env, clients):
    r = run_bot(clients["operator"], "param-bot", {"data_inicio": "2026-01-01", "token_externo": "s3cr3t-value"})
    assert r.status_code == 202
    run = env["db"].get(Run, r.json()["run_id"])
    env["db"].refresh(run)
    assert run.parameters == {"data_inicio": "2026-01-01", "modo": "rapido"}
    bad = run_bot(clients["operator"], "param-bot", {"data_inicio": "ontem"})
    assert bad.status_code == 422
    extra = run_bot(clients["operator"], "param-bot", {"data_inicio": "2026-01-01", "cmd": "calc.exe"})
    assert extra.status_code == 422


def test_unknown_trigger_source_not_allowed(clients):
    # param-bot só permite 'manual': criar regra de agendamento falha
    r = clients["admin"].post("/api/admin/rules", json={"bot_key": "param-bot", "name": "agenda",
                                                        "trigger_type": "schedule", "config": {"cron": "0 6 * * *"}})
    assert r.status_code == 422


def test_approval_flow_four_eyes(clients):
    r = run_bot(clients["operator"], "high-bot")
    assert r.json()["status"] == "WAITING_APPROVAL"
    rid = r.json()["run_id"]
    # operador não tem permissão de aprovar
    assert clients["operator"].post(f"/api/runs/{rid}/approval", json={"approve": True}).status_code == 403
    ok = clients["approver"].post(f"/api/runs/{rid}/approval", json={"approve": True, "comment": "ok"})
    assert ok.status_code == 200 and ok.json()["status"] == "QUEUED"
    detail = clients["operator"].get(f"/api/runs/{rid}").json()
    assert detail["approved_by_name"] == "approver"


def test_self_approval_forbidden(env, clients):
    from botmanager.models import BotPermission, Bot, Permission, User

    db = env["db"]
    appr = db.query(User).filter_by(username="approver").one()
    bot = db.query(Bot).filter_by(key="high-bot").one()
    db.add(BotPermission(bot_id=bot.id, user_id=appr.id, permission=Permission.EXECUTE))
    db.commit()
    rid = run_bot(clients["approver"], "high-bot").json()["run_id"]
    r = clients["approver"].post(f"/api/runs/{rid}/approval", json={"approve": True})
    assert r.status_code == 403 and r.json()["code"] == "approval_error"
    assert clients["approver2"].post(f"/api/runs/{rid}/approval", json={"approve": True}).status_code == 200


def test_rejection_cancels(clients):
    rid = run_bot(clients["operator"], "high-bot").json()["run_id"]
    r = clients["approver"].post(f"/api/runs/{rid}/approval", json={"approve": False, "comment": "não hoje"})
    assert r.json()["status"] == "CANCELLED"
    # depois de cancelada, o bot fica livre
    assert run_bot(clients["operator"], "high-bot").status_code == 202


def test_cancel_queued(clients):
    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    r = clients["operator"].post(f"/api/runs/{rid}/cancel")
    assert r.json()["status"] == "CANCELLED"
    assert clients["operator"].post(f"/api/runs/{rid}/cancel").status_code == 409


def test_dependencies(env, clients):
    r = clients["admin"].post("/api/admin/dependencies", json={"bot_key": "other-bot", "depends_on": "low-bot",
                                                               "condition": "succeeded_within", "within_hours": 24})
    assert r.status_code == 201
    blocked = run_bot(clients["operator"], "other-bot")
    assert blocked.status_code == 409 and blocked.json()["code"] == "dependency_unmet"
    # ciclo recusado
    cyc = clients["admin"].post("/api/admin/dependencies", json={"bot_key": "low-bot", "depends_on": "other-bot"})
    assert cyc.status_code == 422
    # conclui low-bot com sucesso via worker → dependência satisfeita
    from conftest import worker_client

    run_bot(clients["operator"], "low-bot")
    w = worker_client(env["app"])
    job = w.post("/api/worker/claim", json={}).json()
    w.post(f"/api/worker/runs/{job['run_id']}/complete", json={"status": "SUCCEEDED", "exit_code": 0})
    assert run_bot(clients["operator"], "other-bot").status_code == 202


def test_run_filters(clients):
    run_bot(clients["operator"], "low-bot")
    run_bot(clients["operator2"], "param-bot", {"data_inicio": "2026-01-01"})
    by_bot = clients["viewer"].get("/api/runs", params={"bot": "param-bot"}).json()
    assert {r["bot_key"] for r in by_bot} == {"param-bot"}
    by_user = clients["viewer"].get("/api/runs", params={"requested_by": "operator"}).json()
    assert len(by_user) == 1 and by_user[0]["bot_key"] == "low-bot"
    by_status = clients["viewer"].get("/api/runs", params={"status": "QUEUED"}).json()
    assert len(by_status) == 2
    assert clients["viewer"].get("/api/runs", params={"status": "BOGUS"}).status_code == 422


def test_dashboard(clients):
    run_bot(clients["operator"], "low-bot")
    d = clients["viewer"].get("/api/dashboard").json()
    assert d["queued"] == 1 and d["bots_total"] >= 4
