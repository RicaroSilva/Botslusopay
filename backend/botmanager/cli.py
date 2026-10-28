"""Comandos de administração:

  python -m botmanager.cli sync-registry
  python -m botmanager.cli create-user --username admin --role admin
  python -m botmanager.cli create-worker --name BOTSERVER1 --capabilities taskt_cli
  python -m botmanager.cli validate-registry
  python -m botmanager.cli import-flows [ficheiro.json ...]
  python -m botmanager.cli reset-password --username admin
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
    rp = sub.add_parser("reset-password", help="desbloqueia um utilizador e, opcionalmente, muda a password")
    rp.add_argument("--username", required=True)
    imp = sub.add_parser("import-flows", help="importa fluxos de bots/flows/*.json (ou ficheiros indicados)")
    imp.add_argument("files", nargs="*")
    imp.add_argument("--as-user", default="admin", help="utilizador registado como autor da versão")
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
        if args.cmd == "reset-password":
            u = db.scalar(select(User).where(User.username == args.username.strip().lower()))
            if u is None:
                print("utilizador não existe; utilizadores: "
                      + ", ".join(db.scalars(select(User.username))), file=sys.stderr)
                return 1
            pw = getpass.getpass("Nova password (Enter = manter a atual e só desbloquear): ")
            if pw:
                if len(pw) < 12:
                    print("a password tem de ter pelo menos 12 caracteres", file=sys.stderr)
                    return 1
                if pw != getpass.getpass("Repetir password: "):
                    print("as passwords não coincidem", file=sys.stderr)
                    return 1
                u.password_hash = hash_password(pw)
            u.failed_logins, u.locked_until = 0, None
            u.is_active = True
            audit(db, "system", "cli", "user.password_reset" if pw else "user.unlocked", "user", u.id,
                  details={"username": u.username})
            db.commit()
            print(f"{u.username} desbloqueado" + (" e password alterada" if pw else ""))
            return 0
        if args.cmd == "import-flows":
            import json
            from pathlib import Path

            from fastapi import HTTPException

            from .api.flows import FlowImport, import_flow
            from .config import REPO_ROOT

            user = db.scalar(select(User).where(User.username == args.as_user))
            if user is None:
                print(f"utilizador {args.as_user} não existe (use --as-user)", file=sys.stderr)
                return 1
            files = [Path(f) for f in args.files] or sorted((REPO_ROOT / "bots" / "flows").glob("*.json"))
            errors = 0
            for f in files:
                try:
                    bot, version, created = import_flow(db, FlowImport.model_validate_json(f.read_text(encoding="utf-8")), user)
                    db.commit()
                    print(f"OK    {bot.key:35} versão {version} ({'criado, desativado' if created else 'nova versão'})")
                except HTTPException as exc:
                    db.rollback()
                    errors += 1
                    print(f"ERRO  {f.name}: {exc.detail}", file=sys.stderr)
                except ValueError as exc:
                    db.rollback()
                    errors += 1
                    print(f"ERRO  {f.name}: {exc}", file=sys.stderr)
            return 1 if errors else 0
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
