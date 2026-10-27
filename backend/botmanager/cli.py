"""Comandos de administração:

  python -m botmanager.cli sync-registry
  python -m botmanager.cli create-user --username admin --role admin
  python -m botmanager.cli create-worker --name BOTSERVER1 --capabilities taskt_cli
  python -m botmanager.cli validate-registry
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from .config import get_settings
from .db import session_factory
from .models import Role, User, Worker
from .registry.loader import load_registry, sync_registry
from .security.passwords import hash_password, hash_token, new_token
from .services.audit import audit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="botmanager")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync-registry")
    sub.add_parser("validate-registry")
    cu = sub.add_parser("create-user")
    cu.add_argument("--username", required=True)
    cu.add_argument("--role", choices=[r.value for r in Role], default="viewer")
    cu.add_argument("--display-name", default="")
    cw = sub.add_parser("create-worker")
    cw.add_argument("--name", required=True)
    cw.add_argument("--capabilities", default="taskt_cli")
    args = ap.parse_args(argv)
    s = get_settings()

    if args.cmd == "validate-registry":
        res = load_registry(s.registry_dirs)
        for d in res.definitions:
            print(f"OK    {d.key:45} {d.execution.adapter:16} validated={d.execution.validated}")
        for f, e in res.errors.items():
            print(f"ERRO  {f}: {e}", file=sys.stderr)
        return 1 if res.errors else 0

    with session_factory()() as db:
        if args.cmd == "sync-registry":
            res = sync_registry(db, s.registry_dirs, actor="cli")
            print(f"{len(res.definitions)} definições carregadas, {len(res.errors)} com erro")
            for f, e in res.errors.items():
                print(f"ERRO  {f}: {e}", file=sys.stderr)
            return 1 if res.errors else 0
        if args.cmd == "create-user":
            username = args.username.strip().lower()
            if db.scalar(select(User).where(User.username == username)):
                print("utilizador já existe", file=sys.stderr)
                return 1
            pw = getpass.getpass("Password (mín. 12 caracteres): ")
            if pw != getpass.getpass("Repetir password: "):
                print("as passwords não coincidem", file=sys.stderr)
                return 1
            u = User(username=username, display_name=args.display_name or username, role=Role(args.role),
                     password_hash=hash_password(pw))
            db.add(u)
            db.flush()
            audit(db, "system", "cli", "user.created", "user", u.id, details={"username": username, "role": args.role})
            db.commit()
            print(f"utilizador {username} criado ({args.role})")
            return 0
        if args.cmd == "create-worker":
            token = new_token()
            w = Worker(name=args.name, token_hash=hash_token(token),
                       capabilities=[c.strip() for c in args.capabilities.split(",") if c.strip()])
            db.add(w)
            db.flush()
            audit(db, "system", "cli", "worker.created", "worker", w.id, details={"name": args.name})
            db.commit()
            print("Token do worker (guarde-o agora; não volta a ser mostrado):")
            print(token)
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
