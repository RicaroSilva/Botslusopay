"""Scheduler: processo separado que avalia regras periódicas (cron, polling)
e recolhe execuções sem heartbeat.

Só uma instância fica ativa (lease na tabela scheduler_leases); outras ficam
em espera. Executar:  python -m botmanager.scheduler
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import session_factory
from .models import SchedulerLease, TriggerRule, utcnow
from .services.runs import reap_stale_runs
from .services.settings import triggers_paused
from .triggers import TRIGGER_TYPES

log = logging.getLogger("botmanager.scheduler")
LEASE_NAME = "scheduler"


def acquire_lease(db: Session, holder: str, ttl_seconds: int, now: datetime | None = None) -> bool:
    now = now or utcnow()
    lease = db.get(SchedulerLease, LEASE_NAME)
    if lease is None:
        try:
            with db.begin_nested():
                db.add(SchedulerLease(name=LEASE_NAME, holder=holder, expires_at=now + timedelta(seconds=ttl_seconds)))
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False
    if lease.holder == holder or lease.expires_at < now:
        lease.holder = holder
        lease.expires_at = now + timedelta(seconds=ttl_seconds)
        db.commit()
        return True
    return False


def tick(db: Session, now: datetime | None = None) -> dict:
    """Uma iteração do scheduler (também usada nos testes)."""
    now = now or utcnow()
    summary = {"reaped": reap_stale_runs(db, now), "fired": []}
    db.commit()
    if triggers_paused(db):
        return summary
    periodic = [name for name, t in TRIGGER_TYPES.items() if t.periodic]
    rules = list(db.scalars(select(TriggerRule).where(TriggerRule.enabled.is_(True),
                                                       TriggerRule.trigger_type.in_(periodic))))
    for rule in rules:
        ttype = TRIGGER_TYPES[rule.trigger_type]
        try:
            results = ttype.evaluate(db, rule, now)
            db.commit()
        except Exception:  # uma regra com erro não pára as restantes
            db.rollback()
            log.exception("erro ao avaliar regra %s", rule.id)
            continue
        summary["fired"].extend((rule.id, r.outcome, r.run_id) for r in results)
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    holder = f"{socket.gethostname()}:{os.getpid()}"
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    log.info("scheduler iniciado (%s)", holder)
    while not stop:
        with session_factory()() as db:
            if acquire_lease(db, holder, ttl_seconds=s.scheduler_interval_seconds * 3):
                try:
                    summary = tick(db)
                    if summary["fired"] or summary["reaped"]:
                        log.info("tick: %s", summary)
                except Exception:
                    log.exception("erro no tick do scheduler")
        for _ in range(s.scheduler_interval_seconds):
            if stop:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
