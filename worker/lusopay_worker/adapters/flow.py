"""Adaptador de fluxos nativos: executa o fluxo num subprocesso Python
(lusopay_worker.flowengine), sem taskt/OpenBots nem desktop Windows."""
from __future__ import annotations

import base64
import hashlib
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
        # ficheiros persistentes: colocados na pasta da execução antes de começar
        initial: dict[str, str | None] = {}
        for name, content in (job.get("persistent_files") or {}).items():
            if "/" in name or "\\" in name or name.startswith(".") or ".." in name:
                raise AdapterRejected(f"nome de ficheiro persistente inválido: {name}")
            if content is None:
                initial[name] = None
                continue
            data = base64.b64decode(content)
            (out_dir / name).write_bytes(data)
            initial[name] = hashlib.sha256(data).hexdigest()
        ctx.extra["persistent_initial"] = initial
        payload = {
            "run_id": job["run_id"],
            "flow": job["flow"],
            "credentials": job.get("credentials") or {},
            "allowed_hosts": job.get("allowed_hosts") or [],
            "parameters": job.get("parameters") or {},
            "out_dir": str(out_dir),
            "dry_run": bool(job.get("dry_run")),
        }
        if job["flow"]["definition"].get("language") == "groovy":
            from ..groovy import GroovyUnavailable, Runtime, runtime

            try:
                rt = runtime()
            except GroovyUnavailable as exc:
                raise AdapterRejected(f"robô Groovy: {exc}") from exc
            payload["groovy"] = {"argv": rt.command("run", out_dir), "env": Runtime.env(out_dir)}
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
        persistent = set(ctx.extra.get("persistent_initial") or {})
        artifacts = [out_dir / f for f in result.get("files", []) if (out_dir / f).is_file() and f not in persistent]
        summary["files"] = [p.name for p in artifacts]
        if result.get("status") == "SUCCEEDED":
            return Outcome("SUCCEEDED", None, summary, artifacts)
        return Outcome("FAILED", "bot_reported_error", summary, artifacts)

    def persistent_updates(self, ctx: RunContext) -> list[tuple[str, bytes]]:
        if ctx.job.get("dry_run"):
            return []  # simulação: o estado guardado não muda
        out_dir: Path | None = ctx.extra.get("out_dir")
        updates = []
        for name, initial_sha in (ctx.extra.get("persistent_initial") or {}).items():
            path = out_dir / name if out_dir else None
            if path is None or not path.is_file():
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != initial_sha:
                updates.append((name, data))
        return updates

    def cleanup(self, ctx: RunContext) -> None:
        out_dir = ctx.extra.get("out_dir")
        if out_dir:
            shutil.rmtree(out_dir, ignore_errors=True)
