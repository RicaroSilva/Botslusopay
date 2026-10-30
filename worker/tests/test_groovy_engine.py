"""Robôs Groovy: execução isolada (JVM) com a ponte para o motor (http/email/sql/ficheiros)."""
from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from lusopay_worker.flowengine import Engine, make_env

try:
    from lusopay_worker.groovy import Runtime, run_tool, runtime

    runtime()
    HAS_GROOVY = True
except Exception:  # noqa: BLE001
    HAS_GROOVY = False

pytestmark = pytest.mark.skipif(not HAS_GROOVY, reason="Java 17–23 e Groovy (python -m lusopay_worker.groovy setup)")

CREDS = {"cyclos-dev": {"kind": "http_basic", "username": "u", "password": "segredo-muito-secreto"},
         "smtp-x": {"kind": "smtp", "host": "h", "port": 587, "username": "a@b.pt", "password": "p", "from_address": "a@b.pt"},
         "sql-x": {"kind": "mssql", "server": "s", "username": "u", "password": "p", "database": "d"}}


class SMTP:
    sent: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, u, p):
        pass

    def send_message(self, m):
        SMTP.sent.append(m)


def run(tmp_path, code, *, dry_run=False, variables=None, params=None, api=None, sql=None):
    calls, logs = [], []

    def default_api(r):
        calls.append((r.method, str(r.url), r.content.decode(), r.headers.get("authorization")))
        if r.method == "GET":
            return httpx.Response(200, json=[{"id": 1, "nome": "Ana"}, {"id": 2, "nome": "Rui"}])
        return httpx.Response(201, text="77")

    rt = runtime()
    job = {"run_id": "r1", "flow": {"version": 1, "definition": {"language": "groovy", "code": code,
                                                                 "variables": variables or {}}},
           "credentials": CREDS, "allowed_hosts": [], "parameters": params or {}, "dry_run": dry_run,
           "groovy": {"argv": rt.command("run", tmp_path), "env": Runtime.env(tmp_path)}}
    SMTP.sent = []
    res = Engine(job, tmp_path, emit=logs.append, http_client=httpx.Client(transport=httpx.MockTransport(api or default_api)),
                 smtp_factory=SMTP, sql_connect=sql).run()
    return res, calls, logs


def test_api_http_files_email_and_logs(tmp_path):
    code = r"""
def clientes = http.get("https://dev.lusopay.com:8444/api/users", credencial: "cyclos-dev", query: [pageSize: 10])
log "recebidos ${clientes.size()}"
println "linha do println"
ficheiro.gravar("nomes.txt", clientes.collect { it.nome }.join("\n"))
ficheiro.csv("t.csv", clientes, colunas: ["id", "nome"])
def novo = http.post("https://dev.lusopay.com:8444/api/x", [nomes: clientes*.nome], credencial: "cyclos-dev")
email.enviar(credencial: "smtp-x", para: params.para, assunto: "Total ${clientes.size()} (${novo})", corpo: "ok", anexos: ["t.csv"])
assert ficheiro.existe("nomes.txt") && ficheiro.ler("nada.txt") == null
"""
    res, calls, logs = run(tmp_path, code, params={"para": "x@y.pt; z@w.pt"})
    assert res["status"] == "SUCCEEDED", (res, logs)
    assert calls[0][1] == "https://dev.lusopay.com:8444/api/users?pageSize=10" and calls[0][3].startswith("Basic ")
    assert json.loads(calls[1][2]) == {"nomes": ["Ana", "Rui"]}
    assert (tmp_path / "nomes.txt").read_text() == "Ana\nRui"
    assert (tmp_path / "t.csv").read_text(encoding="utf-8-sig").splitlines() == ["id;nome", "1;Ana", "2;Rui"]
    assert SMTP.sent[0]["To"] == "x@y.pt, z@w.pt" and SMTP.sent[0]["Subject"] == "Total 2 (77)"
    assert "recebidos 2" in logs and "linha do println" in logs
    assert res["files"] == ["nomes.txt", "t.csv"] and res["counters"]["http_requests"] == 2
    assert not any("segredo-muito-secreto" in line for line in logs)


def test_dry_run_sends_nothing(tmp_path):
    code = """
http.post("https://dev.lusopay.com:8444/api/x", [a: 1], credencial: "cyclos-dev")
email.enviar(credencial: "smtp-x", para: "a@b.pt", assunto: "s", corpo: "c")
log "fim"
"""
    res, calls, logs = run(tmp_path, code + 'log "simulacao=${simulacao}"\n', dry_run=True)
    assert res["status"] == "SUCCEEDED" and calls == [] and SMTP.sent == []
    assert "simulacao=true" in logs
    assert any("[SIMULAÇÃO] POST" in line for line in logs) and any("[SIMULAÇÃO] email" in line for line in logs)


def test_sql_named_parameters(tmp_path):
    seen = []

    class Cur:
        description = True

        def execute(self, q, p):
            seen.append((q, p))

        def fetchall(self):
            return [{"id": 9}]

    class Conn:
        committed = False

        def cursor(self, as_dict):
            return Cur()

        def rollback(self):
            pass

        def commit(self):
            Conn.committed = True

        def close(self):
            pass

    code = """
def linhas = sql.consultar("sql-x", "select * from t where id > :ultimo and nome like 'a:b%'", [ultimo: 5])
log "id ${linhas[0].id}"
sql.executar("sql-x", "update t set x = 1 where id = :id", [id: linhas[0].id])
"""
    res, _, logs = run(tmp_path, code, sql=lambda **k: Conn())
    assert res["status"] == "SUCCEEDED", res
    assert seen[0] == ("select * from t where id > %(ultimo)s and nome like 'a:b%%'", {"ultimo": 5})
    assert seen[1] == ("update t set x = 1 where id = %(id)s", {"id": 9}) and Conn.committed
    assert "id 9" in logs


def test_errors_report_line_and_can_be_caught(tmp_path):
    res, _, logs = run(tmp_path, 'log "a"\ntry {\n  http.get("http://inseguro/x")\n} catch (e) {\n  aviso "apanhado: ${e.message}"\n}\n'
                                   'def x = null\nx.foo()\n')
    assert res["status"] == "FAILED" and res["failed_step"] == "linha 8" and "NullPointerException" in res["error"]
    assert any("apanhado: ValueError: só são permitidos pedidos https" in line for line in logs)
    res, _, _ = run(tmp_path, 'falhar("sem dados")')
    assert res["status"] == "FAILED" and res["error"] == "sem dados" and res["failed_step"] == "linha 1"
    res, _, _ = run(tmp_path, 'try { terminar("fim normal") } catch (e) { falhar("não devia apanhar") }')
    assert res["status"] == "SUCCEEDED" and res["stopped"] == "fim normal"
    res, _, _ = run(tmp_path, "if (true {")
    assert res["status"] == "FAILED" and res["failed_step"] == "compilação"


@pytest.mark.parametrize("code,blocked", [
    ('"ls".execute()', "método não permitido: execute"),
    ('new File("/etc/passwd").text', "tipo não permitido: File"),
    ('log "file:///etc/passwd".toURL().text', "leitura não permitida"),
    ('log "https://example.com".toURL().text', "rede não permitida"),
    ('this.class.classLoader', "propriedade não permitida"),
    ('@groovy.transform.ASTTest(value={ assert false })\ndef x = 1', "anotações não permitidas"),
    ('def m = "execute"\n"ls"."$m"()', "nome de método dinâmico"),
    ('import java.net.Socket\n1', "import não permitido"),
])
def test_sandbox_blocks_dangerous_code(tmp_path, code, blocked):
    res, calls, _ = run(tmp_path, code)
    assert res["status"] == "FAILED" and blocked in res["error"], res
    assert calls == []


def test_parallel_calls(tmp_path):
    res, calls, _ = run(tmp_path, 'paralelo(1..8, 4) { n -> http.get("https://dev.lusopay.com:8444/api/u/${n}", credencial: "cyclos-dev") }')
    assert res["status"] == "SUCCEEDED" and len(calls) == 8


def test_helpers_match_flow_engine(tmp_path):
    """As funções auxiliares do Groovy dão o mesmo texto que os filtros dos fluxos (base das conversões)."""
    cases = {
        "text_list": ("text([1, 'a', null])", "[1, 'a', none] | text"),
        "text_map": ("text([a: 1.5, b: true])", "{'a': 1.5, 'b': true} | text"),
        "text_bool": ("text(true)", "true | text"),
        "num_pt": ("text(num('1.234,56'))", "'1.234,56' | num | text"),
        "num_int": ("text(num('42'))", "'42' | num | text"),
        "money": ("money('7.5')", "'7.5' | money"),
        "decimal": ("decimal(2.345, 1)", "2.345 | decimal(1)"),
        "between": ("between('a[x]b[y]', '[', ']', 1)", "'a[x]b[y]' | between('[', ']', 1)"),
        "after": ("after('k=v=w', '=')", "'k=v=w' | after('=')"),
        "before": ("before('k=v=w', '=', 1)", "'k=v=w' | before('=', 1)"),
        "regex": ("regex('ab123cd', '([0-9]+)', 1)", "'ab123cd' | regex('([0-9]+)', 1)"),
        "regex_replace": ("regex_replace('ab12', '([0-9]+)', '<$1>')", "'ab12' | regex_replace('([0-9]+)', '<$1>')"),
        "split": ("text(split_text('a;b;;c', ';'))", "'a;b;;c' | split_text(';') | text"),
        "jsonpath": ("""text(jsonpath('{"a": {"b": [1, 2]}}', '$.a.b[1]'))""", """'{"a": {"b": [1, 2]}}' | jsonpath('$.a.b[1]') | text"""),
        "jsonpath_deep": ("text(jsonpath([x: [y: [z: 5]]], '$..z'))", "{'x': {'y': {'z': 5}}} | jsonpath('$..z') | text"),
        "as_list": ("text(as_list('[1,2]'))", "'[1,2]' | as_list | text"),
        "as_list_single": ("text(as_list('ANA'))", "'ANA' | as_list | text"),
        "date": ("date('2026-03-15', '%d/%m/%Y %B %A')", "'2026-03-15' | date('%d/%m/%Y %B %A')"),
        "add_time": ("date(add_time('2026-01-31', 'months', 1), '%Y-%m-%d')", "'2026-01-31' | add_time('months', 1) | date('%Y-%m-%d')"),
        "add_days": ("date(add_days('2026-03-01', -1))", "'2026-03-01' | add_days(-1) | date"),
        "compare_num": ("text(taskt_compare('10', 'is greater than', '9'))", "taskt_compare('10', 'is greater than', '9') | text"),
        "compare_text": ("text(taskt_compare('Ana', 'contains', 'AN'))", "taskt_compare('Ana', 'contains', 'AN') | text"),
        "is_numeric": ("text(is_numeric('12,5'))", "is_numeric('12,5') | text"),
        "tojson": ("tojson([a: [1, 'ç']])", "{'a': [1, 'ç']} | tojson"),
        "length": ("text(length('abc'))", "'abc' | length | text"),
    }
    code = "def r = [:]\n" + "".join(f"r[{json.dumps(k)}] = {g}\n" for k, (g, _) in cases.items()) + 'ficheiro.gravar("r.json", tojson(r))'
    res, _, logs = run(tmp_path, code)
    assert res["status"] == "SUCCEEDED", (res, logs)
    groovy = json.loads((tmp_path / "r.json").read_text())
    env = make_env()
    for k, (_, jinja) in cases.items():
        expected = env.from_string("{{ " + jinja + " }}").render()
        assert groovy[k] == expected, (k, groovy[k], expected)


def test_upload_file_to_cyclos_temp(tmp_path):
    seen = []

    def api(r):
        seen.append((r.method, str(r.url), r.headers["content-type"], r.content))
        return httpx.Response(201, text="-555")

    code = """
ficheiro.gravar("relatorio.txt", "linha 1")
def id = http.post("https://dev.lusopay.com:8444/api/files/temp", credencial: "cyclos-dev", ficheiro: "relatorio.txt", resposta: "texto")
http.post("https://dev.lusopay.com:8444/api/x", [descricao: "teste"], credencial: "cyclos-dev", ficheiro: "relatorio.txt", campo: "anexo")
log "id=${id}"
"""
    res, _, logs = run(tmp_path, code, api=api)
    assert res["status"] == "SUCCEEDED", (res, logs)
    assert "id=-555" in logs
    assert seen[0][2].startswith("multipart/form-data") and b'name="file"; filename="relatorio.txt"' in seen[0][3]
    assert b"linha 1" in seen[0][3]
    assert b'name="anexo"' in seen[1][3] and b'name="descricao"' in seen[1][3] and b"teste" in seen[1][3]
    # simulação: nada é enviado
    seen.clear()
    res, _, logs = run(tmp_path, code, api=api, dry_run=True)
    assert res["status"] == "SUCCEEDED" and seen == [] and any("ficheiro relatorio.txt" in line for line in logs)
