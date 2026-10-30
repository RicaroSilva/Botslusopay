import pytest

from botmanager.security.redaction import REDACTED, redact_obj, redact_text


@pytest.mark.parametrize("text,secret", [
    ("Authorization: Basic ZXhlbXBsbzpuYW8tZS1yZWFsLTEyMw==", "ZXhlbXBsbzpuYW8tZS1yZWFsLTEyMw=="),
    ("Bearer eyJhbGciOiJIUzI1NiJ9.abc.def", "eyJhbGciOiJIUzI1NiJ9.abc.def"),
    ("Data Source=1.2.3.4;User ID=x;Password=Sup3rS3cr3t;", "Sup3rS3cr3t"),
    ('v_SMTPPassword="Kx9-pass"', "Kx9-pass"),
    ("RPATaskt,QmFzaWMgeHl6,Server,srv1,", "QmFzaWMgeHl6"),
    ("smtpPass,minha-pass,smtpPort,587,", "minha-pass"),
    ("https://user:pa55@host/x", "pa55"),
    ("senha=abc12345", "abc12345"),
    ('{"token": "tok_123456"}', "tok_123456"),
])
def test_patterns(text, secret):
    out = redact_text(text)
    assert secret not in out and REDACTED in out


def test_keeps_normal_text():
    t = "Script Path: C:\\taskt\\OK Saldos.xml — Result Code: Successful"
    assert redact_text(t) == t


def test_extra_secrets_and_objects():
    obj = {"password": "x", "nested": [{"api_key": "y"}, "valor segredo-muito-especifico"], "n": 1}
    out = redact_obj(obj, ["segredo-muito-especifico"])
    assert out["password"] == REDACTED and out["nested"][0]["api_key"] == REDACTED
    assert "segredo-muito-especifico" not in out["nested"][1] and out["n"] == 1


def test_audit_details_redacted(env, clients):
    from botmanager.services.audit import audit

    db = env["db"]
    ev = audit(db, "system", "t", "x", "y", None, details={"msg": "Authorization: Basic QUJDREVGR0hJSktM", "pwd": "1"})
    db.commit()
    assert "QUJDREVGR0hJSktM" not in str(ev.details) and ev.details["pwd"] == REDACTED


def test_worker_token_not_stored_in_clear(env, clients):
    r = clients["admin"].post("/api/admin/workers", json={"name": "BOTSERVER9", "capabilities": ["taskt_cli"]})
    token = r.json()["token"]
    from botmanager.models import Worker

    w = env["db"].query(Worker).filter_by(name="BOTSERVER9").one()
    assert token not in w.token_hash
    assert "token" not in str(clients["admin"].get("/api/admin/workers").json())


def test_api_never_returns_registry_secrets(clients):
    body = clients["admin"].get("/api/admin/bots").text.lower()
    assert "password" not in body and "authorization" not in body
