"""Executa os fluxos migrados (bots/flows/*.json) contra uma API Cyclos SIMULADA.

Confirma que os fluxos correm e produzem ficheiros/emails coerentes. Não prova
que os dados reais do Cyclos têm o formato assumido: isso confirma-se ao correr
em paralelo com o bot antigo."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from lusopay_worker.flowengine import Engine
from test_flowengine import CREDS, FakeSMTP

FLOWS = Path(__file__).resolve().parents[2] / "bots" / "flows"
CREDS = {**CREDS, "cyclos-producao": CREDS["cyclos-dev"], "smtp-lusopay": CREDS["smtp-geral"]}


def run_flow(tmp_path, name, handler):
    flow = json.loads((FLOWS / name).read_text(encoding="utf-8"))
    calls = []

    def h(req: httpx.Request):
        calls.append(req)
        return handler(req)

    lines: list[str] = []
    FakeSMTP.sent = []
    eng = Engine({"run_id": "r", "flow": {"version": 1, "definition": flow["definition"]}, "credentials": CREDS,
                  "allowed_hosts": ["app.lusopay.com"]}, tmp_path, emit=lines.append,
                 http_client=httpx.Client(transport=httpx.MockTransport(h)), smtp_factory=FakeSMTP)
    return eng.run(), calls, lines


def test_saldos(tmp_path):
    users = [{"id": f"u{i}", "balance": f"{i}.50"} for i in range(25)]

    def h(req):
        if req.url.path.endswith("/user-balances"):
            assert req.url.params["pageSize"] == "99999"
            return httpx.Response(200, json=users)
        uid = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"name": f"Cliente {uid}"})

    res, calls, _ = run_flow(tmp_path, "saldos-clientes-nativo.json", h)
    assert res["status"] == "SUCCEEDED", res
    assert len(calls) == 26
    rows = list(csv.reader((tmp_path / res["files"][0]).open(encoding="utf-8-sig"), delimiter=";"))
    assert rows[0] == ["Nome do cliente", "Saldo"]
    assert rows[1:4] == [["Cliente u0", "0.50"], ["Cliente u1", "1.50"], ["Cliente u2", "2.50"]]  # ordem da API
    msg = FakeSMTP.sent[0][1]
    assert msg["To"] == "ricardosilva@lusopay.com" and "Saldos de clientes no Cyclos a" in msg["Subject"]


def test_transacoes_aleatorias(tmp_path):
    clientes = [{"id": f"c{i}", "customValues": {"IdentificadorPublicoDeConta": f"PT{i:04d}"}} for i in range(100)]

    def h(req):
        if req.url.path == "/web/api/users":
            q = parse_qs(req.url.query.decode())
            assert q["fields"] == ["id", "customValues.IdentificadorPublicoDeConta"]
            assert q["statuses"] == ["active"] and "PtPenhoraPessoaSingular" in q["groups"][0]
            return httpx.Response(200, json=clientes)
        cid = req.url.path.split("/")[3]
        assert req.url.params["direction"] == "credit"
        n = int(cid[1:])
        mov = [] if n % 2 else [{"date": "2026-09-03", "type": {"name": "Pagamento MB"}, "description": "x",
                                  "amount": "10.00", "transactionNumber": f"T{n}"}]
        return httpx.Response(200, json=mov)

    res, calls, _ = run_flow(tmp_path, "transacoes-aleatorias-nativo.json", h)
    assert res["status"] == "SUCCEEDED", res
    assert len(calls) == 31  # 1 lista + 30 clientes, sem repetidos
    assert len({c.url.path for c in calls}) == 31
    relatorio = next(f for f in res["files"] if f.startswith("BCFT"))
    linhas = (tmp_path / relatorio).read_text(encoding="utf-8").splitlines()
    assert linhas[0].startswith("Relatório de clientes analisados")
    analisados = [l for l in linhas if " - " in l and "transações" in l]
    assert len(analisados) == 30 and all(l.startswith("PT") for l in analisados)
    com = [l for l in analisados if l.endswith("com transações")]
    assert len(FakeSMTP.sent) == len(com) + 1  # 1 email por cliente com transações + relatório
    csvs = [f for f in res["files"] if f.endswith(".csv")]
    rows = list(csv.reader((tmp_path / csvs[0]).open(encoding="utf-8-sig"), delimiter=";"))
    assert rows[0][-2:] == ["Opinião PBCFT", "Analista"] and rows[1][1] == "Pagamento MB"


def test_desempenho_fraudes(tmp_path):
    ev = [{"id": "e1", "customValues": {"MeioPagamento": "ReferenciaMultibanco", "Canal": "CaixaAutomatico"}},
          {"id": "e2", "customValues": {"MeioPagamento": "MbWay", "Canal": "MOBILE"}}]
    fr = [{"id": "f1", "customValues": {"MeioPagamento": "ReferenciaMultibanco"}}]
    counts = {"BancoEuro.CarMB1,BancoEuro.PagMB1": 200, "BancoEuro.pagamentombway": 50}

    def h(req):
        if "RegistoEventualFraude" in req.url.path:
            return httpx.Response(200, json=ev)
        if "RegistoFraudes" in req.url.path:
            return httpx.Response(200, json=fr)
        n = counts.get(req.url.params["transferTypes"], 0)
        return httpx.Response(200, json=[{"id": i} for i in range(n)])

    res, calls, _ = run_flow(tmp_path, "desempenho-fraudes-nativo.json", h)
    assert res["status"] == "SUCCEEDED", res
    assert len(calls) == 8
    lines = (tmp_path / res["files"][0]).read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("Dados de clientes recolhidos;Meio de pagamento")
    mb = lines[1].split(";")
    assert mb[1:5] == ["Referências multibanco", "200", "2", "0,0100"] and mb[5] == "1"  # canal caixa
    mbway = lines[3].split(";")
    assert mbway[2:5] == ["50", "1", "0,0200"] and mbway[9] == "1"  # canal mobile
    dd = lines[4].split(";")
    assert dd[2:5] == ["0", "0", "0,0000"]
    assert FakeSMTP.sent[0][1]["To"] == "ricardosilva@lusopay.com"
