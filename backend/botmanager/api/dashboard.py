from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditEvent, Bot, Permission, Role, Run, User, Worker, utcnow
from ..security.permissions import has_bot_permission
from ..states import RunStatus
from .deps import current_user
from .serializers import run_brief

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    bots = [b for b in db.scalars(select(Bot).where(Bot.in_registry.is_(True)))
            if has_bot_permission(db, user, b, Permission.VIEW)]
    ids = [b.id for b in bots]
    since = utcnow() - timedelta(days=7)
    runs = list(db.scalars(select(Run).where(Run.bot_id.in_(ids or [""]), Run.created_at >= since)
                           .order_by(Run.created_at.desc())))
    count = lambda *st: sum(1 for r in runs if r.status in st)  # noqa: E731
    activity = []
    if user.role in (Role.ADMIN, Role.APPROVER):
        activity = [
            {"ts": a.created_at.isoformat(), "actor": a.actor_id, "action": a.action,
             "resource": f"{a.resource_type}:{a.resource_id}", "outcome": a.outcome}
            for a in db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(15))
        ]
    workers = [{"name": w.name, "last_seen_at": w.last_seen_at.isoformat() if w.last_seen_at else None,
                "online": bool(w.last_seen_at and w.last_seen_at > utcnow() - timedelta(minutes=2))}
               for w in db.scalars(select(Worker).where(Worker.is_active.is_(True)))]
    return {
        "bots_total": len(bots),
        "bots_available": sum(1 for b in bots if b.enabled and b.availability.value == "available"),
        "running": count(RunStatus.RUNNING),
        "queued": count(RunStatus.QUEUED, RunStatus.PENDING),
        "waiting_approval": count(RunStatus.WAITING_APPROVAL),
        "succeeded_7d": count(RunStatus.SUCCEEDED),
        "failed_7d": count(RunStatus.FAILED),
        "needs_review": sum(1 for r in runs if r.needs_review),
        "recent_failures": [run_brief(r) for r in runs if r.status == RunStatus.FAILED][:10],
        "recent_runs": [run_brief(r) for r in runs[:10]],
        "activity": activity,
        "workers": workers,
    }
