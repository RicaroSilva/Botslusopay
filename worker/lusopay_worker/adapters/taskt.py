"""Adaptador taskt: lança 'taskt.exe <script.xml>' (mecanismo confirmado no
código-fonte do taskt; a versão instalada tem de ser validada no servidor)."""
from __future__ import annotations

from ..tasktlog import LogTailer, parse_result
from .base import Adapter, AdapterRejected, LaunchSpec, Outcome, RunContext, run_success_checks, safe_join, sha256_file


class TasktCliAdapter(Adapter):
    name = "taskt_cli"

    def prepare(self, ctx: RunContext) -> LaunchSpec:
        exe = self.cfg.taskt_exe
        if exe is None or not exe.is_file():
            raise AdapterRejected("WORKER_TASKT_EXE não configurado ou inexistente")
        if self.cfg.taskt_logs_dir is None or not self.cfg.taskt_logs_dir.is_dir():
            raise AdapterRejected("pasta de logs do taskt não encontrada (WORKER_TASKT_LOGS_DIR)")
        script = safe_join(self.cfg.taskt_scripts_dir, ctx.job["script"], (".xml",))
        expected = ctx.job.get("expected_sha256")
        if expected:
            actual = sha256_file(script)
            if actual != expected:
                raise AdapterRejected(
                    f"o ficheiro do script foi alterado (sha256 {actual[:12]}… ≠ registo {expected[:12]}…); "
                    "rever e atualizar a definição do bot"
                )
        if ctx.job.get("parameters"):
            raise AdapterRejected("taskt não aceita parâmetros pela linha de comandos")
        ctx.script_path = script
        tailer = LogTailer(self.cfg.taskt_logs_dir)
        tailer.snapshot()
        ctx.extra["tailer"] = tailer
        # cwd = pasta do script: alguns scripts usam caminhos relativos
        return LaunchSpec(argv=[str(exe), str(script)], cwd=script.parent)

    def progress_lines(self, ctx: RunContext) -> list[str]:
        return ctx.extra["tailer"].read_new()

    def evaluate(self, ctx: RunContext, exit_code: int | None, output: str) -> Outcome:
        tailer: LogTailer = ctx.extra["tailer"]
        tailer.read_new()
        detection = ctx.job.get("success_detection") or {}
        res = parse_result(tailer.lines, ctx.script_path)
        summary = {
            "runtime": "taskt",
            "runtime_result": res.result_code,
            "exit_code_note": "o taskt não devolve código de saída significativo",
            "nested_scripts": res.nested_scripts[:50],
            "runtime_errors": res.errors[:10],
            "handled_errors_at_lines": res.handled_error_lines[:50],
        }
        if res.result_code is None:
            summary["reason"] = res.reason
            return Outcome("FAILED", "result_undetermined", summary)
        if res.result_code == "Error":
            return Outcome("FAILED", "bot_reported_error", summary)
        if res.result_code == "Cancelled" and not detection.get("taskt_cancelled_is_success"):
            summary["reason"] = "o taskt terminou com Cancelled (Stop Task ou cancelamento)"
            return Outcome("FAILED", "bot_reported_error", summary)
        if res.result_code not in ("Successful", "Cancelled"):
            summary["reason"] = f"Result Code desconhecido: {res.result_code}"
            return Outcome("FAILED", "result_undetermined", summary)
        if res.handled_error_lines:
            summary["warnings"] = [f"{len(res.handled_error_lines)} erro(s) ignorados por 'Continue Processing'"]
            if detection.get("fail_on_handled_errors"):
                return Outcome("FAILED", "bot_reported_error", summary)
        failures = run_success_checks(ctx.job, self.cfg.taskt_scripts_dir, ctx)
        if failures:
            summary["success_check_failures"] = failures
            return Outcome("FAILED", "success_check_failed", summary)
        return Outcome("SUCCEEDED", None, summary)
