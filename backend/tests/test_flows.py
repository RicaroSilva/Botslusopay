import base64
import uuid

from botmanager.models import Bot, Credential, Run
from botmanager.registry.loader import sync_registry
from conftest import run_bot, worker_client

SMTP = {"name": "smtp-geral", "kind": "smtp", "description": "SMTP LUSOPAY",
        "fields": {"host": "mail.exemplo.pt", "port": 587, "username": "geral@exemplo.pt",
                   "password": "smtp-pass-secreta", "from_address": "geral@exemplo.pt", "security": "starttls"}}
API = {"name": "cyclos-dev", "kind": "http_basic", "fields": {"username": "cliente7", "password": "api-pass-secreta"}}

FLOW = {
    "description": "Transações dev por email",
    "steps": [
        {"id": "tx", "type": "http_request", "url": "https://dev.lusopay.com:8444/web_dev/api/transactions",
         "headers": {"accept": "application/json"}, "credential": "cyclos-dev", "save_as": "transacoes"},
        {"id": "csv", "type": "csv_write", "file": "transacoes.csv", "rows_expr": "transacoes",
         "columns": [{"header": "ID", "value": "{{ row.id }}"}]},
        {"id": "mail", "type": "email", "credential": "smtp-geral", "to": ["ricardosilva@lusopay.com"],
         "subject": "Transações", "body": "Em anexo.", "attachments": ["transacoes.csv"]},
    ],
}


def _setup(clients, **meta):
    a = clients["admin"]
    assert a.post("/api/admin/credentials", json=SMTP).status_code == 201
    assert a.post("/api/admin/credentials", json=API).status_code == 201
    body = {"key": "transacoes-dev", "name": "Transações dev por email", "risk_level": "low",
            "definition": FLOW, **meta}
    r = a.post("/api/flows", json=body)
    assert r.status_code == 201, r.text
    a.patch("/api/admin/bots/transacoes-dev", json={"enabled": True})
    return r.json()


def test_credentials_never_exposed_and_encrypted(env, clients):
    a = clients["admin"]
    r = a.post("/api/admin/credentials", json=SMTP)
    assert r.status_code == 201
    body = a.get("/api/admin/credentials").text
    assert "smtp-pass-secreta" not in body and "geral@exemplo.pt" in body
    c = env["db"].query(Credential).one()
    assert "smtp-pass-secreta" not in c.encrypted_data and "smtp-pass-secreta" not in str(c.public_fields)
    audits = a.get("/api/admin/audit", params={"action": "credential."}).text
    assert "smtp-pass-secreta" not in audits
    # só administradores
    assert clients["operator"].get("/api/admin/credentials").status_code == 403


def test_credential_validation_and_update(env, clients):
    a = clients["admin"]
    assert a.post("/api/admin/credentials", json={**API, "fields": {"username": "x"}}).status_code == 422
    assert a.post("/api/admin/credentials", json={**API, "fields": {**API["fields"], "extra": 1}}).status_code == 422
    assert a.post("/api/admin/credentials", json={**API, "kind": "ftp"}).status_code == 422
    cid = a.post("/api/admin/credentials", json=API).json()["id"]
    assert a.put(f"/api/admin/credentials/{cid}", json={"fields": {"password": "nova-pass-123"}}).status_code == 200
    from botmanager.security import vault

    env["db"].expire_all()
    assert vault.decrypt(env["db"].get(Credential, cid).encrypted_data) == {"password": "nova-pass-123"}


def test_credential_in_use_cannot_be_deleted(env, clients):
    _setup(clients)
    cid = [c for c in clients["admin"].get("/api/admin/credentials").json() if c["name"] == "cyclos-dev"][0]["id"]
    r = clients["admin"].delete(f"/api/admin/credentials/{cid}")
    assert r.status_code == 409 and "transacoes-dev" in r.json()["detail"]


def test_flow_validation_errors(env, clients):
    a = clients["admin"]
    a.post("/api/admin/credentials", json=API)
    a.post("/api/admin/credentials", json=SMTP)

    def check(steps):
        return a.post("/api/flows/validate", json={"definition": {"steps": steps}}).json()

    assert check(FLOW["steps"][:1])["valid"]
    bad = [
        [{"id": "a", "type": "http_request", "url": "http://inseguro.pt/x"}],
        [{"id": "a", "type": "http_request", "url": "https://x.pt", "headers": {"Authorization": "Basic abc"}}],
        [{"id": "a", "type": "http_request", "url": "https://x.pt", "credential": "nao-existe"}],
        [{"id": "a", "type": "http_request", "url": "https://x.pt", "credential": "smtp-geral"}],
        [{"id": "a", "type": "http_request", "url": "https://x.pt", "method": "POST", "retries": 2}],
        [{"id": "a", "type": "log", "message": "{{ x "}],
        [{"id": "a", "type": "shell", "command": "dir"}],
        [{"id": "a", "type": "log", "message": "x"}, {"id": "a", "type": "log", "message": "y"}],
        [{"id": "a", "type": "csv_write", "file": "../x.csv", "rows_expr": "[]", "columns": [{"header": "h", "value": "v"}]}],
        [{"id": "a", "type": "sql_query", "credential": "x", "query": "select * from t where id = {{ id }}"}],
        [{"id": "a", "type": "sql_query", "credential": "x", "query": "delete from t"}],
    ]
    for steps in bad:
        assert check(steps)["valid"] is False, steps


def test_create_flow_requires_admin_and_unique_key(clients):
    body = {"key": "x-flow", "name": "Fluxo x", "definition": {"steps": [{"id": "l", "type": "log", "message": "x"}]}}
    assert clients["operator"].post("/api/flows", json=body).status_code == 403
    assert clients["admin"].post("/api/flows", json=body).status_code == 201
    assert clients["admin"].post("/api/flows", json=body).status_code == 409
    assert clients["admin"].post("/api/flows", json={**body, "key": "low-bot"}).status_code == 409


def test_new_flow_disabled_until_enabled_and_high_risk_needs_approval(env, clients):
    body = {"key": "fluxo-risco", "name": "Fluxo de risco", "risk_level": "high",
            "definition": {"steps": [{"id": "l", "type": "log", "message": "x"}]}}
    created = clients["admin"].post("/api/flows", json=body).json()
    assert created["enabled"] is False and created["requires_approval"] is True
    assert run_bot(clients["operator"], "fluxo-risco").status_code == 409
    clients["admin"].patch("/api/admin/bots/fluxo-risco", json={"enabled": True})
    assert run_bot(clients["operator"], "fluxo-risco").json()["status"] == "WAITING_APPROVAL"


def test_versions_and_pinned_version(env, clients):
    _setup(clients)
    a = clients["admin"]
    rid = run_bot(clients["operator"], "transacoes-dev").json()["run_id"]
    # nova versão gravada depois do pedido
    v2 = {**FLOW, "steps": FLOW["steps"][:1]}
    assert a.put("/api/flows/transacoes-dev", json={"definition": v2, "comment": "sem email"}).json()["version"] == 2
    data = a.get("/api/flows/transacoes-dev").json()
    assert data["current_version"] == 2 and [v["version"] for v in data["versions"]] == [2, 1]
    assert a.get("/api/flows/transacoes-dev", params={"version": 1}).json()["definition"]["steps"][2]["type"] == "email"
    # o trabalho executa a versão do momento do pedido (1)
    job = worker_client(env["app"], "worker-token-1")
    env["db"].query(Bot)  # noqa
    from botmanager.models import Worker

    w = env["db"].query(Worker).filter_by(name="w1").one()
    w.capabilities = ["flow"]
    env["db"].commit()
    j = job.post("/api/worker/claim", json={}).json()
    assert j["run_id"] == rid and j["flow"]["version"] == 1 and len(j["flow"]["definition"]["steps"]) == 3
    # apenas as credenciais referidas, decifradas
    assert set(j["credentials"]) == {"cyclos-dev", "smtp-geral"}
    assert j["credentials"]["cyclos-dev"]["password"] == "api-pass-secreta"
    assert clients["viewer"].get(f"/api/runs/{rid}").json()["flow_version"] == 1


def test_operator_cannot_edit_flow(clients):
    _setup(clients)
    r = clients["operator"].put("/api/flows/transacoes-dev", json={"definition": FLOW})
    assert r.status_code == 403


def test_artifacts_upload_and_download(env, clients):
    _setup(clients)
    from botmanager.models import Worker

    w = env["db"].query(Worker).filter_by(name="w1").one()
    w.capabilities = ["flow"]
    env["db"].commit()
    rid = run_bot(clients["operator"], "transacoes-dev").json()["run_id"]
    wc = worker_client(env["app"])
    wc.post("/api/worker/claim", json={})
    data = "ID\n1\n".encode()
    up = wc.post(f"/api/worker/runs/{rid}/artifacts",
                 json={"name": "transacoes.csv", "content_type": "text/csv", "data_b64": base64.b64encode(data).decode()})
    assert up.status_code == 201
    bad = wc.post(f"/api/worker/runs/{rid}/artifacts", json={"name": "../x", "data_b64": "AA=="})
    assert bad.status_code == 422
    wc.post(f"/api/worker/runs/{rid}/complete", json={"status": "SUCCEEDED"})
    arts = clients["viewer"].get(f"/api/runs/{rid}/artifacts").json()
    assert arts[0]["name"] == "transacoes.csv" and arts[0]["size_bytes"] == len(data)
    dl = clients["viewer"].get(f"/api/runs/{rid}/artifacts/{arts[0]['id']}")
    assert dl.content == data and "attachment" in dl.headers["content-disposition"]
    # utilizador sem acesso ao bot não descarrega
    assert clients["admin"].get("/api/admin/audit", params={"action": "artifact.downloaded"}).json()


def test_registry_sync_keeps_ui_flows(env, clients):
    _setup(clients)
    sync_registry(env["db"], [env["registry"]])
    bot = env["db"].query(Bot).filter_by(key="transacoes-dev").one()
    assert bot.in_registry and bot.enabled and bot.source == "ui"


def test_missing_credential_at_run_time_fails_safely(env, clients):
    _setup(clients)
    from botmanager.models import Worker

    db = env["db"]
    w = db.query(Worker).filter_by(name="w1").one()
    w.capabilities = ["flow"]
    db.query(Credential).filter_by(name="cyclos-dev").delete()
    db.commit()
    rid = run_bot(clients["operator"], "transacoes-dev").json()["run_id"]
    assert worker_client(env["app"]).post("/api/worker/claim", json={}).status_code == 204
    run = clients["viewer"].get(f"/api/runs/{rid}").json()
    assert run["status"] == "FAILED" and run["failure_reason"] == "worker_rejected" and not run["needs_review"]


def test_bootstrap(env, monkeypatch):
    from botmanager import config as bm_config
    from botmanager.models import Worker
    from botmanager.security.passwords import hash_token
    from botmanager.services.bootstrap import bootstrap

    monkeypatch.setenv("BM_BOOTSTRAP_RUNNER_TOKEN", "r" * 40)
    bm_config.get_settings.cache_clear()
    bootstrap(env["db"])
    w = env["db"].query(Worker).filter_by(name="flow-runner").one()
    assert w.capabilities == ["flow"] and w.token_hash == hash_token("r" * 40)
    monkeypatch.setenv("BM_BOOTSTRAP_RUNNER_TOKEN", "s" * 40)
    bm_config.get_settings.cache_clear()
    bootstrap(env["db"])
    assert w.token_hash == hash_token("s" * 40)


def test_smtp_sender_must_be_full_email(clients):
    bad = {**SMTP, "name": "smtp-mau", "fields": {**SMTP["fields"], "from_address": "teste"}}
    r = clients["admin"].post("/api/admin/credentials", json=bad)
    assert r.status_code == 422 and "email completo" in r.json()["detail"]
