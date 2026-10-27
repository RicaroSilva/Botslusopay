"""Autorização. Avaliada SEMPRE no backend.

Regras:
* admin tem todas as permissões.
* Para cada bot, o registo YAML define que funções têm cada permissão
  (definition.permissions). Uma função superior herda as inferiores apenas
  se constar da lista — a lista é explícita para evitar surpresas.
* Concessões individuais (tabela bot_permissions) acrescentam permissões.
* Um utilizador inativo não tem permissões.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Bot, BotPermission, Permission, Role, User

DEFAULT_PERMISSIONS: dict[str, list[str]] = {
    Permission.VIEW.value: [Role.VIEWER.value, Role.OPERATOR.value, Role.APPROVER.value],
    Permission.EXECUTE.value: [Role.OPERATOR.value],
    Permission.APPROVE.value: [Role.APPROVER.value],
    Permission.CONFIGURE.value: [],
}


def role_grants(bot: Bot, permission: Permission) -> list[str]:
    perms = bot.definition.get("permissions") or DEFAULT_PERMISSIONS
    return list(perms.get(permission.value, DEFAULT_PERMISSIONS[permission.value]))


def has_bot_permission(db: Session, user: User, bot: Bot, permission: Permission) -> bool:
    if not user.is_active:
        return False
    if user.role == Role.ADMIN:
        return True
    if user.role.value in role_grants(bot, permission):
        return True
    explicit = db.scalar(
        select(BotPermission.id).where(
            BotPermission.bot_id == bot.id,
            BotPermission.user_id == user.id,
            BotPermission.permission == permission,
        )
    )
    if explicit is not None:
        return True
    # Quem pode executar/aprovar/configurar também pode consultar.
    if permission == Permission.VIEW:
        return any(
            has_bot_permission(db, user, bot, p) for p in (Permission.EXECUTE, Permission.APPROVE, Permission.CONFIGURE)
        )
    return False


def user_bot_permissions(db: Session, user: User, bot: Bot) -> list[str]:
    return [p.value for p in Permission if has_bot_permission(db, user, bot, p)]
