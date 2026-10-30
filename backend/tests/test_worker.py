from datetime import timedelta

from botmanager.models import Run, utcnow
from botmanager.services.runs import reap_stale_runs
from botmanager.states import RunStatus
from conftest import run_bot, worker_client


def _claim(app, token="worker-token-1", active=None):
    return worker_client(app, token).post("/api/worker/claim", json={"active_run_ids": active or []})


def test_invalid_worker_token(env):
    assert _claim(env["app"], "nope").status_code == 401


def test_full_lifecycle_with_logs(env, clients):
    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    w = worker_client(env["app"])
    job = w.post("/api/worker/claim", json={}).json()
    assert job["run_id"] == rid and job["adapter"] == "simulated"
    assert clients["viewer"].get(f"/api/runs/{rid}").json()["status"] == "RUNNING"
    logs = [{"seq": 1, "message": "a iniciar"},
            {"seq": 2, "message": "Authorization: Basic ZXhlbXBsbzpzZWdyZWRv"}]
    assert w.post(f"/api/worker/runs/{rid}/logs", json={"entries": logs}).json()["added"] == 2
    # reenvio do mesmo lote (rede instável) não duplica
    assert w.post(f"/api/worker/runs/{rid}/logs", json={"entries": logs}).json()["added"] == 0
    r = w.post(f"/api/worker/runs/{rid}/complete", json={"status": "SUCCEEDED", "exit_code": 0,
                                                          "result_summary": {"runtime_result": "Successful"}})
    assert r.json()["status"] == "SUCCEEDED"
    out = clients["viewer"].get(f"/api/runs/{rid}/logs").json()
    assert [l["seq"] for l in out["lines"]] == [1, 2]
    assert "ZXhlbXBsbzpzZWdyZWRv" not in out["lines"][1]["message"]
    # conclusão repetida é idempotente
    again = w.post(f"/api/worker/runs/{rid}/complete", json={"status": "FAILED", "failure_reason": "exit_code"})
    assert again.json() == {"status": "SUCCEEDED", "already_final": True}


def test_worker_cannot_touch_other_workers_runs(env, clients):
    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    _claim(env["app"])
    w2 = worker_client(env["app"], "worker-token-2")
    assert w2.post(f"/api/worker/runs/{rid}/complete", json={"status": "SUCCEEDED"}).status_code == 404


def test_exclusive_resource_blocks_parallel_claim(env, clients):
    a = run_bot(clients["operator"], "low-bot").json()["run_id"]
    b = run_bot(clients["operator"], "other-bot").json()["run_id"]
    j1 = _claim(env["app"]).json()
    assert j1["run_id"] == a
    # w2 não pode pegar other-bot: o recurso 'desktop' está ocupado
    assert _claim(env["app"], "worker-token-2").status_code == 204
    worker_client(env["app"]).post(f"/api/worker/runs/{a}/complete", json={"status": "SUCCEEDED"})
    j2 = _claim(env["app"], "worker-token-2").json()
    assert j2["run_id"] == b


def test_worker_restart_marks_lost_runs(env, clients):
    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    _claim(env["app"])
    # o worker reinicia e já não reporta a execução em curso
    r = _claim(env["app"], active=[])
    run = clients["viewer"].get(f"/api/runs/{rid}").json()
    assert run["status"] == "FAILED" and run["failure_reason"] == "worker_lost" and run["needs_review"] is True
    # bot libertado (não há repetição automática)
    assert r.status_code == 204
    assert len(clients["viewer"].get("/api/runs", params={"bot": "low-bot"}).json()) == 1


def test_retry_after_lost_requires_confirmation(env, clients):
    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    _claim(env["app"])
    _claim(env["app"], active=[])
    r = clients["operator"].post(f"/api/runs/{rid}/retry", json={})
    assert r.status_code == 400 and r.json()["details"]["requires_confirmation"] is True
    r2 = clients["operator"].post(f"/api/runs/{rid}/retry", json={"confirm_side_effects_checked": True})
    assert r2.status_code == 202


def test_heartbeat_returns_cancel(env, clients):
    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    _claim(env["app"])
    w = worker_client(env["app"])
    assert w.post(f"/api/worker/runs/{rid}/heartbeat").json()["cancel_requested"] is False
    clients["operator"].post(f"/api/runs/{rid}/cancel")
    assert w.post(f"/api/worker/runs/{rid}/heartbeat").json()["cancel_requested"] is True
    w.post(f"/api/worker/runs/{rid}/complete", json={"status": "CANCELLED"})
    assert clients["viewer"].get(f"/api/runs/{rid}").json()["status"] == "CANCELLED"


def test_reaper_stale_heartbeat(env, clients):
    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    _claim(env["app"])
    db = env["db"]
    db.expire_all()
    reaped = reap_stale_runs(db, now=utcnow() + timedelta(minutes=10))
    db.commit()
    assert reaped == [rid]
    run = db.get(Run, rid)
    assert run.status == RunStatus.FAILED and run.needs_review


def test_timeout_reported_by_worker_needs_review(env, clients):
    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    _claim(env["app"])
    worker_client(env["app"]).post(f"/api/worker/runs/{rid}/complete",
                                   json={"status": "FAILED", "failure_reason": "timeout", "process_started": True})
    run = clients["viewer"].get(f"/api/runs/{rid}").json()
    assert run["failure_reason"] == "timeout" and run["needs_review"] is True


def test_process_failure(env, clients):
    rid = run_bot(clients["operator"], "other-bot").json()["run_id"]
    _claim(env["app"])
    worker_client(env["app"]).post(f"/api/worker/runs/{rid}/complete",
                                   json={"status": "FAILED", "failure_reason": "bot_reported_error", "exit_code": 0})
    run = clients["viewer"].get(f"/api/runs/{rid}").json()
    assert run["status"] == "FAILED" and run["needs_review"] is False


def test_auto_retry_only_when_not_started(env, clients):
    # low-bot: retry.automatic + idempotent
    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    _claim(env["app"])
    r = worker_client(env["app"]).post(f"/api/worker/runs/{rid}/complete",
                                       json={"status": "FAILED", "failure_reason": "launch_error",
                                             "process_started": False})
    retry_id = r.json()["auto_retry_run_id"]
    assert retry_id
    # a repetição não volta a repetir-se
    _claim(env["app"])
    r2 = worker_client(env["app"]).post(f"/api/worker/runs/{retry_id}/complete",
                                        json={"status": "FAILED", "failure_reason": "launch_error",
                                              "process_started": False})
    assert r2.json()["auto_retry_run_id"] is None


def test_no_auto_retry_after_process_started(env, clients):
    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    _claim(env["app"])
    r = worker_client(env["app"]).post(f"/api/worker/runs/{rid}/complete",
                                       json={"status": "FAILED", "failure_reason": "bot_reported_error",
                                             "process_started": True})
    assert r.json()["auto_retry_run_id"] is None


def test_worker_capabilities_respected(env, clients):
    # w2 só tem 'simulated'; um bot taskt nunca lhe é atribuído
    from botmanager.models import Availability, Bot

    db = env["db"]
    b = db.query(Bot).filter_by(key="unvalidated-bot").one()
    b.availability = Availability.AVAILABLE
    db.commit()
    run_bot(clients["operator"], "unvalidated-bot")
    assert _claim(env["app"], "worker-token-2").status_code == 204
    assert _claim(env["app"]).json()["adapter"] == "taskt_cli"
