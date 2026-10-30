"""Sessões: JWT assinado (HS256) num cookie httpOnly + SameSite=Strict.

O token inclui token_version do utilizador: incrementar invalida todas as
sessões (logout global, desativação, mudança de função)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from ..config import get_settings

COOKIE_NAME = "bm_session"
ALGORITHM = "HS256"


def issue_session(user_id: str, token_version: int) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.session_minutes)).timestamp()),
        "typ": "session",
    }
    return jwt.encode(payload, s.secret_key, algorithm=ALGORITHM)


def decode_session(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "session":
        return None
    return payload
