"""Robôs Groovy: definição, validação, conversões fluxo ⇄ Groovy, duplicação e simulação (dry run)."""
import shutil
import sys
from pathlib import Path

import pytest

from conftest import run_bot, worker_client  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "worker"))

try:
    from lusopay_worker.groovy import GroovyUnavailable, runtime

    runtime()
    HAS_GROOVY = True
except Exception:  # noqa: BLE001 - sem Java/Groovy neste ambiente
    HAS_GROOVY = False

needs_groovy = pytest.mark.skipif(not HAS_GROOVY, reason="Java 17–23 e Groovy (python -m lusopay_worker.groovy setup)")

API = {"name": "cyclos-dev", "kind": "http_basic", "fields": {"username": "u", "password": "segredo-api"}}
CODE = '''def clientes = http.get("https://dev.lusopay.com:8444/web_dev/api/users", credencial: "cyclos-dev")
log "recebidos ${clientes.size()}"
'''
FLOW = {"description": "teste", "variables": {"total": 0},
        "steps": [{"id": "a", "type": "http_request", "url": "https://dev.lusopay.com:8444/x", "credential": "cyclos-dev",
                   "save_as": "lista"},
                  {"id": "b", "type": "foreach", "items_expr": "lista", "item_variable": "c", "carry": ["total"],
                   "steps": [{"id": "c1", "type": "set", "variable": "total", "expr": "total + (c.valor | num)"}]},
                  {"id": "d", "type": "log", "message": "total {{ total | money }}"}]}


def _create(clients, key="robo-groovy", definition=None, **meta):
    a = clients["admin"]
    a.post("/api/admin/credentials", json=API)
    r = a.post("/api/flows", json={"key": key, "name": "Robô Groovy", "risk_level": "low",
                                   "definition": definition or {"language": "groovy", "code": CODE}, **meta})
    assert r.status_code == 201, r.text
    return r.json()


def test_groovy_definition_is_stored_and_versioned(clients):
    _create(clients)
    a = clients["admin"]
    d = a.get("/api/flows/robo-groovy").json()["definition"]
    assert d["language"] == "groovy" and d["code"] == CODE and "steps" not in d
    # os dois formatos são exclusivos
    bad = a.put("/api/flows/robo-groovy", json={"definition": {"language": "groovy", "code": CODE, "steps": FLOW["steps"]}})
    assert bad.status_code == 422
    assert a.put("/api/flows/robo-groovy", json={"definition": {"language": "groovy", "code": "  "}}).status_code == 422


def test_groovy_credentials_detected_and_validated(env, clients):
    _create(clients)
    a = clients["admin"]
    r = a.post("/api/flows/validate", json={"definition": {"language": "groovy",
                                                           "code": 'http.get("https://x/y", credencial: "nao-existe")'}})
    assert r.json()["valid"] is False and "nao-existe" in r.json()["error"]
    r = a.post("/api/flows/validate", json={"definition": {"language": "groovy", "code": "def c = 'x'\nhttp.get('https://x', credencial: c)"}})
    assert r.json()["valid"] is False and r.json()["errors"][0]["line"] == 2
    # só a credencial referida chega ao worker
    from botmanager.models import Worker

    w = env["db"].query(Worker).filter_by(name="w1").one()
    w.capabilities = ["flow"]
    env["db"].commit()
    a.patch("/api/admin/bots/robo-groovy", json={"enabled": True})
    rid = run_bot(clients["operator"], "robo-groovy").json()["run_id"]
    job = worker_client(env["app"]).post("/api/worker/claim", json={}).json()
    assert job["run_id"] == rid and set(job["credentials"]) == {"cyclos-dev"}
    assert job["flow"]["definition"]["language"] == "groovy" and job["dry_run"] is False


@needs_groovy
def test_check_code_reports_syntax_and_security_errors(clients):
    a = clients["admin"]
    a.post("/api/admin/credentials", json=API)
    r = a.post("/api/flows/check-code", json={"code": "def x = 1\nif (x > 0 {\n}"}).json()
    assert r["checked"] and r["errors"] and r["errors"][0]["line"] in (2, 3)
    r = a.post("/api/flows/check-code", json={"code": 'log "x"\n"ls".execute()'}).json()
    assert "execute" in r["errors"][0]["message"] and r["errors"][0]["line"] == 2
    r = a.post("/api/flows/check-code", json={"code": CODE}).json()
    assert r["errors"] == [] and r["credentials"] == [{"name": "cyclos-dev", "exists": True, "kind": "http_basic"}]
    # gravar código com erro de sintaxe é recusado
    _create(clients, key="robo-x")
    bad = a.put("/api/flows/robo-x", json={"definition": {"language": "groovy", "code": "if ("}})
    assert bad.status_code == 422 and "linha 1" in bad.json()["detail"]


def test_flow_to_groovy_transform_does_not_save(clients):
    _create(clients, key="robo-fluxo", definition=FLOW)
    a = clients["admin"]
    r = a.post("/api/flows/transform", json={"definition": FLOW, "target": "groovy"}).json()
    code = r["definition"]["code"]
    assert r["complete"] and r["definition"]["language"] == "groovy" and r["definition"]["variables"] == {"total": 0}
    assert 'lista = http.get(\'https://dev.lusopay.com:8444/x\', credencial: \'cyclos-dev\')' in code
    assert "for (c in as_list(lista))" in code and "total = (total + num(c.valor))" in code
    assert 'log "total ${money(total)}"' in code
    # nada foi gravado
    assert a.get("/api/flows/robo-fluxo").json()["current_version"] == 1


@needs_groovy
def test_groovy_to_flow_transform_and_limits(clients):
    a = clients["admin"]
    a.post("/api/admin/credentials", json=API)
    code = ('lista = http.get("https://dev.lusopay.com:8444/x", credencial: "cyclos-dev")\n'
            'for (c in lista) {\n    total = total + num(c.valor)\n}\nlog "total ${money(total)}"\n')
    r = a.post("/api/flows/transform", json={"definition": {"language": "groovy", "code": code, "variables": {"total": 0}},
                                             "target": "flow"}).json()
    steps = r["definition"]["steps"]
    assert [s["type"] for s in steps] == ["http_request", "foreach", "log"]
    assert steps[1]["carry"] == ["total"] and steps[1]["steps"][0]["expr"] == "(total + (c.valor | num))"
    assert steps[2]["message"] == "total {{ (total | money) }}"
    # código sem equivalente: conversão incompleta, com relatório; nada é apagado
    r = a.post("/api/flows/transform", json={"definition": {"language": "groovy", "code": "def f(x) { x }\nlog f(1)"},
                                             "target": "flow"}).json()
    assert r["complete"] is False and any("método 'f'" in i["message"] for i in r["report"])


def test_duplicate_into_other_format(clients):
    _create(clients, key="robo-fluxo", definition=FLOW)
    a = clients["admin"]
    r = a.post("/api/flows/robo-fluxo/duplicate", json={"key": "robo-fluxo-groovy", "name": "Cópia Groovy", "target": "groovy"})
    assert r.status_code == 201, r.text
    d = a.get("/api/flows/robo-fluxo-groovy").json()
    assert d["definition"]["language"] == "groovy" and d["bot"]["enabled"] is False
    assert clients["operator"].post("/api/flows/robo-fluxo/duplicate", json={"key": "x-y-z", "name": "abc"}).status_code == 403


def test_dry_run_allowed_on_disabled_flow_without_approval(env, clients):
    _create(clients, risk_level="high")
    a = clients["admin"]
    import uuid

    body = {"parameters": {}, "idempotency_key": uuid.uuid4().hex, "dry_run": True}
    # o operador não configura o robô: não pode testar
    assert clients["operator"].post("/api/bots/robo-groovy/run", json=body).status_code == 403
    r = a.post("/api/bots/robo-groovy/run", json=body)
    assert r.status_code == 202 and r.json()["status"] == "QUEUED"
    run = a.get(f"/api/runs/{r.json()['run_id']}").json()
    assert run["dry_run"] is True
    # uma execução real de um robô desativado continua recusada
    assert a.post("/api/bots/robo-groovy/run", json={**body, "dry_run": False,
                                                    "idempotency_key": uuid.uuid4().hex}).status_code == 409
    from botmanager.models import Worker

    w = env["db"].query(Worker).filter_by(name="w1").one()
    w.capabilities = ["flow"]
    env["db"].commit()
    wc = worker_client(env["app"])
    job = wc.post("/api/worker/claim", json={}).json()
    assert job["dry_run"] is True


@needs_groovy
def test_upload_file_converts_both_ways(clients):
    a = clients["admin"]
    flow = {"steps": [
        {"id": "f", "type": "text_write", "file": "r.txt", "content": "x"},
        {"id": "up", "type": "http_request", "method": "POST", "url": "https://dev.lusopay.com:8444/api/files/temp",
         "credential": "cyclos-dev", "upload_file": "r.txt", "response": "text", "expect_status": [201], "save_as": "id"}]}
    r = a.post("/api/flows/transform", json={"definition": flow, "target": "groovy"}).json()
    assert r["complete"], r
    assert "ficheiro: 'r.txt'" in r["definition"]["code"]
    back = a.post("/api/flows/transform", json={"definition": r["definition"], "target": "flow"}).json()
    up = back["definition"]["steps"][-1]
    assert up["upload_file"] == "r.txt" and up["method"] == "POST" and "body_text" not in up
    # ficheiro e corpo ao mesmo tempo, ou com GET: inválido
    bad = dict(flow["steps"][1], body_text="x")
    r = a.post("/api/flows/validate", json={"definition": {"steps": [bad]}}).json()
    assert not r["valid"] and "ficheiro OU um corpo" in str(r)
    get = dict(flow["steps"][1], method="GET")
    r = a.post("/api/flows/validate", json={"definition": {"steps": [get]}}).json()
    assert not r["valid"] and "POST, PUT ou PATCH" in r["error"]
