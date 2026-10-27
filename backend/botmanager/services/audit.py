from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditEvent
from ..security.redaction import redact_obj


def audit(
    db: Session,
    actor_type: str,
    actor_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEvent:
    """Regista um evento de auditoria (sem commit; segue a transação do chamador)."""
    ev = AuditEvent(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        details=redact_obj(details or {}),
        ip_address=ip,
    )
    db.add(ev)
    return ev
