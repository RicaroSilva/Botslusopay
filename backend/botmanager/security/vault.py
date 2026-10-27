"""Cofre de credenciais (cifra simétrica Fernet: AES-128-CBC + HMAC-SHA256).

A chave (BM_VAULT_KEY) vem do ambiente/Docker secret, nunca da base de dados.
Rodar a chave: definir BM_VAULT_KEY_OLD com a antiga e correr
`python -m botmanager.cli rotate-vault-key`."""
from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from ..config import get_settings

# Campos secretos e campos públicos por tipo de credencial.
KINDS: dict[str, dict[str, list[str]]] = {
    "http_basic": {"public": ["username"], "secret": ["password"]},
    "http_bearer": {"public": [], "secret": ["token"]},
    "http_header": {"public": ["header_name"], "secret": ["value"]},
    "smtp": {"public": ["host", "port", "username", "from_address", "security"], "secret": ["password"]},
    "mssql": {"public": ["server", "port", "database", "username"], "secret": ["password"]},
}


class VaultError(Exception):
    pass


def _fernet() -> MultiFernet:
    s = get_settings()
    keys = [s.vault_key] + ([s.vault_key_old] if getattr(s, "vault_key_old", "") else [])
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys if k])
    except (ValueError, TypeError) as exc:
        raise VaultError("BM_VAULT_KEY inválida (tem de ser uma chave Fernet)") from exc


def split_fields(kind: str, data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = KINDS.get(kind)
    if spec is None:
        raise VaultError(f"tipo de credencial desconhecido: {kind}")
    unknown = set(data) - set(spec["public"]) - set(spec["secret"])
    if unknown:
        raise VaultError(f"campos não permitidos: {sorted(unknown)}")
    public = {k: data[k] for k in spec["public"] if k in data}
    secret = {k: data[k] for k in spec["secret"] if k in data}
    return public, secret


def encrypt(secret: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(secret).encode()).decode()


def decrypt(token: str) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:
        raise VaultError("não foi possível decifrar a credencial (chave errada?)") from exc


def rotate(token: str) -> str:
    return _fernet().rotate(token.encode()).decode()
