"""Cofre de credenciais (apenas administradores). Os segredos nunca saem da API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..flows.service import credential_in_use
from ..models import Credential, Role, User
from ..security import vault
from ..services.audit import audit
from .deps import client_ip, require_role

router = APIRouter(prefix="/api/admin/credentials", tags=["credentials"])
admin_only = require_role(Role.ADMIN)


class CredentialIn(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,79}$")
    kind: str
    description: str = Field(default="", max_length=300)
    fields: dict[str, Any]


class CredentialUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=300)
    fields: dict[str, Any] = {}  # segredos omitidos mantêm-se


def _out(c: Credential) -> dict[str, Any]:
    spec = vault.KINDS[c.kind]
    return {"id": c.id, "name": c.name, "kind": c.kind, "description": c.description,
            "public_fields": c.public_fields, "secret_fields": spec["secret"],
            "updated_at": c.updated_at.isoformat()}


@router.get("/kinds")
def kinds(user: User = Depends(admin_only)):
    return vault.KINDS


@router.get("")
def list_credentials(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [_out(c) for c in db.scalars(select(Credential).order_by(Credential.name))]


@router.post("", status_code=201)
def create_credential(body: CredentialIn, request: Request, user: User = Depends(admin_only),
                      db: Session = Depends(get_db)):
    if db.scalar(select(Credential.id).where(Credential.name == body.name)):
        raise HTTPException(409, "já existe uma credencial com este nome")
    try:
        public, secret = vault.split_fields(body.kind, body.fields)
        missing = [f for f in vault.KINDS[body.kind]["secret"] if not secret.get(f)]
        if missing:
            raise vault.VaultError(f"campos secretos em falta: {missing}")
        c = Credential(name=body.name, kind=body.kind, description=body.description, public_fields=public,
                       encrypted_data=vault.encrypt(secret), created_by=user.id)
    except vault.VaultError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.add(c)
    db.flush()
    audit(db, "user", user.username, "credential.created", "credential", c.id,
          details={"name": c.name, "kind": c.kind}, ip=client_ip(request))
    db.commit()
    return _out(c)


@router.put("/{cred_id}")
def update_credential(cred_id: str, body: CredentialUpdate, request: Request, user: User = Depends(admin_only),
                      db: Session = Depends(get_db)):
    c = db.get(Credential, cred_id)
    if c is None:
        raise HTTPException(404, "credencial não encontrada")
    try:
        public, secret = vault.split_fields(c.kind, body.fields)
        if secret:
            merged = {**vault.decrypt(c.encrypted_data), **{k: v for k, v in secret.items() if v}}
            c.encrypted_data = vault.encrypt(merged)
    except vault.VaultError as exc:
        raise HTTPException(422, str(exc)) from exc
    if public:
        c.public_fields = {**c.public_fields, **public}
    if body.description is not None:
        c.description = body.description
    audit(db, "user", user.username, "credential.updated", "credential", c.id,
          details={"name": c.name, "changed_public": sorted(public), "secret_changed": bool(secret)},
          ip=client_ip(request))
    db.commit()
    return _out(c)


@router.delete("/{cred_id}")
def delete_credential(cred_id: str, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    c = db.get(Credential, cred_id)
    if c is None:
        raise HTTPException(404, "credencial não encontrada")
    in_use = credential_in_use(db, c.name)
    if in_use:
        raise HTTPException(409, f"credencial usada pelos fluxos: {', '.join(in_use)}")
    audit(db, "user", user.username, "credential.deleted", "credential", c.id, details={"name": c.name},
          ip=client_ip(request))
    db.delete(c)
    db.commit()
    return {"ok": True}
