import os
from datetime import datetime

import pytest

from lusopay_worker import process
from lusopay_worker.adapters import AdapterRejected, RunContext, TasktCliAdapter
from lusopay_worker.adapters.base import sha256_file
from lusopay_worker.adapters.openbots import OpenBotsStudioAdapter
from conftest import make_script


def job(script, **kw):
    return {"run_id": "r1", "bot_key": "b", "adapter": "taskt_cli", "script": script, "timeout_seconds": 30,
            "parameters": {}, "success_detection": {"method": "taskt_log"}, **kw}


def run_taskt(cfg, j):
    a = TasktCliAdapter(cfg)
    ctx = RunContext(job=j)
    spec = a.prepare(ctx)
    ctx.started_at = datetime.now()
    p = process.start(spec.argv, spec.cwd)
    out = p.communicate(timeout=20)[0].decode()
    return a.evaluate(ctx, p.returncode, out), spec


@pytest.mark.parametrize("scenario,status,reason", [
    ("ok", "SUCCEEDED", None),
    ("error", "FAILED", "bot_reported_error"),
    ("cancel", "FAILED", "bot_reported_error"),
    ("nolog", "FAILED", "result_undetermined"),
    ("nested", "SUCCEEDED", None),
])
def test_taskt_outcomes(taskt_env, scenario, status, reason):
    make_script(taskt_env, "OK bot.xml", scenario)
    outcome, spec = run_taskt(taskt_env, job("OK bot.xml"))
    assert (outcome.status, outcome.failure_reason) == (status, reason)
    assert spec.argv[1].endswith("OK bot.xml") and len(spec.argv) == 2  # sem argumentos extra


def test_existing_log_content_is_ignored(taskt_env):
    # uma execução anterior bem-sucedida do mesmo script não pode contar
    make_script(taskt_env, "OK bot.xml", "ok")
    run_taskt(taskt_env, job("OK bot.xml"))
    make_script(taskt_env, "OK bot.xml", "nolog")
    outcome, _ = run_taskt(taskt_env, job("OK bot.xml"))
    assert outcome.failure_reason == "result_undetermined"


def test_cancelled_as_success_when_declared(taskt_env):
    make_script(taskt_env, "OK bot.xml", "cancel")
    j = job("OK bot.xml", success_detection={"method": "taskt_log", "taskt_cancelled_is_success": True})
    assert run_taskt(taskt_env, j)[0].status == "SUCCEEDED"


def test_handled_errors_warning_or_failure(taskt_env):
    make_script(taskt_env, "OK bot.xml", "handled")
    o, _ = run_taskt(taskt_env, job("OK bot.xml"))
    assert o.status == "SUCCEEDED" and o.result_summary["warnings"]
    j = job("OK bot.xml", success_detection={"method": "taskt_log", "fail_on_handled_errors": True})
    assert run_taskt(taskt_env, j)[0].status == "FAILED"


def test_success_check(taskt_env):
    make_script(taskt_env, "OK bot.xml", "ok")
    checks = {"method": "taskt_log", "checks": [{"type": "file_exists", "path": "Listas/out.csv"}]}
    o, _ = run_taskt(taskt_env, job("OK bot.xml", success_detection=checks))
    assert o.failure_reason == "success_check_failed"
    make_script(taskt_env, "OK bot.xml", "output")
    o, _ = run_taskt(taskt_env, job("OK bot.xml", success_detection=checks))
    assert o.status == "SUCCEEDED"


@pytest.mark.parametrize("script", ["../fora.xml", "..\\..\\fora.xml", "sub/../../fora.xml", "notas.txt", "nao-existe.xml"])
def test_rejects_bad_paths(taskt_env, script):
    (taskt_env.taskt_scripts_dir.parent / "fora.xml").write_text("x")
    (taskt_env.taskt_scripts_dir / "notas.txt").write_text("x")
    with pytest.raises(AdapterRejected):
        TasktCliAdapter(taskt_env).prepare(RunContext(job=job(script)))


def test_sha256_pin(taskt_env):
    p = make_script(taskt_env, "OK bot.xml", "ok")
    a = TasktCliAdapter(taskt_env)
    a.prepare(RunContext(job=job("OK bot.xml", expected_sha256=sha256_file(p))))
    with pytest.raises(AdapterRejected, match="alterado"):
        a.prepare(RunContext(job=job("OK bot.xml", expected_sha256="0" * 64)))


def test_parameters_rejected(taskt_env):
    make_script(taskt_env, "OK bot.xml")
    with pytest.raises(AdapterRejected):
        TasktCliAdapter(taskt_env).prepare(RunContext(job=job("OK bot.xml", parameters={"x": 1})))


def test_missing_exe(taskt_env):
    make_script(taskt_env, "OK bot.xml")
    taskt_env.taskt_exe = taskt_env.taskt_scripts_dir / "nao.exe"
    with pytest.raises(AdapterRejected):
        TasktCliAdapter(taskt_env).prepare(RunContext(job=job("OK bot.xml")))


def test_openbots_refuses_until_validated(taskt_env):
    with pytest.raises(AdapterRejected, match="não validado"):
        OpenBotsStudioAdapter(taskt_env).prepare(RunContext(job=job("x/project.obconfig")))
