from __future__ import annotations

import os
import textwrap
import uuid
from pathlib import Path

import pytest

os.environ["BM_ENVIRONMENT"] = "test"
os.environ.setdefault("BM_SECRET_KEY", "test-secret-key-0123456789-abcdefghijklmnop")
os.environ["BM_COOKIE_SECURE"] = "false"
os.environ["BM_POLL_ALLOWED_HOSTS"] = '["status.example.test"]'

from fastapi.testclient import TestClient  # noqa: E402

from botmanager import config as bm_config  # noqa: E402
from botmanager import db as bm_db  # noqa: E402
from botmanager.db import Base  # noqa: E402
from botmanager.main import create_app  # noqa: E402
from botmanager.models import Availability, Bot, Role, User, Worker  # noqa: E402
from botmanager.registry.loader import sync_registry  # noqa: E402
from botmanager.security.passwords import hash_password, hash_token  # noqa: E402

PASSWORD = "correct-horse-battery"
PASSWORD_HASH = hash_password(PASSWORD)  # argon2 é lento de propósito: calcular uma vez

BOTS = {
    "low-bot": """
        key: low-bot
        name: Bot baixo risco
        execution: {adapter: simulated, script: demo, validated: true}
        risk_level: low
        concurrency: {policy: single, exclusive_resources: [desktop]}
        triggers_allowed: [manual, schedule, webhook, after_bot, poll_http]
        retry: {automatic: true, idempotent: true}
        permissions: {view: [viewer, operator, approver], execute: [operator]}
    """,
    "other-bot": """
        key: other-bot
        name: Outro bot no mesmo desktop
        execution: {adapter: simulated, script: demo, validated: true}
        risk_level: low
        concurrency: {policy: single, exclusive_resources: [desktop]}
        triggers_allowed: [manual, after_bot]
        permissions: {view: [viewer, operator, approver], execute: [operator]}
    """,
    "param-bot": """
        key: param-bot
        name: Bot com parâmetros
        execution: {adapter: simulated, script: demo, validated: true}
        risk_level: low
        concurrency: {policy: parallel}
        parameters:
          - {name: data_inicio, type: date, required: true}
          - {name: modo, type: enum, choices: [rapido, completo], default: rapido}
          - {name: token_externo, type: string, sensitive: true}
        permissions: {view: [viewer, operator, approver], execute: [operator]}
    """,
    "high-bot": """
        key: high-bot
        name: Bot risco elevado
        execution: {adapter: simulated, script: demo, validated: true}
        risk_level: high
        requires_approval: true
        triggers_allowed: [manual, after_bot]
        permissions: {view: [viewer, operator, approver], execute: [operator], approve: [approver]}
    """,
    "unvalidated-bot": """
        key: unvalidated-bot
        name: Bot por validar
        execution: {adapter: taskt_cli, script: "OK x.xml", validated: false}
        risk_level: low
    """,
    "secret-bot": """
        key: secret-bot
        name: Bot restrito
        execution: {adapter: simulated, script: demo, validated: true}
        risk_level: low
        permissions: {view: [], execute: []}
    """,
}


def write_registry(directory: Path, bots: dict[str, str] = BOTS) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for key, body in bots.items():
        (directory / f"{key}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    reg = tmp_path / "registry"
    write_registry(reg)
    # BM_TEST_DATABASE_URL permite correr a mesma suite contra PostgreSQL
    url = os.environ.get("BM_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("BM_DATABASE_URL", url)
    monkeypatch.setenv("BM_REGISTRY_DIR", str(reg))
    bm_config.get_settings.cache_clear()
    engine = bm_db.init_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = bm_db.session_factory()()
    sync_registry(db, [reg])
    for bot in db.query(Bot):
        bot.enabled = True  # nos testes os bots começam ativos
    users = {}
    for role in Role:
        u = User(username=role.value, display_name=role.value, role=role, password_hash=PASSWORD_HASH)
        db.add(u)
        users[role.value] = u
    u2 = User(username="operator2", display_name="op2", role=Role.OPERATOR, password_hash=PASSWORD_HASH)
    a2 = User(username="approver2", display_name="ap2", role=Role.APPROVER, password_hash=PASSWORD_HASH)
    db.add_all([u2, a2])
    users["operator2"], users["approver2"] = u2, a2
    worker = Worker(name="w1", token_hash=hash_token("worker-token-1"), capabilities=["simulated", "taskt_cli"])
    worker2 = Worker(name="w2", token_hash=hash_token("worker-token-2"), capabilities=["simulated"])
    db.add_all([worker, worker2])
    db.commit()
    app = create_app(sync_on_start=False)
    yield {"db": db, "app": app, "users": users, "registry": reg, "worker": worker, "worker2": worker2}
    db.close()
    engine.dispose()
    bm_config.get_settings.cache_clear()


def login(app, username: str, password: str = PASSWORD) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-Requested-With"] = "botmanager"
    return c


class _LazyClients(dict):
    """Só faz login (argon2, lento) para os utilizadores efetivamente usados no teste."""

    def __init__(self, app):
        super().__init__()
        self.app = app

    def __missing__(self, name):
        self[name] = login(self.app, name)
        return self[name]


@pytest.fixture()
def clients(env):
    return _LazyClients(env["app"])


def worker_client(app, token: str = "worker-token-1") -> TestClient:
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def run_bot(client: TestClient, key: str, params: dict | None = None, idem: str | None = None):
    return client.post(f"/api/bots/{key}/run",
                       json={"parameters": params or {}, "idempotency_key": idem or uuid.uuid4().hex})
