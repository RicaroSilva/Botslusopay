"""Webhook / evento externo.

O emissor faz POST /api/hooks/{rule_id} com:
  X-BM-Event-Id: identificador único do evento (dedup)
  X-BM-Timestamp: epoch em segundos (janela de 5 minutos, anti-replay)
  X-BM-Signature: sha256=HMAC_SHA256(segredo, f"{timestamp}.{corpo}")
Também serve para "confirmação de conclusão de processo externo": o sistema
externo chama o webhook quando termina.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from pydantic import BaseModel, ConfigDict

from .base import TriggerType

MAX_SKEW_SECONDS = 300


class WebhookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    parameters: dict = {}


class WebhookTrigger(TriggerType):
    name = "webhook"
    config_model = WebhookConfig


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def verify(secret: str, timestamp: str | None, signature: str | None, body: bytes, now: float | None = None) -> bool:
    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs((now or time.time()) - ts) > MAX_SKEW_SECONDS:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)
