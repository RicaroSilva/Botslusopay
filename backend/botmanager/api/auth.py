from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User, utcnow
from ..security.passwords import hash_password, verify_password
from ..security.sessions import COOKIE_NAME, issue_session
from ..services.audit import audit
from .deps import client_ip, current_user
from .serializers import user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    now = utcnow()
    if user and user.locked_until and user.locked_until > now:
        audit(db, "user", body.username, "auth.login", "user", user.id, outcome="denied",
              details={"reason": "locked"}, ip=client_ip(request))
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "conta temporariamente bloqueada")
    ok = verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active or user.auth_source != "local":
        if user:
            user.failed_logins += 1
            if user.failed_logins >= s.login_max_failures:
                user.locked_until = now + timedelta(minutes=s.login_lockout_minutes)
                user.failed_logins = 0
        audit(db, "user", body.username[:120], "auth.login", "user", user.id if user else None, outcome="denied",
              ip=client_ip(request))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "credenciais inválidas")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    audit(db, "user", user.username, "auth.login", "user", user.id, ip=client_ip(request))
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        issue_session(user.id, user.token_version),
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        max_age=s.session_minutes * 60,
        path="/",
    )
    return user_out(user)


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.token_version += 1  # invalida sessões existentes
    audit(db, "user", user.username, "auth.logout", "user", user.id, ip=client_ip(request))
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, response: Response,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "password atual incorreta")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit(db, "user", user.username, "auth.password_changed", "user", user.id, ip=client_ip(request))
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}
