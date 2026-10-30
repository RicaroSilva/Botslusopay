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
from ..security import vault
from ..services.audit import audit
from ..services.runs import append_logs, claim_next, complete_run, heartbeat, mark_lost_runs
from ..states import FailureReason, RunStatus

router = APIRouter(prefix="/api/worker", tags=["worker"])

from .deps import current_worker  # noqa: E402


class ClaimIn(BaseModel):
    active_run_ids: list[str] = []
    version: str = Field(default="", max_length=40)
    capabilities: list[str] | None = None


def _job(db: Session, run: Run) -> dict[str, Any]:
    defn = bot_definition(run.bot)
    job = {
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
    if defn.execution.adapter == "flow":
        from ..config import get_settings
        from ..flows import service as flows

        fv = flows.get_version(db, run.bot, run.flow_version)
        if fv is None:
            raise vault.VaultError(f"versão {run.flow_version} do fluxo não encontrada")
        job["flow"] = {"version": fv.version, "definition": fv.definition}
        job["dry_run"] = run.dry_run
        # Só as credenciais referidas pelo fluxo, decifradas, por HTTPS e apenas para esta execução.
        job["credentials"] = flows.credentials_for_job(db, fv.definition)
        job["allowed_hosts"] = get_settings().flow_allowed_hosts
        job["parameters"] = run.parameters
        # ficheiros persistentes declarados nesta versão do fluxo (conteúdo atual)
        import base64

        from ..models import FlowFile

        names = list(fv.definition.get("persistent_files") or [])
        stored = {f.name: f for f in db.scalars(select(FlowFile).where(FlowFile.bot_id == run.bot_id,
                                                                       FlowFile.name.in_(names or [""])))}
        job["persistent_files"] = {n: base64.b64encode(stored[n].content).decode() if n in stored else None
                                   for n in names}
    return job


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
    if run is None:
        db.commit()
        response.status_code = 204
        return None
    try:
        job = _job(db, run)
    except vault.VaultError as exc:
        append_logs(db, run, [{"level": "ERROR", "source": "system", "message": f"Não foi possível preparar o fluxo: {exc}"}])
        complete_run(db, run, worker, status=RunStatus.FAILED, exit_code=None,
                     failure_reason=FailureReason.WORKER_REJECTED.value, result_summary={"reason": str(exc)},
                     process_started=False)
        db.commit()
        response.status_code = 204
        return None
    db.commit()
    return job


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


class ArtifactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200, pattern=r"^[^\\/:*?\"<>|]+$")
    content_type: str = Field(default="application/octet-stream", max_length=100)
    data_b64: str


@router.post("/runs/{run_id}/artifacts", status_code=201)
def upload_artifact(run_id: str, body: ArtifactIn, worker: Worker = Depends(current_worker),
                    db: Session = Depends(get_db)):
    import base64
    import binascii
    import hashlib

    from ..config import get_settings
    from ..models import RunArtifact

    run = _worker_run(db, run_id, worker)
    if run.status != RunStatus.RUNNING:
        raise HTTPException(409, "execução já terminou")
    try:
        data = base64.b64decode(body.data_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "data_b64 inválido") from exc
    if len(data) > get_settings().artifact_max_bytes:
        raise HTTPException(413, "ficheiro demasiado grande")
    sha = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(RunArtifact).where(RunArtifact.run_id == run.id, RunArtifact.name == body.name))
    if existing:  # reenvio idempotente
        return {"id": existing.id, "sha256": existing.sha256}
    art = RunArtifact(run_id=run.id, name=body.name, content_type=body.content_type, size_bytes=len(data),
                      sha256=sha, data=data)
    db.add(art)
    db.commit()
    return {"id": art.id, "sha256": sha}


class PersistentFileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content_b64: str = Field(max_length=8_000_000)


@router.post("/runs/{run_id}/persistent-files")
def save_persistent_file(run_id: str, body: PersistentFileIn, worker: Worker = Depends(current_worker),
                         db: Session = Depends(get_db)):
    import base64
    import binascii

    from ..flows import service as flows
    from .flows import FLOW_FILE_MAX_BYTES, save_flow_file

    run = _worker_run(db, run_id, worker)
    if run.status != RunStatus.RUNNING:
        raise HTTPException(409, "execução já terminou")
    if run.dry_run:
        raise HTTPException(409, "uma simulação não altera os ficheiros persistentes")
    fv = flows.get_version(db, run.bot, run.flow_version)
    if fv is None or body.name not in (fv.definition.get("persistent_files") or []):
        raise HTTPException(403, "ficheiro não declarado como persistente neste fluxo")
    try:
        data = base64.b64decode(body.content_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "conteúdo inválido") from exc
    if len(data) > FLOW_FILE_MAX_BYTES:
        raise HTTPException(413, "ficheiro demasiado grande")
    changed = save_flow_file(db, run.bot, body.name, data, f"run:{run.id}")
    if changed:
        audit(db, "worker", worker.name, "flow.file_updated_by_run", "run", run.id,
              details={"file": body.name, "size": len(data)})
    db.commit()
    return {"changed": changed}
