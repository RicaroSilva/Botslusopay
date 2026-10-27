from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Setting


def get_setting(db: Session, key: str, default=None):
    st = db.get(Setting, key)
    return st.value if st is not None else default


def triggers_paused(db: Session) -> bool:
    return bool(get_setting(db, "pause_automatic_triggers", False))
