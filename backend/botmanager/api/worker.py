"""API usada exclusivamente pelo Windows Worker (autenticação por token Bearer)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Run, Worker
from ..registry.loader import bot_definition
from ..services.audit import audit
from ..services.runs import append_logs, claim_next, complete_run, heartbeat, mark_lost_runs
from ..states import FailureReason, RunStatus

router = APIRouter(prefix="/api/worker", tags=["worker"])

from .deps import current_worker  # noqa: E402


class ClaimIn(BaseModel):
    active_run_ids: list[str] = []
    version: str = Field(default="", max_length=40)
    capabilities: list[str] | None = None


def _job(run: Run) -> dict[str, Any]:
    defn = bot_definition(run.bot)
    return {
        "run_id": run.id,
        "bot_key": run.bot.key,
        "adapter": defn.execution.adapter,
        "script": defn.execution.script,
        "expected_sha256": defn.execution.expected_sha256,
        "timeout_seconds": run.timeout_seconds,
        "parameters": run.parameters,
        "success_detection": defn.success_detection.model_dump(mode="json"),
        "started_at": run.started_at.isoformat() if run.started_at else None,
    }


@router.post("/claim")
def claim(body: ClaimIn, response: Response, worker: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    worker.version = body.version
    if body.capabilities is not None:
        # o worker só pode restringir as capacidades atribuídas pelo administrador
        allowed = set(worker.capabilities or [])
        worker_caps = [c for c in body.capabilities if c in allowed]
    else:
        worker_caps = worker.capabilities or []
    lost = mark_lost_runs(db, worker, body.active_run_ids)
    if lost:
        audit(db, "worker", worker.name, "worker.runs_lost", "worker", worker.id, outcome="error",
              details={"runs": lost})
    if body.active_run_ids:  # um trabalho de cada vez por worker
        db.commit()
        response.status_code = 204
        return None
    original = worker.capabilities
    worker.capabilities = worker_caps
    run = claim_next(db, worker)
    worker.capabilities = original
    db.commit()
    if run is None:
        response.status_code = 204
        return None
    return _job(run)


def _worker_run(db: Session, run_id: str, worker: Worker) -> Run:
    run = db.get(Run, run_id)
    if run is None or run.worker_id != worker.id:
        raise HTTPException(404, "execução não atribuída a este worker")
    return run


@router.post("/runs/{run_id}/heartbeat")
def run_heartbeat(run_id: str, worker: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    run = _worker_run(db, run_id, worker)
    if run.status != RunStatus.RUNNING:
        db.commit()
        # A execução foi dada como perdida/terminada: o worker deve parar o processo.
        return {"cancel_requested": True, "status": run.status.value}
    cancel = heartbeat(db, run)
    db.commit()
    return {"cancel_requested": cancel, "status": run.status.value}


class LogEntry(BaseModel):
    seq: int = Field(ge=1)
    ts: str | None = None
    level: str = "INFO"
    source: str = "worker"
    message: str = Field(max_length=8000)


class LogsIn(BaseModel):
    entries: list[LogEntry] = Field(max_length=500)


@router.post("/runs/{run_id}/logs")
def run_logs(run_id: str, body: LogsIn, worker: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    run = _worker_run(db, run_id, worker)
    added = append_logs(db, run, [e.model_dump() for e in body.entries])
    db.commit()
    return {"added": added}


class CompleteIn(BaseModel):
    status: RunStatus
    exit_code: int | None = None
    failure_reason: FailureReason | None = None
    process_started: bool = True
    result_summary: dict[str, Any] = {}


@router.post("/runs/{run_id}/complete")
def run_complete(run_id: str, body: CompleteIn, worker: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    run = _worker_run(db, run_id, worker)
    if run.status != RunStatus.RUNNING:
        # idempotente: um reenvio após timeout de rede não altera o estado final
        return {"status": run.status.value, "already_final": True}
    retry = complete_run(db, run, worker, status=body.status, exit_code=body.exit_code,
                         failure_reason=body.failure_reason.value if body.failure_reason else None,
                         result_summary=body.result_summary, process_started=body.process_started)
    db.commit()
    return {"status": run.status.value, "auto_retry_run_id": retry.id if retry else None}
