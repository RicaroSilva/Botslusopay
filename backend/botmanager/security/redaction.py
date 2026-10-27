"""Redação de segredos em logs, detalhes de auditoria e resultados.

Aplicada no worker (antes de enviar) e novamente no backend (defesa em
profundidade). Os padrões cobrem os formatos encontrados nos scripts taskt
(cabeçalhos Basic, connection strings, passwords SMTP, linhas Config.txt).
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

REDACTED = "***REDACTED***"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization: Basic xxx / Bearer xxx
    (re.compile(r"(?i)\b(basic|bearer)\s+[A-Za-z0-9+/=._~-]{8,}"), r"\1 " + REDACTED),
    # password=..., pwd=..., senha: ..., secret=..., token=..., api_key=...
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|senha|secret|token|api[_-]?key|smtppass|v_SMTPPassword|v_ConnectionStringPassword)"
            r"(\s*[=:]\s*|\"\s*:\s*\"|='|=\")([^\s;,&\"'<>]+)"
        ),
        r"\1\2" + REDACTED,
    ),
    # Config.txt do taskt: "RPATaskt,<segredo>," e "smtpPass,<segredo>,"
    (re.compile(r"(?i)\b(RPATaskt|smtpPass),[^,\r\n]+"), r"\1," + REDACTED),
    # URLs com credenciais: https://user:pass@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1" + REDACTED + "@"),
]

SENSITIVE_KEYS = re.compile(r"(?i)(pass|pwd|senha|secret|token|authorization|api[_-]?key|credential|cookie)")


def redact_text(text: str, extra_secrets: Iterable[str] = ()) -> str:
    if not text:
        return text
    for secret in extra_secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, REDACTED)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_obj(value: Any, extra_secrets: Iterable[str] = ()) -> Any:
    """Redige recursivamente dicionários/listas: chaves sensíveis e valores textuais."""
    secrets = list(extra_secrets)
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and SENSITIVE_KEYS.search(k):
                out[k] = REDACTED
            else:
                out[k] = redact_obj(v, secrets)
        return out
    if isinstance(value, list):
        return [redact_obj(v, secrets) for v in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value
