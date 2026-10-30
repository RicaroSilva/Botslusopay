"""Execução supervisionada de um trabalho: lançamento, heartbeat, logs,
timeout, cancelamento e determinação do resultado."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from . import process
from .adapters import ADAPTERS, AdapterRejected, RunContext
from .client import BackendClient
from .config import WorkerConfig
from .redaction import redact_text
from .state import LocalState

log = logging.getLogger("lusopay_worker.runner")
MAX_OUTPUT_CHARS = 200_000


def _content_type(path) -> str:
    return {".csv": "text/csv", ".json": "application/json", ".txt": "text/plain"}.get(
        path.suffix.lower(), "application/octet-stream")


class RunLogger:
    def __init__(self, cfg: WorkerConfig):
        self.cfg = cfg
        self.extra_secrets: list[str] = []
        self.seq = 0
        self.pending: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def add(self, message: str, level: str = "INFO", source: str = "worker") -> None:
        with self.lock:
            self.seq += 1
            self.pending.append({
                "seq": self.seq,
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "source": source,
                "message": redact_text(message, [*self.cfg.extra_redactions, *self.extra_secrets])[:8000],
            })

    def drain(self) -> list[dict[str, Any]]:
        with self.lock:
            out, self.pending = self.pending, []
            return out


class Runner:
    def __init__(self, cfg: WorkerConfig, client: BackendClient, state: LocalState):
        self.cfg = cfg
        self.client = client
        self.state = state

    # ------------------------------------------------------------------ arranque

    def recover(self) -> None:
        """Chamado no arranque, antes de pedir trabalho."""
        st = self.state.load()
        pending = st.get("pending_completion")
        if pending:
            try:
                self.client.complete(pending["run_id"], pending["payload"])
                log.info("conclusão pendente de %s reenviada", pending["run_id"])
            except Exception:  # o backend tratará a execução como perdida
                log.exception("não foi possível reenviar a conclusão pendente")
        pid = st.get("pid")
        if pid and not pending and process.is_alive(int(pid)):
            log.warning("processo órfão %s da execução %s: a terminar (já não é supervisionado)", pid, st.get("run_id"))
            process.kill_tree(int(pid))
        self.state.clear()

    # ------------------------------------------------------------------ execução

    def _send_logs(self, run_id: str, logger: RunLogger) -> None:
        entries = logger.drain()
        if entries:
            try:
                self.client.logs(run_id, entries)
            except Exception:
                log.exception("falha a enviar logs")
                with logger.lock:
                    logger.pending = entries + logger.pending

    def _finish(self, run_id: str, logger: RunLogger, payload: dict[str, Any]) -> None:
        self.state.save({**self.state.load(), "pending_completion": {"run_id": run_id, "payload": payload}})
        self._send_logs(run_id, logger)
        # Se o envio falhar (exceção), a conclusão fica pendente no estado local
        # e é reenviada no próximo arranque (recover).
        self.client.complete(run_id, payload)
        self.state.clear()

    def execute(self, job: dict[str, Any]) -> dict[str, Any]:
        run_id = job["run_id"]
        logger = RunLogger(self.cfg)
        logger.add(f"Worker recebeu a execução do bot {job['bot_key']} (adaptador {job['adapter']})")
        adapter_cls = ADAPTERS.get(job["adapter"])
        if adapter_cls is None or job["adapter"] not in self.cfg.adapters:
            logger.add(f"Adaptador {job['adapter']} não autorizado neste worker", "ERROR")
            payload = {"status": "FAILED", "failure_reason": "worker_rejected", "process_started": False}
            self._finish(run_id, logger, payload)
            return payload
        adapter = adapter_cls(self.cfg)
        ctx = RunContext(job=job)
        logger.extra_secrets = adapter.secrets(ctx)
        try:
            return self._execute(job, run_id, logger, adapter, ctx)
        finally:
            adapter.cleanup(ctx)

    def _execute(self, job, run_id, logger, adapter, ctx) -> dict[str, Any]:
        try:
            spec = adapter.prepare(ctx)
        except AdapterRejected as exc:
            logger.add(f"Execução recusada antes de iniciar: {exc}", "ERROR")
            payload = {"status": "FAILED", "failure_reason": "worker_rejected", "process_started": False,
                       "result_summary": {"reason": str(exc)}}
            self._finish(run_id, logger, payload)
            return payload

        ctx.started_at = datetime.now()
        try:
            proc = process.start(spec.argv, spec.cwd, spec.stdin_data, spec.env)
        except OSError as exc:
            logger.add(f"Erro ao iniciar o processo: {exc}", "ERROR")
            payload = {"status": "FAILED", "failure_reason": "launch_error", "process_started": False}
            self._finish(run_id, logger, payload)
            return payload
        self.state.save({"run_id": run_id, "pid": proc.pid, "started_at": ctx.started_at.isoformat()})
        logger.add(f"Processo iniciado (pid {proc.pid}); timeout {job['timeout_seconds']}s")
        adapter.on_started(ctx)

        output_parts: list[str] = []
        out_len = [0]

        def pump():
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip()
                if out_len[0] < MAX_OUTPUT_CHARS or line.startswith("@@RESULT "):
                    output_parts.append(line)
                    out_len[0] += len(line)
                if line.startswith("@@RESULT "):
                    continue  # linha técnica de resultado, não é mostrada nos logs
                level = "INFO"
                for lv in ("ERROR", "WARNING"):
                    if line.startswith(lv + " "):
                        level, line = lv, line[len(lv) + 1:]
                logger.add(line, level=level, source="process")

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()

        deadline = time.monotonic() + float(job["timeout_seconds"])
        next_hb = 0.0
        outcome_override: dict[str, Any] | None = None
        while proc.poll() is None:
            now = time.monotonic()
            if now >= deadline:
                logger.add("Timeout excedido: a terminar a árvore de processos", "ERROR")
                process.kill_tree(proc.pid)
                outcome_override = {"status": "FAILED", "failure_reason": "timeout"}
                break
            if now >= next_hb:
                next_hb = now + self.cfg.heartbeat_seconds
                for line in adapter.progress_lines(ctx):
                    logger.add(line, source="runtime")
                self._send_logs(run_id, logger)
                try:
                    hb = self.client.heartbeat(run_id)
                except Exception:
                    log.exception("heartbeat falhou")
                    hb = {}
                if hb.get("cancel_requested"):
                    logger.add("Cancelamento pedido: a terminar a árvore de processos", "WARNING")
                    process.kill_tree(proc.pid)
                    outcome_override = {"status": "CANCELLED", "failure_reason": None}
                    break
            time.sleep(0.2)
        try:
            exit_code = proc.wait(timeout=self.cfg.kill_grace_seconds)
        except Exception:
            process.kill_tree(proc.pid)
            exit_code = None
        reader.join(timeout=5)
        for line in adapter.progress_lines(ctx):
            logger.add(line, source="runtime")

        if outcome_override:
            payload = {**outcome_override, "exit_code": exit_code, "process_started": True,
                       "result_summary": {"note": "processo terminado pelo worker"}}
        else:
            outcome = adapter.evaluate(ctx, exit_code, "\n".join(output_parts))
            payload = {"status": outcome.status, "failure_reason": outcome.failure_reason, "exit_code": exit_code,
                       "process_started": True, "result_summary": outcome.result_summary}
            for path in outcome.artifacts:
                try:
                    self.client.upload_artifact(run_id, path.name, path.read_bytes(), _content_type(path))
                    logger.add(f"Ficheiro guardado: {path.name} ({path.stat().st_size} bytes)")
                except Exception as exc:  # o resultado do bot não muda por falhar o envio
                    logger.add(f"Não foi possível guardar o ficheiro {path.name}: {exc}", "WARNING")
        # Ficheiros persistentes (controlo): gravados mesmo que a execução tenha falhado ou sido
        # interrompida, porque refletem o trabalho já feito nos sistemas externos.
        for name, data in adapter.persistent_updates(ctx):
            try:
                self.client.save_persistent(run_id, name, data)
                logger.add(f"Ficheiro persistente atualizado: {name} ({len(data)} bytes)")
            except Exception as exc:
                logger.add(f"NÃO foi possível gravar o ficheiro persistente {name}: {exc}", "ERROR")
                payload = {**payload, "status": "FAILED", "failure_reason": "result_undetermined",
                           "result_summary": {**(payload.get("result_summary") or {}),
                                              "reason": f"ficheiro de controlo {name} não gravado; verificar antes de repetir"}}
        level = "INFO" if payload["status"] == "SUCCEEDED" else "ERROR"
        logger.add(f"Resultado: {payload['status']}" + (f" ({payload['failure_reason']})" if payload.get("failure_reason") else ""), level)
        self._finish(run_id, logger, payload)
        return payload
