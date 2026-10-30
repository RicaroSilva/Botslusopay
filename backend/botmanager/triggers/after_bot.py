"""Execução após conclusão bem-sucedida de outro bot.

Configuração: {"upstream_bot_key": "..."}; dedup_key = id da execução a montante,
pelo que cada sucesso a montante dispara no máximo uma vez."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Run, TriggerRule
from .base import TriggerType, fire_rule


class AfterBotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upstream_bot_key: str
    parameters: dict = {}


class AfterBotTrigger(TriggerType):
    name = "after_bot"
    config_model = AfterBotConfig


def on_run_succeeded(db: Session, run: Run) -> None:
    upstream_key = run.bot.key
    rules = db.scalars(
        select(TriggerRule).where(TriggerRule.trigger_type == "after_bot", TriggerRule.enabled.is_(True))
    )
    for rule in rules:
        if rule.config.get("upstream_bot_key") == upstream_key and rule.bot_id != run.bot_id:
            fire_rule(db, rule, f"after:{run.id}", {"upstream_run_id": run.id, "upstream_bot": upstream_key},
                      parent_run_id=run.id, actor="after_bot")
