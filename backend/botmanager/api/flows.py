"""Fluxos nativos: criados e editados na aplicação, executados pelo flow runner."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..flows import service
from ..flows.schema import STEP_TYPES
from ..models import Availability, Bot, FlowVersion, Permission, Role, User
from ..registry.loader import definition_hash
from ..registry.schema import BotDefinition, KEY_RE
from ..services.audit import audit
from .deps import client_ip, current_user, ensure_bot_permission, get_bot_or_404, require_role
from .serializers import bot_out

router = APIRouter(prefix="/api/flows", tags=["flows"])


class FlowMeta(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=80)
    risk_level: Literal["low", "medium", "high"] = "medium"
    timeout_seconds: int = Field(default=1800, ge=30, le=86400)
    triggers_allowed: list[str] = ["manual"]
    requires_approval: bool = False
    concurrency: Literal["single", "parallel"] = "single"
    external_effects: list[str] = []
    prerequisites: list[str] = []


class FlowCreate(FlowMeta):
    key: str
    definition: dict[str, Any]
    comment: str = Field(default="versão inicial", max_length=300)


class FlowSave(BaseModel):
    definition: dict[str, Any]
    comment: str = Field(default="", max_length=300)


def _bot_definition(key: str, meta: FlowMeta) -> BotDefinition:
    perms = {"view": ["viewer", "operator", "approver"], "execute": ["operator"]}
    if meta.risk_level == "high" or meta.requires_approval:
        perms["approve"] = ["approver"]
    return BotDefinition.model_validate({
        "key": key, "name": meta.name, "description": meta.description, "category": meta.category,
        "risk_level": meta.risk_level,
        "execution": {"adapter": "flow", "script": f"flows/{key}", "validated": True},
        "external_effects": meta.external_effects, "prerequisites": meta.prerequisites,
        "concurrency": {"policy": meta.concurrency, "exclusive_resources": []},
        "timeout_seconds": meta.timeout_seconds, "success_detection": {"method": "flow"},
        "triggers_allowed": meta.triggers_allowed,
        "requires_approval": meta.requires_approval or meta.risk_level == "high",
        "permissions": perms,
    })


def _apply_definition(bot: Bot, defn: BotDefinition) -> None:
    bot.name, bot.description, bot.category = defn.name, defn.description, defn.category
    bot.risk_level, bot.adapter, bot.project_ref = defn.risk_level, "flow", defn.execution.script
    bot.definition = defn.model_dump(mode="json")
    bot.definition_hash = definition_hash(defn)


def _flow_bot(db: Session, key: str) -> Bot:
    bot = get_bot_or_404(db, key)
    if bot.adapter != "flow":
        raise HTTPException(404, "não é um fluxo nativo")
    return bot


@router.get("/step-types")
def step_types(user: User = Depends(current_user)):
    return STEP_TYPES


@router.get("/credential-names")
def credential_names(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Nomes e tipos das credenciais (sem quaisquer dados) para o editor de fluxos."""
    from ..models import Credential

    return [{"name": c.name, "kind": c.kind, "description": c.description}
            for c in db.scalars(select(Credential).order_by(Credential.name))]


@router.post("", status_code=201)
def create_flow(body: FlowCreate, request: Request, user: User = Depends(require_role(Role.ADMIN)),
                db: Session = Depends(get_db)):
    if not KEY_RE.match(body.key):
        raise HTTPException(422, "chave inválida: 3-80 caracteres [a-z0-9-]")
    if db.scalar(select(Bot.id).where(Bot.key == body.key)):
        raise HTTPException(409, "já existe um bot com esta chave")
    try:
        defn = _bot_definition(body.key, body)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    bot = Bot(key=body.key, source="ui", availability=Availability.AVAILABLE, enabled=False, name="", project_ref="",
              adapter="flow")
    _apply_definition(bot, defn)
    db.add(bot)
    db.flush()
    try:
        service.save_version(db, bot, body.definition, user, body.comment)
    except (ValidationError, ValueError) as exc:
        db.rollback()
        raise HTTPException(422, f"fluxo inválido: {exc}") from exc
    audit(db, "user", user.username, "flow.created", "bot", bot.id, details={"key": bot.key}, ip=client_ip(request))
    db.commit()
    return bot_out(bot, full=True)


@router.get("/{key}")
def get_flow(key: str, request: Request, version: int | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    bot = _flow_bot(db, key)
    ensure_bot_permission(db, user, bot, Permission.VIEW, request)
    fv = service.get_version(db, bot, version or bot.current_flow_version)
    versions = db.scalars(select(FlowVersion).where(FlowVersion.bot_id == bot.id).order_by(FlowVersion.version.desc()))
    names = {u.id: u.username for u in db.scalars(select(User))}
    return {
        "bot": bot_out(bot, full=True),
        "current_version": bot.current_flow_version,
        "version": fv.version if fv else None,
        "definition": fv.definition if fv else None,
        "versions": [{"version": v.version, "comment": v.comment, "created_at": v.created_at.isoformat(),
                      "created_by": names.get(v.created_by or "", None)} for v in versions],
    }


@router.post("/validate")
def validate_flow(body: FlowSave, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        service.validate(db, body.definition)
    except (ValidationError, ValueError) as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True}


@router.put("/{key}")
def save_flow(key: str, body: FlowSave, request: Request, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    bot = _flow_bot(db, key)
    ensure_bot_permission(db, user, bot, Permission.CONFIGURE, request)
    try:
        fv = service.save_version(db, bot, body.definition, user, body.comment)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, f"fluxo inválido: {exc}") from exc
    db.commit()
    return {"version": fv.version}


@router.patch("/{key}")
def update_meta(key: str, body: FlowMeta, request: Request, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    bot = _flow_bot(db, key)
    ensure_bot_permission(db, user, bot, Permission.CONFIGURE, request)
    try:
        defn = _bot_definition(bot.key, body)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    before = {k: bot.definition.get(k) for k in ("risk_level", "requires_approval", "timeout_seconds", "triggers_allowed")}
    _apply_definition(bot, defn)
    audit(db, "user", user.username, "flow.meta_updated", "bot", bot.id,
          details={"before": before, "after": body.model_dump()}, ip=client_ip(request))
    db.commit()
    return bot_out(bot, full=True)
