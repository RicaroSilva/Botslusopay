"""Integração worker ↔ backend (backend em processo via TestClient).

Usa o adaptador SIMULADO e o taskt FALSO: prova o comportamento do Bot
Manager, não que os bots reais funcionem."""
from __future__ import annotations

import os
import sys
import textwrap
import threading
import time
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))
os.environ["BM_ENVIRONMENT"] = "test"
os.environ.setdefault("BM_SECRET_KEY", "test-secret-key-0123456789-abcdefghijklmnop")
os.environ["BM_COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from botmanager import config as bm_config  # noqa: E402
from botmanager import db as bm_db  # noqa: E402
from botmanager.db import Base  # noqa: E402
from botmanager.main import create_app  # noqa: E402
from botmanager.models import Bot, Role, Run, User, Worker  # noqa: E402
from botmanager.registry.loader import sync_registry  # noqa: E402
from botmanager.security.passwords import hash_password, hash_token  # noqa: E402
from lusopay_worker import process  # noqa: E402
from lusopay_worker.client import BackendClient  # noqa: E402
from lusopay_worker.runner import Runner  # noqa: E402
from lusopay_worker.state import LocalState  # noqa: E402
from conftest import make_script  # noqa: E402

REG = {
    "sim": "demo", "sim-hang": "demo-hang", "sim-fail": "demo-fail", "sim-exit": "demo-exit",
    "sim-secret": "demo-secret",
}


@pytest.fixture()
def stack(tmp_path, monkeypatch, taskt_env):
    reg = tmp_path / "reg"
    reg.mkdir()
    for key, scen in REG.items():
        (reg / f"{key}.yaml").write_text(textwrap.dedent(f"""
            key: {key}
            name: {key}
            execution: {{adapter: simulated, script: {scen}, validated: true}}
            risk_level: low
            timeout_seconds: 30
            success_detection: {{method: simulated}}
            permissions: {{execute: [operator]}}
        """), encoding="utf-8")
    (reg / "tk.yaml").write_text(textwrap.dedent("""
        key: taskt-bot
        name: taskt falso
        execution: {adapter: taskt_cli, script: "OK bot.xml", validated: true}
        risk_level: low
        permissions: {execute: [operator]}
    """), encoding="utf-8")
    monkeypatch.setenv("BM_DATABASE_URL", f"sqlite:///{tmp_path / 'i.db'}")
    monkeypatch.setenv("BM_REGISTRY_DIR", str(reg))
    bm_config.get_settings.cache_clear()
    engine = bm_db.init_engine()
    Base.metadata.create_all(engine)
    db = bm_db.session_factory()()
    sync_registry(db, [reg])
    for b in db.query(Bot):
        b.enabled = True
    db.add(User(username="operator", role=Role.OPERATOR, password_hash=hash_password("correct-horse-battery")))
    db.add(Worker(name="w", token_hash=hash_token("tok-w"), capabilities=["simulated", "taskt_cli"]))
    db.commit()
    app = create_app(sync_on_start=False)
    user = TestClient(app)
    user.post("/api/auth/login", json={"username": "operator", "password": "correct-horse-battery"})
    user.headers["X-Requested-With"] = "botmanager"
    http = TestClient(app, base_url="http://test")
    http.headers["Authorization"] = "Bearer tok-w"
    client = BackendClient(taskt_env, http=http)
    runner = Runner(taskt_env, client, LocalState(taskt_env.state_file))
    yield {"db": db, "user": user, "client": client, "runner": runner, "cfg": taskt_env}
    db.close()
    engine.dispose()
    bm_config.get_settings.cache_clear()


def start(stack, key):
    r = stack["user"].post(f"/api/bots/{key}/run", json={"parameters": {}, "idempotency_key": uuid.uuid4().hex})
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


def claim_and_run(stack):
    job = stack["client"].claim([], ["simulated", "taskt_cli"])
    assert job
    return job, stack["runner"].execute(job)


def get_run(stack, rid):
    return stack["user"].get(f"/api/runs/{rid}").json()


def test_success_end_to_end(stack):
    rid = start(stack, "sim")
    claim_and_run(stack)
    run = get_run(stack, rid)
    assert run["status"] == "SUCCEEDED" and run["result_summary"]["simulated"] is True
    logs = stack["user"].get(f"/api/runs/{rid}/logs").json()["lines"]
    assert any("passo 3/3" in l["message"] for l in logs)
    assert [l["seq"] for l in logs] == sorted(l["seq"] for l in logs)


def test_process_reports_error_and_bad_exit_code(stack):
    rid = start(stack, "sim-fail")
    claim_and_run(stack)
    assert get_run(stack, rid)["failure_reason"] == "bot_reported_error"
    rid = start(stack, "sim-exit")
    claim_and_run(stack)
    run = get_run(stack, rid)
    assert run["failure_reason"] == "exit_code" and run["exit_code"] == 3


def test_timeout_kills_process(stack):
    rid = start(stack, "sim-hang")
    run_row = stack["db"].get(Run, rid)
    run_row.timeout_seconds = 1
    stack["db"].commit()
    t0 = time.monotonic()
    job, payload = claim_and_run(stack)
    assert time.monotonic() - t0 < 15
    run = get_run(stack, rid)
    assert run["status"] == "FAILED" and run["failure_reason"] == "timeout" and run["needs_review"] is True


def test_cancel_running(stack):
    rid = start(stack, "sim-hang")
    job = stack["client"].claim([], ["simulated"])
    th = threading.Thread(target=stack["runner"].execute, args=(job,))
    th.start()
    time.sleep(0.8)
    assert stack["user"].post(f"/api/runs/{rid}/cancel").json()["cancel_requested"] is True
    th.join(timeout=15)
    assert get_run(stack, rid)["status"] == "CANCELLED"


def test_secret_redacted_in_logs(stack):
    rid = start(stack, "sim-secret")
    claim_and_run(stack)
    text = str(stack["user"].get(f"/api/runs/{rid}/logs").json())
    assert "ZXhlbXBsbzpzZWdyZWRv" not in text and "REDACTED" in text


def test_worker_restart_recovers(stack):
    rid = start(stack, "sim-hang")
    job = stack["client"].claim([], ["simulated"])
    # simula um worker que morreu a meio: processo órfão e estado local gravado
    orphan = process.start([sys.executable, "-c", "import time; time.sleep(600)"], None)
    LocalState(stack["cfg"].state_file).save({"run_id": rid, "pid": orphan.pid})
    stack["runner"].recover()
    orphan.wait(timeout=10)
    assert orphan.returncode is not None
    assert stack["client"].claim([], ["simulated"]) is None  # backend marca a execução como perdida
    run = get_run(stack, rid)
    assert run["status"] == "FAILED" and run["failure_reason"] == "worker_lost" and run["needs_review"]


def test_pending_completion_resent_after_restart(stack):
    rid = start(stack, "sim")
    stack["client"].claim([], ["simulated"])
    payload = {"status": "SUCCEEDED", "process_started": True, "result_summary": {}}
    LocalState(stack["cfg"].state_file).save({"run_id": rid, "pid": None,
                                              "pending_completion": {"run_id": rid, "payload": payload}})
    stack["runner"].recover()
    assert get_run(stack, rid)["status"] == "SUCCEEDED"


def test_adapter_not_enabled_on_worker(stack):
    rid = start(stack, "sim")
    stack["cfg"].adapters = ["taskt_cli"]
    job = stack["client"].claim([], ["simulated", "taskt_cli"])
    stack["runner"].execute(job)
    run = get_run(stack, rid)
    assert run["failure_reason"] == "worker_rejected"


def test_fake_taskt_end_to_end(stack):
    make_script(stack["cfg"], "OK bot.xml", "error")
    rid = start(stack, "taskt-bot")
    claim_and_run(stack)
    run = get_run(stack, rid)
    assert run["status"] == "FAILED" and run["failure_reason"] == "bot_reported_error"
    assert run["result_summary"]["runtime_result"] == "Error"
    logs = stack["user"].get(f"/api/runs/{rid}/logs").json()["lines"]
    assert any(l["source"] == "runtime" and "Script Path" in l["message"] for l in logs)


def test_redaction_parity_with_backend():
    from botmanager.security import redaction as b
    from lusopay_worker import redaction as w

    assert [p.pattern for p, _ in b._PATTERNS] == [p.pattern for p, _ in w._PATTERNS]


def test_flow_filters_parity_with_backend_validation():
    from botmanager.flows import schema
    from lusopay_worker.flowengine import make_env

    env = make_env()
    base = __import__("jinja2.sandbox", fromlist=["SandboxedEnvironment"]).SandboxedEnvironment()
    assert set(env.filters) == set(base.filters) | set(schema.ENGINE_FILTERS)
    assert set(env.tests) == set(base.tests) | set(schema.ENGINE_TESTS)
    assert set(env.globals) == set(base.globals) | set(schema.ENGINE_GLOBALS)
