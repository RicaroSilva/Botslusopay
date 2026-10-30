from __future__ import annotations

import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from lusopay_worker.config import WorkerConfig

ROOT = Path(__file__).resolve().parents[2]

FAKE_TASKT = r'''#!{python}
"""taskt.exe FALSO para testes: escreve no log como o motor taskt (Serilog) e termina.
O comportamento é controlado por uma linha "# FAKE: <cenário>" no XML."""
import sys, time, datetime, pathlib, re
script = pathlib.Path(sys.argv[1])
logs = pathlib.Path({logs!r})
text = script.read_text(encoding="utf-8")
m = re.search(r"FAKE: (\w+)", text)
scenario = m.group(1) if m else "ok"
def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " +00:00"
path = logs / ("taskt Engine Logs" + datetime.date.today().strftime("%Y%m%d") + ".txt")
child = logs / ("taskt Engine Logs" + datetime.date.today().strftime("%Y%m%d") + "_001.txt")
def w(line, p=path):
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(f"{{ts()}} [INF] {{line}}\n")
    time.sleep(0.002)
w("Engine Class has been initialized")
w("Client requesting to execute script using frmEngine")
w("Bot Engine Started: now")
w("Deserializing File")
w(f"Script Path: {{script}}")
w("Running Line 1: Comment")
if scenario == "nested":
    w("Engine Class has been initialized", child)
    w(f"Script Path: {{script.parent / 'Ok Recolha das Configurações.xml'}}", child)
    w("Result Code: Successful", child)
    w("Error: None", child)
    w("Running Line 2: Run Task")
if scenario == "handled":
    w("Error Occured at Line 7:System.Exception: boom")
    w("Continuing Per Error Handling")
if scenario == "hang":
    time.sleep(3600)
if scenario == "nolog":
    sys.exit(0)
result = {{"error": "Error", "cancel": "Cancelled"}}.get(scenario, "Successful")
w(f"Result Code: {{result}}")
w("Error: " + ("System.Exception: falhou na linha 3" if scenario == "error" else "None"))
if scenario == "output":
    out = script.parent / "Listas" / "out.csv"
    out.parent.mkdir(exist_ok=True)
    out.write_text("x")
'''


@pytest.fixture()
def taskt_env(tmp_path):
    scripts = tmp_path / "taskt" / "My Scripts"
    logs = tmp_path / "taskt" / "Logs"
    scripts.mkdir(parents=True)
    logs.mkdir(parents=True)
    exe = tmp_path / "taskt.exe"
    exe.write_text(FAKE_TASKT.format(python=sys.executable, logs=str(logs)), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    cfg = WorkerConfig(backend_url="http://test", token="t", adapters=["taskt_cli", "simulated"], taskt_exe=exe,
                       taskt_scripts_dir=scripts, taskt_logs_dir=logs, state_file=tmp_path / "state.json",
                       heartbeat_seconds=0.2, poll_seconds=0.1, kill_grace_seconds=2)
    return cfg


def make_script(cfg: WorkerConfig, name: str, scenario: str = "ok") -> Path:
    p = cfg.taskt_scripts_dir / name
    p.write_text(f'<?xml version="1.0"?>\n<Script><!-- FAKE: {scenario} --></Script>\n', encoding="utf-8")
    return p
