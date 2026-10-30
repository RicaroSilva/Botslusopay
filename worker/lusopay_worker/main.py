"""Ponto de entrada do worker:  python -m lusopay_worker.main

Tem de correr na sessão interativa da conta Windows dedicada aos bots (o taskt
é uma aplicação WinForms e muitos bots usam o browser/teclado), por exemplo
através do Agendador de Tarefas com o gatilho "Ao iniciar sessão". Ver
docs/instalacao-windows.md."""
from __future__ import annotations

import logging
import signal
import time

from .client import BackendClient
from .config import WorkerConfig
from .runner import Runner
from .state import LocalState

log = logging.getLogger("lusopay_worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = WorkerConfig.from_env()
    client = BackendClient(cfg)
    runner = Runner(cfg, client, LocalState(cfg.state_file))
    stop = {"flag": False}

    def _stop(*_):
        stop["flag"] = True
        log.info("pedido de paragem: o worker termina após a execução em curso")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    runner.recover()
    log.info("worker iniciado; adaptadores=%s backend=%s", cfg.adapters, cfg.backend_url)
    while not stop["flag"]:
        try:
            job = client.claim(active_run_ids=[], capabilities=cfg.adapters)
        except Exception:
            log.exception("falha a pedir trabalho")
            job = None
        if job:
            log.info("execução %s (%s)", job["run_id"], job["bot_key"])
            try:
                runner.execute(job)
            except Exception:
                log.exception("erro inesperado na execução %s", job["run_id"])
            continue
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    main()
