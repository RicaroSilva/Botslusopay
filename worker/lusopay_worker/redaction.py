"""Redação de segredos (cópia intencional de botmanager.security.redaction:
o worker não depende do pacote do backend). Os testes garantem paridade."""
from __future__ import annotations

import re
from collections.abc import Iterable

REDACTED = "***REDACTED***"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(basic|bearer)\s+[A-Za-z0-9+/=._~-]{8,}"), r"\1 " + REDACTED),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|senha|secret|token|api[_-]?key|smtppass|v_SMTPPassword|v_ConnectionStringPassword)"
            r"(\s*[=:]\s*|\"\s*:\s*\"|='|=\")([^\s;,&\"'<>]+)"
        ),
        r"\1\2" + REDACTED,
    ),
    (re.compile(r"(?i)\b(RPATaskt|smtpPass),[^,\r\n]+"), r"\1," + REDACTED),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1" + REDACTED + "@"),
]


def redact_text(text: str, extra_secrets: Iterable[str] = ()) -> str:
    if not text:
        return text
    for secret in extra_secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, REDACTED)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text
