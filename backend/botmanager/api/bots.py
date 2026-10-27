from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Bot, BotDependency, Permission, Run, TriggerRule, User
from ..security.permissions import has_bot_permission, user_bot_permissions
from ..services.runs import create_run, unmet_dependencies
from .deps import client_ip, current_user, ensure_bot_permission, get_bot_or_404
from .serializers import bot_out, rule_out, run_brief

router = APIRouter(prefix="/api/bots", tags=["bots"])


def _last_run(db: Session, bot: Bot) -> Run | None:
    return db.scalar(select(Run).where(Run.bot_id == bot.id).order_by(Run.created_at.desc()).limit(1))


@router.get("")
def list_bots(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for bot in db.scalars(select(Bot).where(Bot.in_registry.is_(True)).order_by(Bot.name)):
        if has_bot_permission(db, user, bot, Permission.VIEW):
            out.append(bot_out(bot, user_bot_permissions(db, user, bot), _last_run(db, bot)))
    return out


@router.get("/{key}")
def get_bot(key: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, key)
    ensure_bot_permission(db, user, bot, Permission.VIEW, request)
    data = bot_out(bot, user_bot_permissions(db, user, bot), _last_run(db, bot), full=True)
    deps = db.scalars(select(BotDependency).where(BotDependency.bot_id == bot.id))
    data["dependencies"] = [
        {"id": d.id, "depends_on": db.get(Bot, d.depends_on_bot_id).key, "condition": d.condition,
         "within_hours": d.within_hours, "enabled": d.enabled}
        for d in deps
    ]
    data["unmet_dependencies"] = unmet_dependencies(db, bot)
    data["rules"] = [rule_out(r) for r in db.scalars(select(TriggerRule).where(TriggerRule.bot_id == bot.id))]
    return data


@router.get("/{key}/runs")
def bot_runs(key: str, request: Request, limit: int = 50, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, key)
    ensure_bot_permission(db, user, bot, Permission.VIEW, request)
    q = select(Run).where(Run.bot_id == bot.id).order_by(Run.created_at.desc()).limit(min(limit, 200))
    return [run_brief(r) for r in db.scalars(q)]


class RunRequest(BaseModel):
    parameters: dict[str, Any] = {}
    # gerado pelo browser por clique: protege contra duplo clique / reenvio
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/{key}/run", status_code=202)
def run_bot(key: str, body: RunRequest, request: Request, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, key)
    ensure_bot_permission(db, user, bot, Permission.VIEW, request)
    ensure_bot_permission(db, user, bot, Permission.EXECUTE, request)
    res = create_run(db, bot, source="manual", user=user, parameters=body.parameters,
                     idempotency_key=f"manual:{user.id}:{body.idempotency_key}")
    db.commit()
    return {"run_id": res.run.id, "status": res.run.status.value, "deduplicated": res.deduplicated}
