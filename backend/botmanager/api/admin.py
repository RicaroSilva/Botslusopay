from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import (
    AuditEvent,
    Availability,
    Bot,
    BotDependency,
    BotPermission,
    Permission,
    Role,
    Setting,
    TriggerRule,
    User,
    Worker,
    utcnow,
)
from ..registry.loader import bot_definition, sync_registry
from ..security.passwords import hash_password, hash_token, new_token
from ..services.audit import audit
from ..triggers import get_trigger_type
from .deps import client_ip, current_user, ensure_bot_permission, get_bot_or_404, require_role
from .serializers import bot_out, rule_out, user_out

router = APIRouter(prefix="/api/admin", tags=["admin"])
admin_only = require_role(Role.ADMIN)

# Configurações operacionais editáveis (nunca segredos).
EDITABLE_SETTINGS: dict[str, type] = {
    "maintenance_banner": str,
    "pause_automatic_triggers": bool,
}


# ------------------------------------------------------------------ bots


@router.get("/bots")
def admin_bots(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [bot_out(b, full=True) for b in db.scalars(select(Bot).order_by(Bot.name))]


class BotPatch(BaseModel):
    enabled: bool | None = None
    availability: Availability | None = None
    reason: str = Field(default="", max_length=300)


@router.patch("/bots/{key}")
def patch_bot(key: str, body: BotPatch, request: Request, user: User = Depends(admin_only),
              db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, key)
    defn = bot_definition(bot)
    changes: dict[str, Any] = {}
    if body.availability is not None:
        if body.availability == Availability.AVAILABLE and not defn.execution.validated:
            raise HTTPException(409, "o mecanismo de execução deste bot ainda não foi validado (execution.validated)")
        if body.availability == Availability.UNVALIDATED:
            raise HTTPException(422, "'unvalidated' é definido pelo registo")
        changes["availability"] = [bot.availability.value, body.availability.value]
        bot.availability = body.availability
    if body.enabled is not None:
        if not bot.in_registry and body.enabled:
            raise HTTPException(409, "bot removido do registo")
        changes["enabled"] = [bot.enabled, body.enabled]
        bot.enabled = body.enabled
    audit(db, "user", user.username, "bot.updated", "bot", bot.id, details={**changes, "reason": body.reason},
          ip=client_ip(request))
    db.commit()
    return bot_out(bot, full=True)


@router.post("/registry/sync")
def registry_sync(request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    res = sync_registry(db, get_settings().registry_dirs, actor=user.username)
    return {"loaded": [d.key for d in res.definitions], "errors": res.errors}


# ------------------------------------------------------------------ regras de disparo


class RuleIn(BaseModel):
    bot_key: str
    name: str = Field(min_length=3, max_length=200)
    trigger_type: str
    config: dict[str, Any] = {}
    enabled: bool = False
    requires_approval: bool = False


class RulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    requires_approval: bool | None = None


def _validated_config(db: Session, bot: Bot, trigger_type: str, config: dict[str, Any]) -> dict[str, Any]:
    defn = bot_definition(bot)
    if trigger_type not in defn.triggers_allowed:
        raise HTTPException(422, f"o registo do bot não permite disparo '{trigger_type}'")
    try:
        ttype = get_trigger_type(trigger_type)
        cfg = ttype.validate_config(config)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, f"configuração inválida: {exc}") from exc
    if "parameters" in cfg and cfg["parameters"]:
        from ..registry.schema import validate_parameters

        try:
            validate_parameters(defn, cfg["parameters"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if trigger_type == "after_bot":
        up = db.scalar(select(Bot).where(Bot.key == cfg["upstream_bot_key"]))
        if up is None or up.id == bot.id:
            raise HTTPException(422, "upstream_bot_key inválido")
    return cfg


@router.get("/rules")
def list_rules(user: User = Depends(require_role(Role.VIEWER)), db: Session = Depends(get_db)):
    from ..security.permissions import has_bot_permission

    return [rule_out(r) for r in db.scalars(select(TriggerRule).order_by(TriggerRule.created_at))
            if has_bot_permission(db, user, r.bot, Permission.CONFIGURE)]


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, body.bot_key)
    ensure_bot_permission(db, user, bot, Permission.CONFIGURE, request)
    cfg = _validated_config(db, bot, body.trigger_type, body.config)
    if bot.requires_approval and not body.requires_approval:
        body.requires_approval = True  # o bot exige sempre aprovação
    rule = TriggerRule(bot_id=bot.id, name=body.name, trigger_type=body.trigger_type, config=cfg,
                       enabled=body.enabled, requires_approval=body.requires_approval, created_by=user.id)
    secret = None
    if body.trigger_type == "webhook":
        secret = new_token()
        rule.secret = secret
    rule.next_fire_at = get_trigger_type(body.trigger_type).initial_next_fire(rule, utcnow())
    db.add(rule)
    db.flush()
    audit(db, "user", user.username, "rule.created", "trigger_rule", rule.id,
          details={"bot": bot.key, "type": body.trigger_type, "config": cfg, "enabled": body.enabled},
          ip=client_ip(request))
    db.commit()
    out = rule_out(rule)
    if secret:
        out["webhook_secret"] = secret  # mostrado uma única vez
        out["webhook_url"] = f"/api/hooks/{rule.id}"
    return out


@router.patch("/rules/{rule_id}")
def patch_rule(rule_id: str, body: RulePatch, request: Request, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    rule = db.get(TriggerRule, rule_id)
    if rule is None:
        raise HTTPException(404, "regra não encontrada")
    ensure_bot_permission(db, user, rule.bot, Permission.CONFIGURE, request)
    before = rule_out(rule)
    if body.config is not None:
        rule.config = _validated_config(db, rule.bot, rule.trigger_type, body.config)
        rule.next_fire_at = get_trigger_type(rule.trigger_type).initial_next_fire(rule, utcnow())
    if body.name is not None:
        rule.name = body.name
    if body.requires_approval is not None:
        if rule.bot.requires_approval and not body.requires_approval:
            raise HTTPException(422, "o bot exige aprovação")
        rule.requires_approval = body.requires_approval
    if body.enabled is not None:
        rule.enabled = body.enabled
        if body.enabled:
            rule.next_fire_at = get_trigger_type(rule.trigger_type).initial_next_fire(rule, utcnow())
    audit(db, "user", user.username, "rule.updated", "trigger_rule", rule.id,
          details={"before": {k: before[k] for k in ("config", "enabled", "requires_approval", "name")},
                   "after": body.model_dump(exclude_none=True)}, ip=client_ip(request))
    db.commit()
    return rule_out(rule)


@router.post("/rules/{rule_id}/rotate-secret")
def rotate_secret(rule_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rule = db.get(TriggerRule, rule_id)
    if rule is None or rule.trigger_type != "webhook":
        raise HTTPException(404, "regra webhook não encontrada")
    ensure_bot_permission(db, user, rule.bot, Permission.CONFIGURE, request)
    rule.secret = new_token()
    audit(db, "user", user.username, "rule.secret_rotated", "trigger_rule", rule.id, ip=client_ip(request))
    db.commit()
    return {"webhook_secret": rule.secret}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rule = db.get(TriggerRule, rule_id)
    if rule is None:
        raise HTTPException(404, "regra não encontrada")
    ensure_bot_permission(db, user, rule.bot, Permission.CONFIGURE, request)
    audit(db, "user", user.username, "rule.deleted", "trigger_rule", rule.id, details=rule_out(rule),
          ip=client_ip(request))
    db.delete(rule)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ dependências


class DependencyIn(BaseModel):
    bot_key: str
    depends_on: str
    condition: str = Field(default="succeeded_within", pattern="^(succeeded_within|succeeded_today)$")
    within_hours: int = Field(default=24, ge=1, le=24 * 31)


def _creates_cycle(db: Session, bot_id: str, depends_on_id: str) -> bool:
    graph: dict[str, list[str]] = {}
    for d in db.scalars(select(BotDependency)):
        graph.setdefault(d.bot_id, []).append(d.depends_on_bot_id)
    graph.setdefault(bot_id, []).append(depends_on_id)
    stack, seen = [depends_on_id], set()
    while stack:
        cur = stack.pop()
        if cur == bot_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(graph.get(cur, []))
    return False


@router.get("/dependencies")
def list_dependencies(user: User = Depends(require_role(Role.VIEWER)), db: Session = Depends(get_db)):
    out = []
    for d in db.scalars(select(BotDependency)):
        out.append({"id": d.id, "bot_key": db.get(Bot, d.bot_id).key, "depends_on": db.get(Bot, d.depends_on_bot_id).key,
                    "condition": d.condition, "within_hours": d.within_hours, "enabled": d.enabled})
    return out


@router.post("/dependencies", status_code=201)
def create_dependency(body: DependencyIn, request: Request, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, body.bot_key)
    up = get_bot_or_404(db, body.depends_on)
    ensure_bot_permission(db, user, bot, Permission.CONFIGURE, request)
    if bot.id == up.id or _creates_cycle(db, bot.id, up.id):
        raise HTTPException(422, "dependência inválida: cria um ciclo")
    dep = BotDependency(bot_id=bot.id, depends_on_bot_id=up.id, condition=body.condition, within_hours=body.within_hours)
    db.add(dep)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "dependência já existe") from exc
    audit(db, "user", user.username, "dependency.created", "bot", bot.id, details=body.model_dump(),
          ip=client_ip(request))
    db.commit()
    return {"id": dep.id}


@router.delete("/dependencies/{dep_id}")
def delete_dependency(dep_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    dep = db.get(BotDependency, dep_id)
    if dep is None:
        raise HTTPException(404, "dependência não encontrada")
    bot = db.get(Bot, dep.bot_id)
    ensure_bot_permission(db, user, bot, Permission.CONFIGURE, request)
    audit(db, "user", user.username, "dependency.deleted", "bot", bot.id,
          details={"depends_on": db.get(Bot, dep.depends_on_bot_id).key}, ip=client_ip(request))
    db.delete(dep)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ utilizadores e permissões


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9._@-]+$")
    display_name: str = Field(default="", max_length=200)
    email: str | None = Field(default=None, max_length=254)
    role: Role = Role.VIEWER
    password: str = Field(min_length=12, max_length=256)


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    role: Role | None = None
    is_active: bool | None = None
    new_password: str | None = Field(default=None, min_length=12, max_length=256)


@router.get("/users")
def list_users(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users", status_code=201)
def create_user(body: UserIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(409, "utilizador já existe")
    u = User(username=body.username, display_name=body.display_name, email=body.email, role=body.role,
             password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    audit(db, "user", user.username, "user.created", "user", u.id, details={"username": u.username, "role": u.role.value},
          ip=client_ip(request))
    db.commit()
    return user_out(u)


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatch, request: Request, user: User = Depends(admin_only),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "utilizador não encontrado")
    if u.id == user.id and (body.role not in (None, Role.ADMIN) or body.is_active is False):
        raise HTTPException(409, "não pode retirar a sua própria administração")
    changes = body.model_dump(exclude_none=True, exclude={"new_password"})
    for k, v in changes.items():
        setattr(u, k, v)
    if body.new_password:
        u.password_hash = hash_password(body.new_password)
        changes["password"] = "reset"
    if body.role is not None or body.is_active is not None or body.new_password:
        u.token_version += 1  # termina sessões ativas
    audit(db, "user", user.username, "user.updated", "user", u.id,
          details={k: (v.value if isinstance(v, Role) else v) for k, v in changes.items()}, ip=client_ip(request))
    db.commit()
    return user_out(u)


class GrantIn(BaseModel):
    user_id: str
    bot_key: str
    permission: Permission


@router.get("/permissions")
def list_grants(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    out = []
    for g in db.scalars(select(BotPermission)):
        out.append({"id": g.id, "user_id": g.user_id, "username": db.get(User, g.user_id).username,
                    "bot_key": db.get(Bot, g.bot_id).key, "permission": g.permission.value})
    return out


@router.post("/permissions", status_code=201)
def grant(body: GrantIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, body.bot_key)
    if db.get(User, body.user_id) is None:
        raise HTTPException(404, "utilizador não encontrado")
    g = BotPermission(bot_id=bot.id, user_id=body.user_id, permission=body.permission, granted_by=user.id)
    db.add(g)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "permissão já concedida") from exc
    audit(db, "user", user.username, "permission.granted", "bot", bot.id,
          details={"user_id": body.user_id, "permission": body.permission.value}, ip=client_ip(request))
    db.commit()
    return {"id": g.id}


@router.delete("/permissions/{grant_id}")
def revoke(grant_id: int, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    g = db.get(BotPermission, grant_id)
    if g is None:
        raise HTTPException(404, "permissão não encontrada")
    audit(db, "user", user.username, "permission.revoked", "bot", g.bot_id,
          details={"user_id": g.user_id, "permission": g.permission.value}, ip=client_ip(request))
    db.delete(g)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ workers


class WorkerIn(BaseModel):
    name: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9._-]+$")
    capabilities: list[str] = ["taskt_cli"]


@router.get("/workers")
def list_workers(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [{"id": w.id, "name": w.name, "is_active": w.is_active, "capabilities": w.capabilities,
             "last_seen_at": w.last_seen_at.isoformat() if w.last_seen_at else None, "version": w.version}
            for w in db.scalars(select(Worker))]


@router.post("/workers", status_code=201)
def create_worker(body: WorkerIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    from ..registry.schema import ADAPTERS

    if set(body.capabilities) - ADAPTERS:
        raise HTTPException(422, "adaptador desconhecido")
    token = new_token()
    w = Worker(name=body.name, token_hash=hash_token(token), capabilities=body.capabilities)
    db.add(w)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "worker já existe") from exc
    audit(db, "user", user.username, "worker.created", "worker", w.id, details=body.model_dump(), ip=client_ip(request))
    db.commit()
    return {"id": w.id, "name": w.name, "token": token}  # token mostrado uma única vez


@router.patch("/workers/{worker_id}")
def patch_worker(worker_id: str, is_active: bool, request: Request, user: User = Depends(admin_only),
                 db: Session = Depends(get_db)):
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(404, "worker não encontrado")
    w.is_active = is_active
    audit(db, "user", user.username, "worker.updated", "worker", w.id, details={"is_active": is_active},
          ip=client_ip(request))
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ configurações e auditoria


@router.get("/settings")
def get_settings_view(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    s = get_settings()
    stored = {st.key: st.value for st in db.scalars(select(Setting))}
    return {
        "editable": {k: stored.get(k) for k in EDITABLE_SETTINGS},
        "runtime": {  # apenas leitura, sem segredos
            "environment": s.environment,
            "timezone": s.timezone,
            "registry_dir": str(s.registry_dirs),
            "worker_heartbeat_timeout_seconds": s.worker_heartbeat_timeout_seconds,
            "schedule_misfire_grace_seconds": s.schedule_misfire_grace_seconds,
            "poll_allowed_hosts": s.poll_allowed_hosts,
            "allow_self_approval": s.allow_self_approval,
            "session_minutes": s.session_minutes,
        },
    }


class SettingIn(BaseModel):
    key: str
    value: Any


@router.put("/settings")
def put_setting(body: SettingIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    typ = EDITABLE_SETTINGS.get(body.key)
    if typ is None or not isinstance(body.value, typ):
        raise HTTPException(422, "configuração não editável ou tipo inválido")
    st = db.get(Setting, body.key) or Setting(key=body.key, value=None)
    old = st.value
    st.value, st.updated_by = body.value, user.id
    db.merge(st)
    audit(db, "user", user.username, "setting.updated", "setting", body.key, details={"from": old, "to": body.value},
          ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit_log(actor: str | None = None, action: str | None = None, resource_type: str | None = None,
              resource_id: str | None = None, date_from: date | None = None, limit: int = 100, before_id: int | None = None,
              user: User = Depends(require_role(Role.APPROVER)), db: Session = Depends(get_db)):
    q = select(AuditEvent).order_by(AuditEvent.id.desc())
    if actor:
        q = q.where(AuditEvent.actor_id == actor)
    if action:
        q = q.where(AuditEvent.action.startswith(action))
    if resource_type:
        q = q.where(AuditEvent.resource_type == resource_type)
    if resource_id:
        q = q.where(AuditEvent.resource_id == resource_id)
    if date_from:
        q = q.where(AuditEvent.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if before_id:
        q = q.where(AuditEvent.id < before_id)
    return [{"id": a.id, "created_at": a.created_at.isoformat(), "actor_type": a.actor_type, "actor_id": a.actor_id,
             "action": a.action, "resource_type": a.resource_type, "resource_id": a.resource_id, "outcome": a.outcome,
             "details": a.details, "ip": a.ip_address} for a in db.scalars(q.limit(min(limit, 500)))]
