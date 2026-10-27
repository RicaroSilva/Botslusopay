import textwrap

import pytest
from pydantic import ValidationError

from botmanager.models import Availability, Bot
from botmanager.registry.loader import load_registry, sync_registry
from botmanager.registry.schema import BotDefinition, ParameterError, validate_parameters

BASE = {"key": "abc-bot", "name": "x", "execution": {"adapter": "simulated", "script": "demo"}}


def defn(**over):
    d = {**BASE, **over}
    return BotDefinition.model_validate(d)


def test_minimal_valid():
    d = defn()
    assert d.concurrency.policy == "single"
    assert d.triggers_allowed == ["manual"]


@pytest.mark.parametrize("script", ["..\\..\\Windows\\cmd.exe", "C:\\x.xml", "/etc/passwd", "a/../../b.xml"])
def test_rejects_unsafe_paths(script):
    with pytest.raises(ValidationError):
        defn(execution={"adapter": "taskt_cli", "script": script})


def test_rejects_unknown_adapter_and_fields():
    with pytest.raises(ValidationError):
        defn(execution={"adapter": "powershell", "script": "x"})
    with pytest.raises(ValidationError):
        defn(command="rm -rf /")


def test_high_risk_requires_approval():
    with pytest.raises(ValidationError):
        defn(risk_level="high")
    assert defn(risk_level="high", requires_approval=True).requires_approval


def test_taskt_rejects_parameters():
    with pytest.raises(ValidationError):
        defn(execution={"adapter": "taskt_cli", "script": "x.xml"},
             parameters=[{"name": "p", "type": "string"}])


def test_taskt_rejects_exit_code_success():
    with pytest.raises(ValidationError):
        defn(execution={"adapter": "taskt_cli", "script": "x.xml"}, success_detection={"method": "exit_code"})


def test_auto_retry_requires_idempotent():
    with pytest.raises(ValidationError):
        defn(retry={"automatic": True})


def test_parameter_validation():
    d = defn(parameters=[{"name": "d", "type": "date", "required": True},
                         {"name": "n", "type": "integer", "min": 1, "max": 5},
                         {"name": "s", "type": "string", "pattern": "[A-Z]{3}", "sensitive": True}])
    clean, public = validate_parameters(d, {"d": "2026-01-31", "n": 3, "s": "ABC"})
    assert clean["s"] == "ABC" and "s" not in public
    for bad in ({"n": 3}, {"d": "31/01/2026"}, {"d": "2026-01-01", "n": 9}, {"d": "2026-01-01", "s": "abc"},
                {"d": "2026-01-01", "x": 1}, {"d": "2026-01-01", "n": True}):
        with pytest.raises(ParameterError):
            validate_parameters(d, bad)


def test_real_registry_is_valid():
    from botmanager.config import REPO_ROOT

    res = load_registry([REPO_ROOT / "bots" / "registry", REPO_ROOT / "bots" / "registry-dev"])
    assert res.errors == {}
    keys = {d.key for d in res.definitions}
    assert {"taskt-smoke-config", "cyclos-recolher-ids"} <= keys
    # nenhum bot real é dado como validado antes de ser testado no servidor
    assert all(not d.execution.validated for d in res.definitions if d.execution.adapter != "simulated")


def test_sync_new_bots_disabled_and_removed_bots_disabled(env, tmp_path):
    db = env["db"]
    reg = tmp_path / "reg2"
    reg.mkdir()
    (reg / "n.yaml").write_text(textwrap.dedent("""
        key: new-bot
        name: Novo
        execution: {adapter: simulated, script: demo, validated: true}
    """), encoding="utf-8")
    sync_registry(db, [reg])
    new = db.query(Bot).filter_by(key="new-bot").one()
    assert new.enabled is False and new.availability == Availability.AVAILABLE
    old = db.query(Bot).filter_by(key="low-bot").one()
    assert old.in_registry is False and old.enabled is False


def test_invalid_file_reported_not_loaded(env, tmp_path):
    reg = tmp_path / "bad"
    reg.mkdir()
    (reg / "bad.yaml").write_text("key: BAD KEY\nname: x\n", encoding="utf-8")
    res = load_registry([reg])
    assert "bad.yaml" in res.errors and not res.definitions


def test_unvalidated_bot_cannot_be_made_available(clients):
    r = clients["admin"].patch("/api/admin/bots/unvalidated-bot", json={"availability": "available"})
    assert r.status_code == 409


def test_disabled_bot_cannot_run(clients):
    clients["admin"].patch("/api/admin/bots/low-bot", json={"enabled": False, "reason": "manutenção"})
    from conftest import run_bot

    r = run_bot(clients["operator"], "low-bot")
    assert r.status_code == 409 and r.json()["code"] == "bot_unavailable"
