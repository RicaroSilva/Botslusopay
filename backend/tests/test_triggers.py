import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from botmanager.models import Run, TriggerEvent, TriggerRule
from botmanager.scheduler import acquire_lease, tick
from botmanager.triggers.poll_http import PollHttpTrigger
from botmanager.triggers.webhook import sign
from conftest import worker_client


def _rule(clients, **body):
    r = clients["admin"].post("/api/admin/rules", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _post_hook(env, rule, event_id, body=b'{"ok":true}', secret=None, ts=None):
    from fastapi.testclient import TestClient

    ts = ts or str(int(time.time()))
    sig = sign(secret or rule["webhook_secret"], ts, body)
    return TestClient(env["app"]).post(f"/api/hooks/{rule['id']}", content=body, headers={
        "X-BM-Event-Id": event_id, "X-BM-Timestamp": ts, "X-BM-Signature": sig})


def test_webhook_dedup_and_signature(env, clients):
    rule = _rule(clients, bot_key="low-bot", name="processo externo concluído", trigger_type="webhook", enabled=True)
    assert rule["webhook_secret"] and "webhook_secret" not in clients["admin"].get("/api/admin/rules").json()[0]
    r1 = _post_hook(env, rule, "evt-1")
    assert r1.status_code == 202 and r1.json()["outcome"] == "accepted"
    r2 = _post_hook(env, rule, "evt-1")
    assert r2.status_code == 200 and r2.json()["outcome"] == "duplicate"
    assert _post_hook(env, rule, "evt-2", secret="wrong-secret").status_code == 401
    old = str(int(time.time()) - 3600)
    assert _post_hook(env, rule, "evt-3", ts=old).status_code == 401  # anti-replay
    runs = clients["viewer"].get("/api/runs", params={"bot": "low-bot"}).json()
    assert len(runs) == 1 and runs[0]["trigger_source"] == "webhook"


def test_webhook_disabled_rule_rejected(env, clients):
    rule = _rule(clients, bot_key="low-bot", name="desativada", trigger_type="webhook", enabled=False)
    assert _post_hook(env, rule, "evt-1").status_code == 401


def test_webhook_event_while_bot_busy_is_recorded_not_queued(env, clients):
    rule = _rule(clients, bot_key="low-bot", name="hook", trigger_type="webhook", enabled=True)
    assert _post_hook(env, rule, "a").json()["outcome"] == "accepted"
    r = _post_hook(env, rule, "b")
    assert r.json()["outcome"] == "rejected"
    ev = env["db"].query(TriggerEvent).filter_by(dedup_key="webhook:b").one()
    assert ev.outcome == "rejected" and ev.details["code"] == "conflicting_run"


def test_schedule_fires_once_per_slot(env, clients):
    rule = _rule(clients, bot_key="low-bot", name="todos os dias 06:00", trigger_type="schedule",
                 config={"cron": "0 6 * * *", "timezone": "Europe/Lisbon"}, enabled=True)
    db = env["db"]
    r = db.get(TriggerRule, rule["id"])
    due = r.next_fire_at
    s1 = tick(db, now=due + timedelta(seconds=5))
    s2 = tick(db, now=due + timedelta(seconds=40))  # novo tick / scheduler reiniciado
    assert [f[1] for f in s1["fired"]] == ["accepted"] and s2["fired"] == []
    assert db.query(Run).count() == 1
    # forçar o mesmo instante outra vez (ex.: next_fire_at reposto) é deduplicado
    db.refresh(r)
    r.next_fire_at = due
    db.commit()
    s3 = tick(db, now=due + timedelta(seconds=50))
    assert [f[1] for f in s3["fired"]] == ["duplicate"]


def test_schedule_misfire_skipped(env, clients):
    rule = _rule(clients, bot_key="low-bot", name="agenda", trigger_type="schedule",
                 config={"cron": "0 6 * * *"}, enabled=True)
    db = env["db"]
    due = db.get(TriggerRule, rule["id"]).next_fire_at
    s = tick(db, now=due + timedelta(hours=2))  # scheduler esteve parado
    assert s["fired"] == []
    assert db.query(Run).count() == 0
    audits = clients["admin"].get("/api/admin/audit", params={"action": "trigger.schedule_missed"}).json()
    assert len(audits) == 1


def test_pause_automatic_triggers(env, clients):
    rule = _rule(clients, bot_key="low-bot", name="agenda", trigger_type="schedule",
                 config={"cron": "* * * * *"}, enabled=True)
    clients["admin"].put("/api/admin/settings", json={"key": "pause_automatic_triggers", "value": True})
    db = env["db"]
    due = db.get(TriggerRule, rule["id"]).next_fire_at
    assert tick(db, now=due + timedelta(seconds=1))["fired"] == []


def test_after_bot_chain(env, clients):
    _rule(clients, bot_key="other-bot", name="depois do low-bot", trigger_type="after_bot",
          config={"upstream_bot_key": "low-bot"}, enabled=True)
    from conftest import run_bot

    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    w = worker_client(env["app"])
    w.post("/api/worker/claim", json={})
    w.post(f"/api/worker/runs/{rid}/complete", json={"status": "SUCCEEDED"})
    runs = clients["viewer"].get("/api/runs", params={"bot": "other-bot"}).json()
    assert len(runs) == 1 and runs[0]["trigger_source"] == "after_bot"
    detail = clients["viewer"].get(f"/api/runs/{runs[0]['id']}").json()
    assert detail["parent_run_id"] == rid


def test_after_bot_not_fired_on_failure(env, clients):
    _rule(clients, bot_key="other-bot", name="depois", trigger_type="after_bot",
          config={"upstream_bot_key": "low-bot"}, enabled=True)
    from conftest import run_bot

    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    w = worker_client(env["app"])
    w.post("/api/worker/claim", json={})
    w.post(f"/api/worker/runs/{rid}/complete", json={"status": "FAILED", "failure_reason": "bot_reported_error"})
    assert clients["viewer"].get("/api/runs", params={"bot": "other-bot"}).json() == []


def test_after_bot_with_high_risk_waits_approval(env, clients):
    _rule(clients, bot_key="high-bot", name="depois", trigger_type="after_bot",
          config={"upstream_bot_key": "low-bot"}, enabled=True)
    from conftest import run_bot

    rid = run_bot(clients["operator"], "low-bot").json()["run_id"]
    w = worker_client(env["app"])
    w.post("/api/worker/claim", json={})
    w.post(f"/api/worker/runs/{rid}/complete", json={"status": "SUCCEEDED"})
    runs = clients["viewer"].get("/api/runs", params={"bot": "high-bot"}).json()
    assert runs[0]["status"] == "WAITING_APPROVAL"


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        self.calls.append((url, headers))
        return httpx.Response(200, json=self.payload, request=httpx.Request("GET", url))


def test_poll_http(env, clients, monkeypatch):
    fake = FakeClient({"process": {"status": "done", "batch": "2026-10-27"}})
    monkeypatch.setattr(PollHttpTrigger, "http_client_factory", staticmethod(lambda timeout: fake))
    monkeypatch.setenv("BM_POLL_STATUS_TOKEN", "Bearer abcdefghijklmnop")
    rule = _rule(clients, bot_key="low-bot", name="poll", trigger_type="poll_http", enabled=True,
                 config={"url": "https://status.example.test/api", "interval_seconds": 60,
                         "json_path": "process.status", "equals": "done", "dedup_path": "process.batch",
                         "auth_header_env": "BM_POLL_STATUS_TOKEN"})
    db = env["db"]
    now = datetime.now(timezone.utc)
    s1 = tick(db, now=now + timedelta(seconds=1))
    s2 = tick(db, now=now + timedelta(seconds=120))  # mesmo lote → duplicado
    assert [f[1] for f in s1["fired"]] == ["accepted"]
    assert [f[1] for f in s2["fired"]] == ["duplicate"]
    assert fake.calls[0][1]["Authorization"] == "Bearer abcdefghijklmnop"
    stored = db.get(TriggerRule, rule["id"])
    assert "abcdefghijklmnop" not in json.dumps(stored.config)


def test_poll_http_host_not_allowed(clients):
    r = clients["admin"].post("/api/admin/rules", json={
        "bot_key": "low-bot", "name": "poll", "trigger_type": "poll_http",
        "config": {"url": "https://169.254.169.254/latest", "json_path": "a", "equals": 1, "dedup_path": "b"}})
    assert r.status_code == 422


def test_rule_config_validation(clients):
    r = clients["admin"].post("/api/admin/rules", json={"bot_key": "low-bot", "name": "cron mau",
                                                        "trigger_type": "schedule", "config": {"cron": "todos os dias"}})
    assert r.status_code == 422
    r = clients["admin"].post("/api/admin/rules", json={"bot_key": "low-bot", "name": "tipo",
                                                        "trigger_type": "shell", "config": {}})
    assert r.status_code == 422


def test_high_risk_rule_forced_approval(clients):
    r = clients["admin"].post("/api/admin/rules", json={"bot_key": "high-bot", "name": "depois",
                                                        "trigger_type": "after_bot",
                                                        "config": {"upstream_bot_key": "low-bot"},
                                                        "requires_approval": False})
    assert r.json()["requires_approval"] is True


def test_scheduler_single_lease(env):
    db = env["db"]
    now = datetime.now(timezone.utc)
    assert acquire_lease(db, "a", 60, now)
    assert not acquire_lease(db, "b", 60, now + timedelta(seconds=10))
    assert acquire_lease(db, "b", 60, now + timedelta(seconds=61))
