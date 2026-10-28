"""Integração completa de um fluxo nativo: backend (API) → worker → subprocesso
do motor → servidor HTTPS local (certificado de teste) → CSV guardado no backend."""
from __future__ import annotations

import datetime as dt
import json
import ssl
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from test_integration import stack  # noqa: F401  (fixture do backend em processo)

SEEN: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        SEEN.append({"path": self.path, "auth": self.headers.get("Authorization")})
        body = json.dumps([{"id": 1, "amount": "10.5"}, {"id": 2, "amount": "7"}]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def https_server(tmp_path, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cert_pem, key_pem = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    srv = HTTPServer(("localhost", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_pem, key_pem)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("SSL_CERT_FILE", str(cert_pem))  # o subprocesso do motor confia no certificado de teste
    SEEN.clear()
    yield srv.server_address[1]
    srv.shutdown()


def test_native_flow_end_to_end(stack, https_server):  # noqa: F811
    from fastapi.testclient import TestClient

    from botmanager.models import Role, User, Worker
    from botmanager.security.passwords import hash_password

    db = stack["db"]
    db.add(User(username="admin", role=Role.ADMIN, password_hash=hash_password("correct-horse-battery")))
    w = db.query(Worker).filter_by(name="w").one()
    w.capabilities = ["flow"]
    db.commit()
    stack["cfg"].adapters = ["flow"]
    admin = TestClient(stack["user"].app)
    admin.post("/api/auth/login", json={"username": "admin", "password": "correct-horse-battery"})
    admin.headers["X-Requested-With"] = "botmanager"

    assert admin.post("/api/admin/credentials", json={
        "name": "cyclos-dev", "kind": "http_basic",
        "fields": {"username": "cliente7", "password": "pass-de-teste-secreta"}}).status_code == 201
    flow = {"steps": [
        {"id": "tx", "type": "http_request", "url": f"https://localhost:{https_server}/web_dev/api/transactions",
         "credential": "cyclos-dev", "save_as": "transacoes"},
        {"id": "csv", "type": "csv_write", "file": "transacoes.csv", "rows_expr": "transacoes",
         "columns": [{"header": "ID", "value": "{{ row.id }}"}, {"header": "Valor", "value": "{{ row.amount | money }}"}]},
        {"id": "fim", "type": "log", "message": "{{ transacoes | length }} transações exportadas"},
    ]}
    r = admin.post("/api/flows", json={"key": "transacoes-dev", "name": "Transações dev", "risk_level": "low",
                                       "definition": flow})
    assert r.status_code == 201, r.text
    admin.patch("/api/admin/bots/transacoes-dev", json={"enabled": True})
    rid = stack["user"].post("/api/bots/transacoes-dev/run",
                             json={"parameters": {}, "idempotency_key": uuid.uuid4().hex}).json()["run_id"]

    job = stack["client"].claim([], ["flow"])
    payload = stack["runner"].execute(job)
    run = stack["user"].get(f"/api/runs/{rid}").json()
    logs0 = stack["user"].get(f"/api/runs/{rid}/logs").json()["lines"]
    assert run["status"] == "SUCCEEDED", [l["message"] for l in logs0]
    assert run["result_summary"]["counters"]["http_requests"] == 1
    assert SEEN[0]["path"] == "/web_dev/api/transactions" and SEEN[0]["auth"].startswith("Basic ")

    logs = stack["user"].get(f"/api/runs/{rid}/logs").json()["lines"]
    text = "\n".join(l["message"] for l in logs)
    assert "2 transações exportadas" in text and "→ 200" in text
    assert "pass-de-teste-secreta" not in text and "@@RESULT" not in text

    arts = stack["user"].get(f"/api/runs/{rid}/artifacts").json()
    assert [a["name"] for a in arts] == ["transacoes.csv"]
    content = stack["user"].get(f"/api/runs/{rid}/artifacts/{arts[0]['id']}").content.decode("utf-8-sig")
    assert content.splitlines() == ["ID;Valor", "1;10,50", "2;7,00"]


def test_persistent_control_file_saved_even_when_flow_fails(stack):  # noqa: F811
    import base64

    from fastapi.testclient import TestClient

    from botmanager.models import Role, User, Worker
    from botmanager.security.passwords import hash_password

    db = stack["db"]
    db.add(User(username="admin", role=Role.ADMIN, password_hash=hash_password("correct-horse-battery")))
    w = db.query(Worker).filter_by(name="w").one()
    w.capabilities = ["flow"]
    db.commit()
    stack["cfg"].adapters = ["flow"]
    admin = TestClient(stack["user"].app)
    admin.post("/api/auth/login", json={"username": "admin", "password": "correct-horse-battery"})
    admin.headers["X-Requested-With"] = "botmanager"
    ctl = "ultimo id processado.txt"
    flow = {"persistent_files": [ctl], "steps": [
        {"id": "ler", "type": "text_read", "file": ctl, "save_as": "ultimo", "missing_ok": True},
        {"id": "ciclo", "type": "foreach", "items_expr": "range((ultimo | int) + 1, (ultimo | int) + 4)",
         "item_variable": "n", "steps": [
             {"id": "grava", "type": "text_write", "file": ctl, "content": "{{ n }}"},
             {"id": "para", "type": "if", "condition": "n == (ultimo | int) + 2",
              "then": [{"id": "erro", "type": "fail", "message": "falha a meio"}]}]},
    ]}
    assert admin.post("/api/flows", json={"key": "controlo", "name": "Controlo", "risk_level": "low",
                                          "definition": flow}).status_code == 201
    admin.patch("/api/admin/bots/controlo", json={"enabled": True})
    url = f"/api/flows/controlo/files/{ctl}"
    assert admin.put(url, json={"content_b64": base64.b64encode(b"41").decode()}).status_code == 200
    rid = stack["user"].post("/api/bots/controlo/run",
                             json={"parameters": {}, "idempotency_key": uuid.uuid4().hex}).json()["run_id"]
    stack["runner"].execute(stack["client"].claim([], ["flow"]))
    run = stack["user"].get(f"/api/runs/{rid}").json()
    assert run["status"] == "FAILED"
    # o último id efetivamente escrito (43) ficou gravado, apesar da falha
    assert admin.get(url).content == b"43"
    assert admin.get(url, params={"previous": True}).content == b"41"
    assert stack["user"].get(f"/api/runs/{rid}/artifacts").json() == []
    text = "\n".join(l["message"] for l in stack["user"].get(f"/api/runs/{rid}/logs").json()["lines"])
    assert f"Ficheiro persistente atualizado: {ctl}" in text
