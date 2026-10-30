from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import TriggerRule
from ..services.audit import audit
from ..services.settings import triggers_paused
from ..triggers import fire_rule
from ..triggers.webhook import verify

router = APIRouter(prefix="/api/hooks", tags=["webhooks"])


@router.post("/{rule_id}")
async def receive(
    rule_id: str,
    request: Request,
    response: Response,
    x_bm_event_id: str | None = Header(default=None),
    x_bm_timestamp: str | None = Header(default=None),
    x_bm_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    body = await request.body()
    if len(body) > 64 * 1024:
        raise HTTPException(413, "corpo demasiado grande")
    rule = db.get(TriggerRule, rule_id)
    # Resposta genérica: não revela se a regra existe.
    if rule is None or rule.trigger_type != "webhook" or not rule.enabled or not rule.secret or not verify(
        rule.secret, x_bm_timestamp, x_bm_signature, body
    ):
        audit(db, "webhook", request.client.host if request.client else None, "webhook.rejected", "trigger_rule",
              rule_id, outcome="denied")
        db.commit()
        raise HTTPException(401, "pedido não autorizado")
    if not x_bm_event_id or len(x_bm_event_id) > 200:
        raise HTTPException(400, "X-BM-Event-Id obrigatório")
    if triggers_paused(db):
        raise HTTPException(503, "disparos automáticos em pausa")
    res = fire_rule(db, rule, f"webhook:{x_bm_event_id}", {"event_id": x_bm_event_id}, actor="webhook")
    db.commit()
    response.status_code = 202 if res.outcome == "accepted" else 200
    return {"outcome": res.outcome, "run_id": res.run_id}
