"""Testes do motor de fluxos nativos (HTTP, SMTP e SQL simulados)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import httpx
import pytest

from lusopay_worker.flowengine import Engine, extract_path

CREDS = {
    "cyclos-dev": {"kind": "http_basic", "username": "cliente7", "password": "pass-super-secreta"},
    "token-api": {"kind": "http_bearer", "token": "tok-abcdefghijkl"},
    "smtp-geral": {"kind": "smtp", "host": "mail.exemplo.pt", "port": 587, "username": "geral@exemplo.pt",
                   "password": "smtp-pass-secreta", "from_address": "geral@exemplo.pt", "security": "starttls"},
    "magnimeios": {"kind": "mssql", "server": "sql1", "port": 1433, "database": "db", "username": "u",
                   "password": "sql-pass-secreta"},
}

TX = [{"id": 1, "amount": "10.50", "description": "=HYPERLINK(\"x\")"}, {"id": 2, "amount": "3.00", "description": "ok"}]


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None, **kw):
        self.host, self.port = host, port
        self.logged = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, u, p):
        self.logged = (u, p)

    def send_message(self, msg):
        FakeSMTP.sent.append((self, msg))


def make_engine(tmp_path, steps, handler=None, allowed=(), variables=None, sql=None, params=None):
    lines: list[str] = []
    calls: list[httpx.Request] = []

    def default_handler(req: httpx.Request):
        calls.append(req)
        return httpx.Response(200, json=TX)

    def wrapped(req):
        calls.append(req)
        return handler(req)

    transport = httpx.MockTransport(wrapped if handler else default_handler)
    job = {"run_id": "r1", "flow": {"version": 1, "definition": {"variables": variables or {}, "steps": steps}},
           "credentials": CREDS, "allowed_hosts": list(allowed), "parameters": params or {}}
    FakeSMTP.sent = []
    eng = Engine(job, tmp_path, emit=lines.append, http_client=httpx.Client(transport=transport),
                 smtp_factory=FakeSMTP, sql_connect=sql)
    return eng, lines, calls


GET_TX = {"id": "tx", "type": "http_request", "method": "GET",
          "url": "https://dev.lusopay.com:8444/web_dev/api/transactions",
          "headers": {"accept": "application/json"}, "credential": "cyclos-dev", "save_as": "transacoes"}


def test_users_example_api_csv_email(tmp_path):
    steps = [
        GET_TX,
        {"id": "csv", "type": "csv_write", "file": "transacoes {{ now() | date('%Y-%m-%d') }}.csv",
         "rows_expr": "transacoes", "columns": [{"header": "ID", "value": "{{ row.id }}"},
                                                {"header": "Valor", "value": "{{ row.amount | money }}"},
                                                {"header": "Descrição", "value": "{{ row.description }}"}]},
        {"id": "mail", "type": "email", "credential": "smtp-geral", "to": ["ricardosilva@lusopay.com"],
         "subject": "Transações dev ({{ transacoes | length }})", "body": "Em anexo.",
         "attachments": ["{{ files[0] }}"]},
    ]
    eng, lines, calls = make_engine(tmp_path, steps)
    res = eng.run()
    assert res["status"] == "SUCCEEDED", res
    # autenticação Basic enviada mas nunca registada
    assert calls[0].headers["authorization"].startswith("Basic ")
    assert not any("pass-super-secreta" in l or "smtp-pass-secreta" in l for l in lines)
    assert any("GET https://dev.lusopay.com:8444/web_dev/api/transactions → 200" in l for l in lines)
    # CSV com proteção contra fórmulas e formato PT
    f = tmp_path / res["files"][0]
    rows = list(csv.reader(f.open(encoding="utf-8-sig"), delimiter=";"))
    assert rows[0] == ["ID", "Valor", "Descrição"]
    assert rows[1] == ["1", "10,50", "'=HYPERLINK(\"x\")"]
    # email com anexo, STARTTLS e login
    smtp, msg = FakeSMTP.sent[0]
    assert smtp.tls and smtp.logged == ("geral@exemplo.pt", "smtp-pass-secreta")
    assert msg["To"] == "ricardosilva@lusopay.com" and msg["Subject"] == "Transações dev (2)"
    assert [p.get_filename() for p in msg.iter_attachments()] == [res["files"][0]]
    assert res["counters"] == {"steps": 3, "http_requests": 1, "emails": 1, "sql_queries": 0}


def test_bearer_and_host_allowlist(tmp_path):
    step = {**GET_TX, "credential": "token-api"}
    eng, _, calls = make_engine(tmp_path, [step], allowed=["dev.lusopay.com"])
    assert eng.run()["status"] == "SUCCEEDED"
    assert calls[0].headers["authorization"] == "Bearer tok-abcdefghijkl"
    eng, _, calls = make_engine(tmp_path, [GET_TX], allowed=["app.lusopay.com"])
    res = eng.run()
    assert res["status"] == "FAILED" and "não autorizado" in res["error"] and calls == []


def test_unexpected_status_fails_and_error_is_redacted(tmp_path):
    eng, lines, _ = make_engine(tmp_path, [GET_TX],
                                handler=lambda r: httpx.Response(500, text="erro password=pass-super-secreta"))
    res = eng.run()
    assert res["status"] == "FAILED" and res["failed_step"] == "tx"
    assert "pass-super-secreta" not in res["error"] and all("pass-super-secreta" not in l for l in lines)


def test_get_retries_but_post_never(tmp_path, monkeypatch):
    n = {"c": 0}

    def flaky(req):
        n["c"] += 1
        return httpx.Response(503) if n["c"] == 1 else httpx.Response(200, json={})

    import lusopay_worker.flowengine as fe

    monkeypatch.setattr(fe.time, "sleep", lambda s: None)
    eng, _, _ = make_engine(tmp_path, [{**GET_TX, "retries": 2}], handler=flaky)
    assert eng.run()["status"] == "SUCCEEDED" and n["c"] == 2
    n["c"] = 0
    post = {**GET_TX, "method": "POST", "body_json_expr": "{'a': 1}", "expect_status": [200]}
    eng, _, _ = make_engine(tmp_path, [post], handler=flaky)
    assert eng.run()["status"] == "FAILED" and n["c"] == 1  # POST não é repetido


def test_post_json_body(tmp_path):
    seen = {}

    def h(req):
        seen["body"] = json.loads(req.content)
        seen["ct"] = req.headers["content-type"]
        return httpx.Response(201, json={"id": 9})

    step = {"id": "p", "type": "http_request", "method": "POST", "url": "https://api.exemplo.pt/x",
            "body_json_expr": "{'cliente': params.nif, 'valor': 5}", "expect_status": [201], "save_as": "r"}
    eng, _, _ = make_engine(tmp_path, [step], handler=h, params={"nif": "123"})
    assert eng.run()["status"] == "SUCCEEDED"
    assert seen == {"body": {"cliente": "123", "valor": 5}, "ct": "application/json"}


def test_foreach_parallel_append_if_and_extract(tmp_path):
    def h(req):
        uid = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"id": uid, "name": f"Cliente {uid}", "saldo": int(uid) * 10})

    steps = [
        {"id": "ids", "type": "set", "variable": "ids", "expr": "[1,2,3,4,5,6]"},
        {"id": "lst", "type": "set", "variable": "saldos", "expr": "[]"},
        {"id": "loop", "type": "foreach", "items_expr": "ids", "item_variable": "uid", "parallel": 4, "steps": [
            {"id": "get", "type": "http_request", "url": "https://api.exemplo.pt/users/{{ uid }}", "save_as": "u"},
            {"id": "cond", "type": "if", "condition": "u.saldo > 20", "then": [
                {"id": "add", "type": "append", "variable": "saldos", "expr": "{'nome': u.name, 'saldo': u.saldo}"}]},
        ]},
        {"id": "nomes", "type": "extract", "source_expr": "saldos", "path": "[*].nome", "save_as": "nomes"},
        {"id": "log", "type": "log", "message": "{{ nomes | length }} clientes"},
    ]
    eng, lines, calls = make_engine(tmp_path, steps, handler=h)
    res = eng.run()
    assert res["status"] == "SUCCEEDED", res
    assert len(calls) == 6 and "[log] 4 clientes" in lines


def test_foreach_failure_stops_flow(tmp_path):
    steps = [{"id": "loop", "type": "foreach", "items_expr": "[1,2,3]", "parallel": 2, "steps": [
        {"id": "f", "type": "if", "condition": "item == 2", "then": [{"id": "x", "type": "fail", "message": "item {{ item }}"}]}]},
        {"id": "never", "type": "log", "message": "não deve correr"}]
    eng, lines, _ = make_engine(tmp_path, steps)
    res = eng.run()
    assert res["status"] == "FAILED" and res["failed_step"] == "x" and "item 2" in res["error"]
    assert not any("não deve correr" in l for l in lines)


def test_stop_and_continue_on_error(tmp_path):
    steps = [
        {"id": "bad", "type": "http_request", "url": "https://api.exemplo.pt/x", "continue_on_error": True},
        {"id": "s", "type": "stop", "message": "sem dados ({{ last_error is defined }})"},
        {"id": "never", "type": "fail", "message": "x"},
    ]
    eng, lines, _ = make_engine(tmp_path, steps, handler=lambda r: httpx.Response(404))
    res = eng.run()
    assert res["status"] == "SUCCEEDED" and res["stopped"] == "sem dados (True)"
    assert any(l.startswith("WARNING [bad]") for l in lines)


def test_undefined_variable_fails(tmp_path):
    eng, _, _ = make_engine(tmp_path, [{"id": "l", "type": "log", "message": "{{ nao_existe }}"}])
    res = eng.run()
    assert res["status"] == "FAILED" and "nao_existe" in res["error"]


def test_sandbox_blocks_python_internals(tmp_path):
    eng, _, _ = make_engine(tmp_path, [{"id": "x", "type": "set", "variable": "v",
                                        "expr": "''.__class__.__mro__[1].__subclasses__()"}])
    assert eng.run()["status"] == "FAILED"


def test_attachment_must_be_produced_by_flow(tmp_path):
    (tmp_path / "x.csv").write_text("a")
    eng, _, _ = make_engine(tmp_path, [{"id": "m", "type": "email", "credential": "smtp-geral", "to": ["a@b.pt"],
                                        "subject": "s", "body": "b", "attachments": ["x.csv"]}])
    assert eng.run()["status"] == "FAILED"


def test_invalid_email_and_bad_filename(tmp_path):
    eng, _, _ = make_engine(tmp_path, [{"id": "m", "type": "email", "credential": "smtp-geral",
                                        "to": ["a@b.pt, c@d.pt"], "subject": "s", "body": "b"}])
    assert eng.run()["status"] == "FAILED"
    eng, _, _ = make_engine(tmp_path, [{"id": "t", "type": "text_write", "file": "{{ '../x' }}", "content": "c"}])
    assert eng.run()["status"] == "FAILED"


def test_credential_kind_enforced(tmp_path):
    eng, _, _ = make_engine(tmp_path, [{**GET_TX, "credential": "smtp-geral"}])
    assert eng.run()["status"] == "FAILED"


class FakeCursor:
    def __init__(self, log):
        self.log = log
        self.description = [("x",)]

    def execute(self, q, params):
        self.log.append((q, params))

    def fetchall(self):
        return [{"contato": "9123", "total": 100}]


class FakeConn:
    def __init__(self, **kw):
        self.kw, self.log, self.rolled, self.committed, self.closed = kw, [], False, False, False

    def cursor(self, as_dict=False):
        return FakeCursor(self.log)

    def rollback(self):
        self.rolled = True

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_sql_query_parametrized_read_only(tmp_path):
    conns = []

    def connect(**kw):
        conns.append(FakeConn(**kw))
        return conns[-1]

    steps = [{"id": "q", "type": "sql_query", "credential": "magnimeios",
              "query": "select contato, sum(valor) total from MBWay where data >= %(inicio)s group by contato",
              "params": {"inicio": "{{ params.inicio }}"}, "save_as": "linhas"},
             {"id": "l", "type": "log", "message": "{{ linhas[0].contato }}"}]
    eng, lines, _ = make_engine(tmp_path, steps, sql=connect, params={"inicio": "2026-10-01"})
    assert eng.run()["status"] == "SUCCEEDED"
    c = conns[0]
    assert c.log[0][1] == {"inicio": "2026-10-01"} and c.rolled and not c.committed and c.closed
    assert c.kw["password"] == "sql-pass-secreta" and "[l] 9123" in lines


def test_extract_path():
    data = {"a": {"items": [{"id": 1}, {"id": 2}]}, "b": [[1, 2]]}
    assert extract_path(data, "a.items[*].id") == [1, 2]
    assert extract_path(data, "$.a.items[1].id") == 2
    assert extract_path(data, "b[0][1]") == 2
    assert extract_path(data, "a.nada.x") is None
