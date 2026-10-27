from __future__ import annotations

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Bot, Permission, Run, RunLog, TriggerEvent, TriggerRule, User
from ..security.permissions import has_bot_permission
from ..services.runs import approve_run, cancel_run, retry_run
from ..states import RunStatus
from .deps import current_user, ensure_bot_permission
from .serializers import run_out

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _usernames(db: Session, *ids: str | None) -> dict[str, str]:
    ids_ = [i for i in ids if i]
    if not ids_:
        return {}
    return {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(ids_)))}


def _get_run(db: Session, run_id: str, user: User, request: Request, perm: Permission = Permission.VIEW) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "execução não encontrada")
    ensure_bot_permission(db, user, run.bot, Permission.VIEW, request)
    if perm != Permission.VIEW:
        ensure_bot_permission(db, user, run.bot, perm, request)
    return run


@router.get("")
def list_runs(
    bot: str | None = None,
    status: RunStatus | None = None,
    requested_by: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    needs_review: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = select(Run).join(Bot, Bot.id == Run.bot_id)
    if bot:
        q = q.where(Bot.key == bot)
    if status:
        q = q.where(Run.status == status)
    if requested_by:
        uid = db.scalar(select(User.id).where(User.username == requested_by))
        q = q.where(Run.requested_by == (uid or "-"))
    if date_from:
        q = q.where(Run.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        q = q.where(Run.created_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    if needs_review is not None:
        q = q.where(Run.needs_review.is_(needs_review))
    q = q.order_by(Run.created_at.desc())
    visible: dict[str, bool] = {}
    items = []
    skipped = 0
    for r in db.scalars(q.limit(2000)):
        if r.bot_id not in visible:
            visible[r.bot_id] = has_bot_permission(db, user, r.bot, Permission.VIEW)
        if not visible[r.bot_id]:
            continue
        if skipped < offset:
            skipped += 1
            continue
        items.append(r)
        if len(items) >= min(limit, 200):
            break
    names = _usernames(db, *[r.requested_by for r in items], *[r.approved_by for r in items])
    return [run_out(r, names) for r in items]


@router.get("/{run_id}")
def get_run(run_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = _get_run(db, run_id, user, request)
    out = run_out(run, _usernames(db, run.requested_by, run.approved_by))
    out["permissions"] = {
        "cancel": has_bot_permission(db, user, run.bot, Permission.EXECUTE),
        "approve": has_bot_permission(db, user, run.bot, Permission.APPROVE),
        "retry": has_bot_permission(db, user, run.bot, Permission.EXECUTE),
    }
    if run.trigger_rule_id:
        rule = db.get(TriggerRule, run.trigger_rule_id)
        out["trigger_rule"] = {"id": rule.id, "name": rule.name, "type": rule.trigger_type} if rule else None
    if run.trigger_event_id:
        ev = db.get(TriggerEvent, run.trigger_event_id)
        out["trigger_event"] = (
            {"id": ev.id, "dedup_key": ev.dedup_key, "received_at": ev.received_at.isoformat(), "details": ev.details}
            if ev else None
        )
    return out


@router.get("/{run_id}/logs")
def get_logs(run_id: str, request: Request, after_seq: int = 0, limit: int = 500,
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = _get_run(db, run_id, user, request)
    q = (select(RunLog).where(RunLog.run_id == run.id, RunLog.seq > after_seq)
         .order_by(RunLog.seq).limit(min(limit, 2000)))
    lines = [{"seq": l.seq, "ts": l.ts.isoformat(), "level": l.level, "source": l.source, "message": l.message}
             for l in db.scalars(q)]
    total = db.scalar(select(func.count()).select_from(RunLog).where(RunLog.run_id == run.id))
    return {"status": run.status.value, "lines": lines, "total": total}


@router.post("/{run_id}/cancel")
def cancel(run_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = _get_run(db, run_id, user, request, Permission.EXECUTE)
    cancel_run(db, run, user)
    db.commit()
    return {"status": run.status.value, "cancel_requested": run.cancel_requested}


class ApprovalIn(BaseModel):
    approve: bool
    comment: str = Field(default="", max_length=500)


@router.post("/{run_id}/approval")
def approval(run_id: str, body: ApprovalIn, request: Request, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    run = _get_run(db, run_id, user, request, Permission.APPROVE)
    approve_run(db, run, user, body.approve, body.comment)
    db.commit()
    return {"status": run.status.value}


class RetryIn(BaseModel):
    confirm_side_effects_checked: bool = False


@router.post("/{run_id}/retry", status_code=202)
def retry(run_id: str, body: RetryIn, request: Request, user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    run = _get_run(db, run_id, user, request, Permission.EXECUTE)
    new = retry_run(db, run, user, body.confirm_side_effects_checked)
    db.commit()
    return {"run_id": new.id, "status": new.status.value}
