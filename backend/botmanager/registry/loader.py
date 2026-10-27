"""Carrega o registo YAML e sincroniza-o com a tabela bots."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Availability, Bot
from ..services.audit import audit
from .schema import BotDefinition


@dataclass
class LoadResult:
    definitions: list[BotDefinition] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def load_registry(directories: Path | list[Path]) -> LoadResult:
    result = LoadResult()
    seen: set[str] = set()
    dirs = [directories] if isinstance(directories, Path) else list(directories)
    paths = [p for d in dirs for p in sorted(Path(d).glob("*.yaml"))]
    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            defn = BotDefinition.model_validate(raw)
        except (yaml.YAMLError, ValidationError) as exc:
            result.errors[path.name] = str(exc)
            continue
        if defn.key in seen:
            result.errors[path.name] = f"key duplicada: {defn.key}"
            continue
        seen.add(defn.key)
        result.definitions.append(defn)
    return result


def definition_hash(defn: BotDefinition) -> str:
    return hashlib.sha256(json.dumps(defn.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


def sync_registry(db: Session, directory: Path | list[Path], actor: str = "registry-sync") -> LoadResult:
    result = load_registry(directory)
    existing = {b.key: b for b in db.scalars(select(Bot))}
    for defn in result.definitions:
        h = definition_hash(defn)
        bot = existing.pop(defn.key, None)
        data = defn.model_dump(mode="json")
        if bot is None:
            bot = Bot(
                key=defn.key,
                name=defn.name,
                description=defn.description,
                category=defn.category,
                risk_level=defn.risk_level,
                adapter=defn.execution.adapter,
                project_ref=defn.execution.script,
                definition=data,
                definition_hash=h,
                availability=Availability.AVAILABLE if defn.execution.validated else Availability.UNVALIDATED,
                enabled=False,  # um administrador tem de ativar explicitamente
            )
            db.add(bot)
            db.flush()
            audit(db, "system", actor, "bot.registered", "bot", bot.id, details={"key": defn.key, "hash": h})
        elif bot.definition_hash != h or not bot.in_registry:
            bot.name, bot.description, bot.category = defn.name, defn.description, defn.category
            bot.risk_level, bot.adapter, bot.project_ref = defn.risk_level, defn.execution.adapter, defn.execution.script
            bot.definition, bot.definition_hash, bot.in_registry = data, h, True
            if not defn.execution.validated:
                bot.availability = Availability.UNVALIDATED
            elif bot.availability == Availability.UNVALIDATED:
                bot.availability = Availability.AVAILABLE
            audit(db, "system", actor, "bot.definition_changed", "bot", bot.id, details={"key": defn.key, "hash": h})
    for bot in existing.values():
        if bot.in_registry:
            bot.in_registry = False
            bot.enabled = False
            audit(db, "system", actor, "bot.removed_from_registry", "bot", bot.id, details={"key": bot.key})
    for name, err in result.errors.items():
        audit(db, "system", actor, "registry.invalid_definition", "registry", name, outcome="error", details={"error": err[:500]})
    db.commit()
    return result


def bot_definition(bot: Bot) -> BotDefinition:
    return BotDefinition.model_validate(bot.definition)
