"""Consulta periódica do estado de um sistema externo por HTTP(S) GET.

Só hosts listados em BM_POLL_ALLOWED_HOSTS (proteção SSRF). Dispara quando o
valor extraído por 'json_path' (caminho simples a.b.0.c) é igual a 'equals'.
dedup_key = valor do campo 'dedup_path' (ex.: id/data do processo concluído),
para que o mesmo estado não dispare várias vezes. As credenciais, se
necessárias, são lidas de uma variável de ambiente do backend indicada em
'auth_header_env' — nunca guardadas na regra."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import TriggerRule
from ..services.audit import audit
from .base import FireResult, TriggerType, fire_rule


class PollHttpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    interval_seconds: int = Field(default=300, ge=60, le=86400)
    json_path: str
    equals: Any
    dedup_path: str
    auth_header_env: str | None = Field(default=None, pattern=r"^BM_POLL_[A-Z0-9_]+$")
    timeout_seconds: int = Field(default=15, ge=1, le=60)
    parameters: dict = {}

    @field_validator("url")
    @classmethod
    def _https_allowed(cls, v: str) -> str:
        parts = urlsplit(v)
        if parts.scheme != "https":
            raise ValueError("só https é permitido")
        if parts.hostname not in get_settings().poll_allowed_hosts:
            raise ValueError("host não autorizado em BM_POLL_ALLOWED_HOSTS")
        return v


def extract(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


class PollHttpTrigger(TriggerType):
    name = "poll_http"
    config_model = PollHttpConfig
    periodic = True
    http_client_factory = staticmethod(lambda timeout: httpx.Client(timeout=timeout, follow_redirects=False))

    @classmethod
    def initial_next_fire(cls, rule, now):
        return now

    @classmethod
    def evaluate(cls, db: Session, rule: TriggerRule, now: datetime) -> list[FireResult]:
        if rule.next_fire_at and rule.next_fire_at > now:
            return []
        cfg = PollHttpConfig.model_validate(rule.config)  # revalida host permitido
        rule.next_fire_at = now + timedelta(seconds=cfg.interval_seconds)
        headers = {"accept": "application/json"}
        if cfg.auth_header_env:
            value = os.environ.get(cfg.auth_header_env)
            if value:
                headers["Authorization"] = value
        try:
            with cls.http_client_factory(cfg.timeout_seconds) as client:
                resp = client.get(cfg.url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            rule.state = {**rule.state, "last_error": type(exc).__name__, "last_checked": now.isoformat()}
            audit(db, "system", "scheduler", "trigger.poll_error", "trigger_rule", rule.id, outcome="error",
                  details={"error": type(exc).__name__})
            return []
        rule.state = {**rule.state, "last_checked": now.isoformat(), "last_error": None}
        if extract(data, cfg.json_path) != cfg.equals:
            return []
        key = extract(data, cfg.dedup_path)
        if key in (None, ""):
            audit(db, "system", "scheduler", "trigger.poll_no_dedup_key", "trigger_rule", rule.id, outcome="error")
            return []
        return [fire_rule(db, rule, f"poll:{key}", {"matched": cfg.json_path}, actor="scheduler")]
