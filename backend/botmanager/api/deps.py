from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Bot, Permission, Role, User, Worker, utcnow
from ..security.passwords import hash_token
from ..security.permissions import has_bot_permission
from ..security.sessions import COOKIE_NAME, decode_session
from ..services.audit import audit

ROLE_ORDER = [Role.VIEWER, Role.OPERATOR, Role.APPROVER, Role.ADMIN]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    payload = decode_session(token) if token else None
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "autenticação necessária")
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active or user.token_version != payload.get("ver"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão inválida")
    # CSRF: cookie SameSite=Strict + cabeçalho obrigatório em pedidos que alteram estado.
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-requested-with") != "botmanager":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cabeçalho X-Requested-With em falta")
    return user


def require_role(minimum: Role) -> Callable[..., User]:
    def dep(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        if ROLE_ORDER.index(user.role) < ROLE_ORDER.index(minimum):
            audit(db, "user", user.username, "access.denied", "endpoint", request.url.path, outcome="denied",
                  details={"required_role": minimum.value}, ip=client_ip(request))
            db.commit()
            raise HTTPException(status.HTTP_403_FORBIDDEN, "permissão insuficiente")
        return user

    return dep


def get_bot_or_404(db: Session, key: str) -> Bot:
    bot = db.scalar(select(Bot).where(Bot.key == key))
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bot não encontrado")
    return bot


def ensure_bot_permission(db: Session, user: User, bot: Bot, perm: Permission, request: Request) -> None:
    if not has_bot_permission(db, user, bot, perm):
        audit(db, "user", user.username, f"bot.{perm.value}.denied", "bot", bot.id, outcome="denied",
              ip=client_ip(request))
        db.commit()
        # 404 para consulta (não revela existência), 403 nos restantes
        if perm == Permission.VIEW:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "bot não encontrado")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "sem permissão para esta operação")


def current_worker(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Worker:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token de worker em falta")
    token = authorization.removeprefix("Bearer ").strip()
    worker = db.scalar(select(Worker).where(Worker.token_hash == hash_token(token)))
    if worker is None or not worker.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "worker inválido")
    worker.last_seen_at = utcnow()
    return worker
