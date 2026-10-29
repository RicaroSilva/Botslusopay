"""Ciclo de vida das execuções: criação, aprovação, fila, worker, conclusão."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Availability,
    Bot,
    BotDependency,
    ResourceLock,
    Role,
    Run,
    RunLog,
    TriggerRule,
    User,
    Worker,
    utcnow,
)
from ..registry.loader import bot_definition
from ..registry.schema import validate_parameters
from ..security.redaction import redact_obj, redact_text
from ..states import ACTIVE, TERMINAL, FailureReason, RunStatus, check_transition
from .audit import audit


class RunError(Exception):
    code = "run_error"
    http_status = 400

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.details = details


class BotUnavailable(RunError):
    code = "bot_unavailable"
    http_status = 409


class TriggerNotAllowed(RunError):
    code = "trigger_not_allowed"
    http_status = 403


class InvalidParameters(RunError):
    code = "invalid_parameters"
    http_status = 422


class DependencyUnmet(RunError):
    code = "dependency_unmet"
    http_status = 409


class ConflictingRun(RunError):
    code = "conflicting_run"
    http_status = 409


class ApprovalError(RunError):
    code = "approval_error"
    http_status = 403


class StateError(RunError):
    code = "invalid_state"
    http_status = 409


@dataclass
class CreateResult:
    run: Run
    deduplicated: bool = False


# --------------------------------------------------------------------------- utilitários


def _local_midnight_utc(now: datetime) -> datetime:
    tz = ZoneInfo(get_settings().timezone)
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def unmet_dependencies(db: Session, bot: Bot, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or utcnow()
    unmet = []
    deps = db.scalars(select(BotDependency).where(BotDependency.bot_id == bot.id, BotDependency.enabled.is_(True)))
    for dep in deps:
        since = _local_midnight_utc(now) if dep.condition == "succeeded_today" else now - timedelta(hours=dep.within_hours)
        ok = db.scalar(
            select(Run.id)
            .where(
                Run.bot_id == dep.depends_on_bot_id,
                Run.status == RunStatus.SUCCEEDED,
                Run.finished_at >= since,
            )
            .limit(1)
        )
        if ok is None:
            upstream = db.get(Bot, dep.depends_on_bot_id)
            unmet.append(
                {
                    "depends_on": upstream.key if upstream else dep.depends_on_bot_id,
                    "condition": dep.condition,
                    "within_hours": dep.within_hours,
                }
            )
    return unmet


def transition(
    db: Session,
    run: Run,
    target: RunStatus,
    *,
    actor_type: str,
    actor_id: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    current = RunStatus(run.status)
    check_transition(current, target)
    now = utcnow()
    run.status = target
    if target == RunStatus.QUEUED:
        run.queued_at = now
    elif target == RunStatus.RUNNING:
        run.started_at = now
        run.last_heartbeat_at = now
    if target in TERMINAL:
        run.finished_at = now
        run.exclusive_key = None
        db.execute(delete(ResourceLock).where(ResourceLock.run_id == run.id))
    audit(
        db,
        actor_type,
        actor_id,
        "run.status_changed",
        "run",
        run.id,
        details={"from": current.value, "to": target.value, **(details or {})},
    )
    if target == RunStatus.SUCCEEDED:
        # import tardio para evitar ciclo
        from ..triggers.after_bot import on_run_succeeded

        on_run_succeeded(db, run)


# --------------------------------------------------------------------------- criação


def create_run(
    db: Session,
    bot: Bot,
    *,
    source: str,
    user: User | None = None,
    parameters: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    rule: TriggerRule | None = None,
    trigger_event_id: str | None = None,
    parent_run: Run | None = None,
    retry_of: Run | None = None,
    actor_type: str = "user",
    actor_id: str | None = None,
    dry_run: bool = False,
) -> CreateResult:
    """Cria uma execução após TODAS as verificações. Não faz commit."""
    actor_id = actor_id or (user.username if user else None)
    if idempotency_key:
        existing = db.scalar(select(Run).where(Run.idempotency_key == idempotency_key))
        if existing is not None:
            return CreateResult(existing, deduplicated=True)

    if bot.adapter == "flow" and not bot.current_flow_version:
        raise BotUnavailable("o fluxo ainda não tem nenhuma versão gravada")
    if dry_run and bot.adapter != "flow":
        raise BotUnavailable("a simulação só existe para robôs nativos (fluxo ou Groovy)")
    # a simulação (teste) pode correr com o robô ainda desativado: não tem efeitos externos
    if not bot.in_registry or (not bot.enabled and not dry_run) or bot.availability != Availability.AVAILABLE:
        raise BotUnavailable(
            "bot indisponível", enabled=bot.enabled, availability=bot.availability.value, in_registry=bot.in_registry
        )
    defn = bot_definition(bot)
    trigger_kind = "manual" if source in ("manual", "retry") else source
    if trigger_kind not in defn.triggers_allowed:
        raise TriggerNotAllowed(f"o bot não permite disparo '{trigger_kind}'")
    try:
        _, public_params = validate_parameters(defn, parameters or {})
    except ValueError as exc:
        raise InvalidParameters(str(exc)) from exc

    unmet = unmet_dependencies(db, bot)
    if unmet:
        raise DependencyUnmet("dependências não satisfeitas", unmet=unmet)

    run = Run(
        bot_id=bot.id,
        status=RunStatus.PENDING,
        trigger_source=source,
        requested_by=user.id if user else None,
        trigger_rule_id=rule.id if rule else None,
        trigger_event_id=trigger_event_id,
        parent_run_id=parent_run.id if parent_run else None,
        retry_of_run_id=retry_of.id if retry_of else None,
        idempotency_key=idempotency_key,
        exclusive_key=bot.id if defn.concurrency.policy == "single" else None,
        parameters=public_params,
        timeout_seconds=defn.timeout_seconds,
        # a versão do fluxo fica fixada no pedido: é essa que é aprovada e executada
        flow_version=bot.current_flow_version if bot.adapter == "flow" else None,
        dry_run=dry_run,
    )
    try:
        with db.begin_nested():
            db.add(run)
            db.flush()
    except IntegrityError as exc:
        if idempotency_key:
            existing = db.scalar(select(Run).where(Run.idempotency_key == idempotency_key))
            if existing is not None:
                return CreateResult(existing, deduplicated=True)
        active = db.scalar(select(Run).where(Run.exclusive_key == bot.id))
        raise ConflictingRun(
            "já existe uma execução ativa deste bot", active_run_id=active.id if active else None
        ) from exc

    audit(
        db,
        actor_type,
        actor_id,
        "run.created",
        "run",
        run.id,
        details={"bot": bot.key, "source": source, "parameters": public_params, "rule": rule.id if rule else None,
                 "dry_run": dry_run},
    )
    needs_approval = (defn.requires_approval or bool(rule and rule.requires_approval)) and not dry_run
    if (needs_approval and source == "manual" and user is not None and user.role == Role.ADMIN
            and get_settings().admin_skips_approval):
        needs_approval = False
        run.approved_by = user.id
        run.approved_at = utcnow()
        audit(db, "user", user.username, "run.approval_waived", "run", run.id,
              details={"bot": bot.key, "reason": "pedida por um administrador"})
    transition(
        db,
        run,
        RunStatus.WAITING_APPROVAL if needs_approval else RunStatus.QUEUED,
        actor_type="system",
        actor_id="run-service",
    )
    return CreateResult(run)


# --------------------------------------------------------------------------- aprovação / cancelamento


def approve_run(db: Session, run: Run, approver: User, approve: bool, comment: str = "") -> None:
    if run.status != RunStatus.WAITING_APPROVAL:
        raise StateError("a execução não está a aguardar aprovação")
    s = get_settings()
    own = run.requested_by == approver.id
    if own and not s.allow_self_approval and not (approver.role == Role.ADMIN and s.admin_skips_approval):
        raise ApprovalError("quem pediu a execução não a pode aprovar")
    if approve:
        unmet = unmet_dependencies(db, run.bot)
        if unmet:
            raise DependencyUnmet("dependências deixaram de estar satisfeitas", unmet=unmet)
        run.approved_by = approver.id
        run.approved_at = utcnow()
        transition(db, run, RunStatus.QUEUED, actor_type="user", actor_id=approver.username,
                   details={"approval": "approved", "comment": comment[:500]})
    else:
        transition(db, run, RunStatus.CANCELLED, actor_type="user", actor_id=approver.username,
                   details={"approval": "rejected", "comment": comment[:500]})


def cancel_run(db: Session, run: Run, user: User) -> None:
    status = RunStatus(run.status)
    if status in TERMINAL:
        raise StateError("a execução já terminou")
    if status == RunStatus.RUNNING:
        run.cancel_requested = True
        audit(db, "user", user.username, "run.cancel_requested", "run", run.id)
    else:
        transition(db, run, RunStatus.CANCELLED, actor_type="user", actor_id=user.username)


# --------------------------------------------------------------------------- worker


def mark_lost_runs(db: Session, worker: Worker, active_run_ids: list[str]) -> list[str]:
    """Execuções RUNNING atribuídas ao worker que ele já não reporta (ex.: reinício)."""
    lost = list(
        db.scalars(
            select(Run).where(
                Run.worker_id == worker.id,
                Run.status == RunStatus.RUNNING,
                Run.id.not_in(active_run_ids or [""]),
            )
        )
    )
    for run in lost:
        _fail_lost(db, run, actor=worker.name, note="o worker deixou de reportar esta execução (reinício?)")
    return [r.id for r in lost]


def _fail_lost(db: Session, run: Run, actor: str, note: str, reason: FailureReason = FailureReason.WORKER_LOST) -> None:
    run.failure_reason = reason.value
    run.needs_review = True
    append_logs(db, run, [{"level": "ERROR", "source": "system", "message": note}])
    transition(db, run, RunStatus.FAILED, actor_type="system", actor_id=actor,
               details={"reason": reason.value, "needs_review": True})


def claim_next(db: Session, worker: Worker) -> Run | None:
    """Atribui ao worker a próxima execução QUEUED compatível cujos recursos estejam livres."""
    q = (
        select(Run)
        .join(Bot, Bot.id == Run.bot_id)
        .where(Run.status == RunStatus.QUEUED, Bot.adapter.in_(worker.capabilities or []))
        .order_by(Run.queued_at, Run.created_at)
        .limit(20)
    )
    if db.get_bind().dialect.name == "postgresql":
        q = q.with_for_update(of=Run, skip_locked=True)
    for run in db.scalars(q):
        resources = run.bot.exclusive_resources
        try:
            with db.begin_nested():
                for res in resources:
                    db.add(ResourceLock(resource=res, run_id=run.id))
                db.flush()
                res_upd = db.execute(
                    update(Run)
                    .where(Run.id == run.id, Run.status == RunStatus.QUEUED)
                    .values(worker_id=worker.id)
                    .execution_options(synchronize_session=False)
                )
                if res_upd.rowcount != 1:
                    raise IntegrityError("claim race", None, Exception())
        except IntegrityError:
            continue  # recurso ocupado ou corrida com outro worker: tenta a próxima
        db.refresh(run)
        transition(db, run, RunStatus.RUNNING, actor_type="worker", actor_id=worker.name,
                   details={"resources": resources})
        return run
    return None


def heartbeat(db: Session, run: Run) -> bool:
    """Atualiza heartbeat; devolve True se foi pedido cancelamento."""
    run.last_heartbeat_at = utcnow()
    return run.cancel_requested


def append_logs(db: Session, run: Run, entries: list[dict[str, Any]]) -> int:
    added = 0
    for e in entries[:500]:
        run.log_lines += 1
        seq = int(e.get("seq") or run.log_lines)
        exists = db.scalar(select(RunLog.id).where(RunLog.run_id == run.id, RunLog.seq == seq))
        if exists:
            continue
        ts = e.get("ts")
        db.add(
            RunLog(
                run_id=run.id,
                seq=seq,
                ts=datetime.fromisoformat(ts) if isinstance(ts, str) else utcnow(),
                level=str(e.get("level", "INFO"))[:10],
                source=str(e.get("source", "worker"))[:20],
                message=redact_text(str(e.get("message", "")))[:8000],
            )
        )
        added += 1
    db.flush()
    return added


def complete_run(
    db: Session,
    run: Run,
    worker: Worker,
    *,
    status: RunStatus,
    exit_code: int | None,
    failure_reason: str | None,
    result_summary: dict[str, Any] | None,
    process_started: bool,
) -> Run | None:
    if run.worker_id != worker.id or run.status != RunStatus.RUNNING:
        raise StateError("execução não está em curso neste worker")
    if status not in TERMINAL:
        raise StateError("estado final inválido")
    if status == RunStatus.SUCCEEDED and failure_reason:
        raise StateError("sucesso não pode ter failure_reason")
    run.exit_code = exit_code
    run.failure_reason = failure_reason if status != RunStatus.SUCCEEDED else None
    run.result_summary = redact_obj(result_summary or {})
    # Se o processo arrancou e o resultado é incerto, alguém tem de verificar
    # os efeitos externos antes de repetir.
    if status == RunStatus.FAILED and process_started and failure_reason in (
        FailureReason.TIMEOUT.value,
        FailureReason.RESULT_UNDETERMINED.value,
    ):
        run.needs_review = True
    transition(db, run, status, actor_type="worker", actor_id=worker.name,
               details={"exit_code": exit_code, "failure_reason": run.failure_reason})
    return _maybe_auto_retry(db, run, process_started)


def _maybe_auto_retry(db: Session, run: Run, process_started: bool) -> Run | None:
    if run.status != RunStatus.FAILED or process_started or run.retry_of_run_id:
        return None
    if run.failure_reason not in (FailureReason.LAUNCH_ERROR.value, FailureReason.WORKER_REJECTED.value):
        return None
    defn = bot_definition(run.bot)
    if not (defn.retry.automatic and defn.retry.idempotent):
        return None
    try:
        res = create_run(db, run.bot, source="retry", retry_of=run, parameters=run.parameters,
                         idempotency_key=f"auto-retry:{run.id}", actor_type="system", actor_id="auto-retry")
    except RunError:
        return None
    return res.run


def retry_run(db: Session, original: Run, user: User, confirm_side_effects_checked: bool) -> Run:
    if original.status not in (RunStatus.FAILED, RunStatus.CANCELLED):
        raise StateError("só é possível repetir execuções falhadas ou canceladas")
    if original.needs_review and not confirm_side_effects_checked:
        raise RunError(
            "esta execução pode ter produzido efeitos externos; confirme que verificou antes de repetir",
            requires_confirmation=True,
        )
    res = create_run(db, original.bot, source="retry", user=user, parameters=original.parameters, retry_of=original,
                     idempotency_key=f"retry:{original.id}:{user.id}:{utcnow():%Y%m%d%H%M}")
    if original.needs_review:
        audit(db, "user", user.username, "run.side_effects_confirmed", "run", original.id)
    return res.run


def reap_stale_runs(db: Session, now: datetime | None = None) -> list[str]:
    """Execuções sem heartbeat ou muito para lá do timeout passam a FAILED (needs_review)."""
    now = now or utcnow()
    s = get_settings()
    hb_limit = now - timedelta(seconds=s.worker_heartbeat_timeout_seconds)
    reaped = []
    for run in db.scalars(select(Run).where(Run.status == RunStatus.RUNNING)):
        if run.last_heartbeat_at and run.last_heartbeat_at < hb_limit:
            _fail_lost(db, run, "reaper", "sem heartbeat do worker; resultado e efeitos externos desconhecidos")
            reaped.append(run.id)
        elif run.started_at and run.started_at + timedelta(
            seconds=run.timeout_seconds + 2 * s.worker_heartbeat_timeout_seconds
        ) < now:
            _fail_lost(db, run, "reaper", "timeout excedido sem resposta do worker", FailureReason.TIMEOUT)
            reaped.append(run.id)
    return reaped


def active_run_for_bot(db: Session, bot: Bot) -> Run | None:
    return db.scalar(select(Run).where(Run.bot_id == bot.id, Run.status.in_(list(ACTIVE))).limit(1))
