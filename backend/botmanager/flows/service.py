from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Bot, Credential, FlowVersion, User
from ..security import vault
from ..services.audit import audit
from .schema import FlowDefinition, referenced_credentials, validate_flow


def credential_kinds(db: Session) -> dict[str, str]:
    return {c.name: c.kind for c in db.scalars(select(Credential))}


class GroovyCompileError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("; ".join(f"linha {e.get('line')}: {e.get('message')}" for e in errors[:5]))


def groovy_tool(mode: str, code: str) -> dict[str, Any]:
    """Compila código Groovy sem o executar (no anfitrião isolado do worker). Levanta GroovyUnavailable se o
    Java/Groovy não estiver instalado neste servidor."""
    try:
        from lusopay_worker import groovy
    except ImportError as exc:
        raise RuntimeError("o pacote do worker (lusopay_worker) não está instalado neste servidor") from exc
    return groovy.run_tool(mode, code)


def check_groovy(code: str) -> dict[str, Any]:
    """{"checked": bool, "errors": [...], "reason": str}. Sem Java no servidor, a sintaxe só é verificada ao executar."""
    try:
        res = groovy_tool("check", code)
    except Exception as exc:  # noqa: BLE001 - indisponível: não bloqueia a gravação
        return {"checked": False, "errors": [], "reason": str(exc)}
    return {"checked": True, "errors": res.get("errors", []) if res.get("status") != "ok" else [], "reason": ""}


def validate(db: Session, raw: dict[str, Any], compile_groovy: bool = True) -> FlowDefinition:
    flow = validate_flow(raw, credential_kinds(db), get_settings().flow_allowed_hosts)
    if flow.language == "groovy" and compile_groovy:
        res = check_groovy(flow.code)
        if res["errors"]:
            raise GroovyCompileError(res["errors"])
    return flow


def dump_definition(flow: FlowDefinition) -> dict[str, Any]:
    d = flow.model_dump(mode="json", exclude_none=True)
    if flow.language == "flow":
        d.pop("code", None)
    else:
        d.pop("steps", None)
    return d


def save_version(db: Session, bot: Bot, raw: dict[str, Any], user: User, comment: str = "") -> FlowVersion:
    flow = validate(db, raw)
    last = db.scalar(select(FlowVersion.version).where(FlowVersion.bot_id == bot.id)
                     .order_by(FlowVersion.version.desc()).limit(1)) or 0
    fv = FlowVersion(bot_id=bot.id, version=last + 1, definition=dump_definition(flow),
                     comment=comment[:300], created_by=user.id)
    db.add(fv)
    bot.current_flow_version = fv.version
    db.flush()
    audit(db, "user", user.username, "flow.version_saved", "bot", bot.id,
          details={"key": bot.key, "version": fv.version, "comment": comment[:300]})
    return fv


def get_version(db: Session, bot: Bot, version: int | None) -> FlowVersion | None:
    if version is None:
        return None
    return db.scalar(select(FlowVersion).where(FlowVersion.bot_id == bot.id, FlowVersion.version == version))


def credentials_for_job(db: Session, definition: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Decifra apenas as credenciais referidas pelo fluxo (menor privilégio)."""
    flow = FlowDefinition.model_validate(definition)
    out: dict[str, dict[str, Any]] = {}
    for name in sorted(referenced_credentials(flow)):
        cred = db.scalar(select(Credential).where(Credential.name == name))
        if cred is None:
            raise vault.VaultError(f"credencial em falta: {name}")
        out[name] = {"kind": cred.kind, **cred.public_fields, **vault.decrypt(cred.encrypted_data)}
    return out


def credential_in_use(db: Session, name: str) -> list[str]:
    users = []
    for bot in db.scalars(select(Bot).where(Bot.adapter == "flow", Bot.current_flow_version.is_not(None))):
        fv = get_version(db, bot, bot.current_flow_version)
        if fv and name in referenced_credentials(FlowDefinition.model_validate(fv.definition)):
            users.append(bot.key)
    return users
