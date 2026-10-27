"""Adaptador de fluxos nativos: executa o fluxo num subprocesso Python
(lusopay_worker.flowengine), sem taskt/OpenBots nem desktop Windows."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from ..flowengine import RESULT_PREFIX
from .base import Adapter, AdapterRejected, LaunchSpec, Outcome, RunContext


class FlowAdapter(Adapter):
    name = "flow"

    def prepare(self, ctx: RunContext) -> LaunchSpec:
        job = ctx.job
        if not job.get("flow") or not job["flow"].get("definition"):
            raise AdapterRejected("trabalho sem definição de fluxo")
        out_dir = Path(tempfile.mkdtemp(prefix=f"bm-{job['run_id'][:12]}-"))
        ctx.extra["out_dir"] = out_dir
        payload = {
            "run_id": job["run_id"],
            "flow": job["flow"],
            "credentials": job.get("credentials") or {},
            "allowed_hosts": job.get("allowed_hosts") or [],
            "parameters": job.get("parameters") or {},
            "out_dir": str(out_dir),
        }
        # garante que o subprocesso encontra este pacote mesmo sem instalação via pip
        pkg_root = str(Path(__file__).resolve().parents[2])
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [pkg_root, os.environ.get("PYTHONPATH")])),
               "PYTHONIOENCODING": "utf-8"}
        return LaunchSpec(argv=[sys.executable, "-u", "-m", "lusopay_worker.flowengine"], cwd=out_dir,
                          stdin_data=json.dumps(payload).encode(), env=env)

    def secrets(self, ctx: RunContext) -> list[str]:
        out = []
        for c in (ctx.job.get("credentials") or {}).values():
            out += [str(v) for k, v in c.items() if k in ("password", "token", "value") and v]
        return out

    def evaluate(self, ctx: RunContext, exit_code: int | None, output: str) -> Outcome:
        result = None
        for line in reversed(output.splitlines()):
            if line.startswith(RESULT_PREFIX):
                try:
                    result = json.loads(line[len(RESULT_PREFIX):])
                except ValueError:
                    pass
                break
        summary = {"runtime": "flow", "flow_version": ctx.job["flow"].get("version"), "exit_code": exit_code}
        if result is None:
            summary["reason"] = "o motor de fluxos terminou sem resultado (falha inesperada)"
            return Outcome("FAILED", "result_undetermined", summary)
        summary.update({k: result.get(k) for k in ("counters", "duration_seconds", "stopped", "failed_step", "error")
                        if result.get(k) is not None})
        out_dir: Path = ctx.extra["out_dir"]
        artifacts = [out_dir / f for f in result.get("files", []) if (out_dir / f).is_file()]
        summary["files"] = [p.name for p in artifacts]
        if result.get("status") == "SUCCEEDED":
            return Outcome("SUCCEEDED", None, summary, artifacts)
        return Outcome("FAILED", "bot_reported_error", summary, artifacts)

    def cleanup(self, ctx: RunContext) -> None:
        out_dir = ctx.extra.get("out_dir")
        if out_dir:
            shutil.rmtree(out_dir, ignore_errors=True)
