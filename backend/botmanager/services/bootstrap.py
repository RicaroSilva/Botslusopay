"""Arranque em contentores: cria (ou atualiza) o worker dos fluxos nativos e o
primeiro administrador a partir de variáveis de ambiente / Docker secrets."""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Role, User, Worker
from ..security.passwords import hash_password, hash_token
from .audit import audit

log = logging.getLogger("botmanager.bootstrap")
RUNNER_NAME = "flow-runner"


def bootstrap(db: Session) -> None:
    s = get_settings()
    if s.bootstrap_runner_token:
        if len(s.bootstrap_runner_token) < 32:
            raise ValueError("BM_BOOTSTRAP_RUNNER_TOKEN deve ter pelo menos 32 caracteres")
        h = hash_token(s.bootstrap_runner_token)
        w = db.scalar(select(Worker).where(Worker.name == RUNNER_NAME))
        if w is None:
            db.add(Worker(name=RUNNER_NAME, token_hash=h, capabilities=["flow"]))
            audit(db, "system", "bootstrap", "worker.created", "worker", RUNNER_NAME)
        elif w.token_hash != h:
            w.token_hash = h
            audit(db, "system", "bootstrap", "worker.token_rotated", "worker", w.id)
    if s.bootstrap_admin_username and s.bootstrap_admin_password:
        if not db.scalar(select(func.count()).select_from(User)):
            u = User(username=s.bootstrap_admin_username.lower(), display_name="Administrador", role=Role.ADMIN,
                     password_hash=hash_password(s.bootstrap_admin_password))
            db.add(u)
            db.flush()
            audit(db, "system", "bootstrap", "user.created", "user", u.id, details={"username": u.username})
            log.warning("administrador inicial criado; altere a password e remova BM_BOOTSTRAP_ADMIN_PASSWORD")
    db.commit()
