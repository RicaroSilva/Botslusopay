from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import TriggerEvent, TriggerRule
from ..security.redaction import redact_obj
from ..services.audit import audit
from ..services.runs import RunError, create_run

TRIGGER_TYPES: dict[str, type["TriggerType"]] = {}


class TriggerType:
    name: ClassVar[str]
    config_model: ClassVar[type[BaseModel]]
    periodic: ClassVar[bool] = False  # avaliado pelo scheduler

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if getattr(cls, "name", None):
            TRIGGER_TYPES[cls.name] = cls

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> dict[str, Any]:
        return cls.config_model.model_validate(config).model_dump(mode="json")

    @classmethod
    def initial_next_fire(cls, rule: TriggerRule, now: datetime) -> datetime | None:
        return None

    @classmethod
    def evaluate(cls, db: Session, rule: TriggerRule, now: datetime) -> list["FireResult"]:
        """Chamado pelo scheduler para tipos periódicos."""
        return []


def get_trigger_type(name: str) -> type[TriggerType]:
    try:
        return TRIGGER_TYPES[name]
    except KeyError as exc:
        raise ValueError(f"tipo de disparo desconhecido: {name}") from exc


@dataclass
class FireResult:
    outcome: str  # accepted | duplicate | rejected
    event_id: str | None = None
    run_id: str | None = None
    error: str | None = None


def fire_rule(
    db: Session,
    rule: TriggerRule,
    dedup_key: str,
    details: dict[str, Any] | None = None,
    parent_run_id: str | None = None,
    actor: str | None = None,
) -> FireResult:
    """Regista o evento (único por regra+dedup_key) e cria a execução.

    Um evento repetido devolve 'duplicate' sem criar nova execução. Se a criação
    for recusada (bot ocupado, dependências, etc.) o evento fica registado como
    'rejected' com o motivo — não há nova tentativa automática."""
    dedup_key = dedup_key[:255]
    event = TriggerEvent(rule_id=rule.id, dedup_key=dedup_key, details=redact_obj(details or {}))
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        audit(db, "system", actor or rule.trigger_type, "trigger.duplicate_event", "trigger_rule", rule.id,
              details={"dedup_key": dedup_key})
        return FireResult("duplicate")

    parent = None
    if parent_run_id:
        from ..models import Run

        parent = db.get(Run, parent_run_id)
    try:
        with db.begin_nested():
            res = create_run(
                db,
                rule.bot,
                source=rule.trigger_type,
                rule=rule,
                trigger_event_id=event.id,
                parent_run=parent,
                parameters=rule.config.get("parameters") or {},
                idempotency_key=f"rule:{rule.id}:{dedup_key}",
                actor_type="system",
                actor_id=actor or f"trigger:{rule.trigger_type}",
            )
    except RunError as exc:
        event.outcome = "rejected"
        event.details = {**event.details, "error": str(exc), "code": exc.code, **redact_obj(exc.details)}
        audit(db, "system", actor or rule.trigger_type, "trigger.run_rejected", "trigger_rule", rule.id,
              outcome="error", details={"dedup_key": dedup_key, "error": str(exc), "code": exc.code})
        return FireResult("rejected", event_id=event.id, error=str(exc))
    event.run_id = res.run.id
    audit(db, "system", actor or rule.trigger_type, "trigger.fired", "trigger_rule", rule.id,
          details={"dedup_key": dedup_key, "run_id": res.run.id})
    return FireResult("accepted", event_id=event.id, run_id=res.run.id)
