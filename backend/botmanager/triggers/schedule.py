"""Execução agendada (cron), avaliada no fuso horário configurado.

dedup_key = instante agendado, por isso um reinício do scheduler nunca
produz duas execuções para o mesmo horário. Disparos perdidos para lá de
misfire_grace_seconds são registados como 'missed' e não executados."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import TriggerRule
from ..services.audit import audit
from .base import FireResult, TriggerType, fire_rule


class ScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cron: str
    timezone: str | None = None
    parameters: dict = {}

    @field_validator("cron")
    @classmethod
    def _cron(cls, v: str) -> str:
        if not croniter.is_valid(v):
            raise ValueError("expressão cron inválida")
        return v


def _next_after(rule: TriggerRule, after: datetime) -> datetime:
    tz = ZoneInfo(rule.config.get("timezone") or get_settings().timezone)
    it = croniter(rule.config["cron"], after.astimezone(tz))
    return it.get_next(datetime).astimezone(timezone.utc)


class ScheduleTrigger(TriggerType):
    name = "schedule"
    config_model = ScheduleConfig
    periodic = True

    @classmethod
    def initial_next_fire(cls, rule, now):
        return _next_after(rule, now)

    @classmethod
    def evaluate(cls, db: Session, rule: TriggerRule, now: datetime) -> list[FireResult]:
        results: list[FireResult] = []
        if rule.next_fire_at is None:
            rule.next_fire_at = _next_after(rule, now)
            return results
        grace = timedelta(seconds=get_settings().schedule_misfire_grace_seconds)
        # Processa no máximo alguns instantes em atraso para não entrar em ciclo.
        for _ in range(50):
            due = rule.next_fire_at
            if due is None or due > now:
                break
            if now - due > grace:
                audit(db, "system", "scheduler", "trigger.schedule_missed", "trigger_rule", rule.id,
                      outcome="error", details={"scheduled_for": due.isoformat()})
            else:
                results.append(fire_rule(db, rule, f"schedule:{due.isoformat()}", {"scheduled_for": due.isoformat()},
                                         actor="scheduler"))
            rule.next_fire_at = _next_after(rule, due)
        return results
