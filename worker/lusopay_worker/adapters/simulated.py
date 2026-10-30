"""Adaptador SIMULADO para desenvolvimento e testes do Bot Manager.

Lança um processo Python real (para exercitar timeouts, cancelamento e
terminação de processos), mas não executa nenhum bot. Um sucesso aqui não
prova que qualquer bot real funcione."""
from __future__ import annotations

import sys

from .base import Adapter, AdapterRejected, LaunchSpec, Outcome, RunContext

SCENARIOS = {
    "demo": "import time\nfor i in range(3):\n    print(f'passo {i+1}/3', flush=True); time.sleep(0.2)\nprint('RESULT=OK')",
    "demo-high": "print('operação simulada com efeitos'); print('RESULT=OK')",
    "demo-fail": "print('a falhar'); print('RESULT=ERROR'); raise SystemExit(0)",
    "demo-exit": "raise SystemExit(3)",
    "demo-hang": "import time\nprint('bloqueado (ex.: MessageBox)', flush=True)\ntime.sleep(3600)",
    "demo-secret": "print('Authorization: Basic ZXhlbXBsbzpzZWdyZWRv')\nprint('RESULT=OK')",
}


class SimulatedAdapter(Adapter):
    name = "simulated"

    def prepare(self, ctx: RunContext) -> LaunchSpec:
        code = SCENARIOS.get(ctx.job["script"])
        if code is None:
            raise AdapterRejected(f"cenário simulado desconhecido: {ctx.job['script']}")
        return LaunchSpec(argv=[sys.executable, "-u", "-c", code])

    def evaluate(self, ctx: RunContext, exit_code: int | None, output: str) -> Outcome:
        summary = {"runtime": "simulated", "simulated": True, "exit_code": exit_code}
        if exit_code != 0:
            return Outcome("FAILED", "exit_code", summary)
        if "RESULT=OK" in output:
            return Outcome("SUCCEEDED", None, summary)
        if "RESULT=ERROR" in output:
            return Outcome("FAILED", "bot_reported_error", summary)
        return Outcome("FAILED", "result_undetermined", summary)
