"""Fluxos nativos: criados e editados na aplicação, executados pelo flow runner."""
from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..flows import service
from ..flows.schema import STEP_TYPES
from ..models import Availability, Bot, FlowVersion, Permission, Role, User
from ..registry.loader import definition_hash
from ..registry.schema import BotDefinition, KEY_RE
from ..services.audit import audit
from .deps import client_ip, current_user, ensure_bot_permission, get_bot_or_404, require_role
from .serializers import bot_out

router = APIRouter(prefix="/api/flows", tags=["flows"])


class FlowMeta(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=80)
    risk_level: Literal["low", "medium", "high"] = "medium"
    timeout_seconds: int = Field(default=1800, ge=30, le=86400)
    triggers_allowed: list[str] = ["manual"]
    requires_approval: bool | None = None  # None = exigir em risco elevado
    concurrency: Literal["single", "parallel"] = "single"
    external_effects: list[str] = []
    prerequisites: list[str] = []


class FlowCreate(FlowMeta):
    key: str
    definition: dict[str, Any]
    comment: str = Field(default="versão inicial", max_length=300)


class FlowSave(BaseModel):
    definition: dict[str, Any]
    comment: str = Field(default="", max_length=300)


def _bot_definition(key: str, meta: FlowMeta) -> BotDefinition:
    perms = {"view": ["viewer", "operator", "approver"], "execute": ["operator"]}
    requires_approval = meta.requires_approval if meta.requires_approval is not None else meta.risk_level == "high"
    if meta.risk_level == "high" or requires_approval:
        perms["approve"] = ["approver"]
    return BotDefinition.model_validate({
        "key": key, "name": meta.name, "description": meta.description, "category": meta.category,
        "risk_level": meta.risk_level,
        "execution": {"adapter": "flow", "script": f"flows/{key}", "validated": True},
        "external_effects": meta.external_effects, "prerequisites": meta.prerequisites,
        "concurrency": {"policy": meta.concurrency, "exclusive_resources": []},
        "timeout_seconds": meta.timeout_seconds, "success_detection": {"method": "flow"},
        "triggers_allowed": meta.triggers_allowed,
        "requires_approval": requires_approval,
        "permissions": perms,
    })


def _apply_definition(bot: Bot, defn: BotDefinition) -> None:
    bot.name, bot.description, bot.category = defn.name, defn.description, defn.category
    bot.risk_level, bot.adapter, bot.project_ref = defn.risk_level, "flow", defn.execution.script
    bot.definition = defn.model_dump(mode="json")
    bot.definition_hash = definition_hash(defn)


def _flow_bot(db: Session, key: str) -> Bot:
    bot = get_bot_or_404(db, key)
    if bot.adapter != "flow":
        raise HTTPException(404, "não é um fluxo nativo")
    return bot


@router.get("/step-types")
def step_types(user: User = Depends(current_user)):
    return STEP_TYPES


@router.get("/credential-names")
def credential_names(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Nomes e tipos das credenciais (sem quaisquer dados) para o editor de fluxos."""
    from ..models import Credential

    return [{"name": c.name, "kind": c.kind, "description": c.description}
            for c in db.scalars(select(Credential).order_by(Credential.name))]


@router.post("", status_code=201)
def create_flow(body: FlowCreate, request: Request, user: User = Depends(require_role(Role.ADMIN)),
                db: Session = Depends(get_db)):
    if not KEY_RE.match(body.key):
        raise HTTPException(422, "chave inválida: 3-80 caracteres [a-z0-9-]")
    if db.scalar(select(Bot.id).where(Bot.key == body.key)):
        raise HTTPException(409, "já existe um bot com esta chave")
    try:
        defn = _bot_definition(body.key, body)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    bot = Bot(key=body.key, source="ui", availability=Availability.AVAILABLE, enabled=False, name="", project_ref="",
              adapter="flow")
    _apply_definition(bot, defn)
    db.add(bot)
    db.flush()
    try:
        service.save_version(db, bot, body.definition, user, body.comment)
    except (ValidationError, ValueError) as exc:
        db.rollback()
        raise HTTPException(422, f"fluxo inválido: {exc}") from exc
    audit(db, "user", user.username, "flow.created", "bot", bot.id, details={"key": bot.key}, ip=client_ip(request))
    db.commit()
    return bot_out(bot, full=True)


class FlowImport(BaseModel):
    """Formato dos ficheiros em bots/flows/*.json."""

    key: str
    name: str
    description: str = ""
    category: str = ""
    risk_level: Literal["low", "medium", "high"] = "medium"
    timeout_seconds: int = 1800
    triggers_allowed: list[str] = ["manual"]
    requires_approval: bool | None = None  # None = exigir em risco elevado
    concurrency: Literal["single", "parallel"] = "single"
    external_effects: list[str] = []
    prerequisites: list[str] = []
    source_bot: str = ""
    migration_notes: list[str] = []
    definition: dict[str, Any]
    # conteúdo inicial dos ficheiros persistentes (base64); não substitui ficheiros que já existam
    persistent_contents: dict[str, str] = {}


def import_flow(db: Session, body: FlowImport, user: User) -> tuple[Bot, int, bool]:
    """Cria o fluxo (desativado) ou grava uma nova versão se já existir. Devolve (bot, versão, criado)."""
    meta = FlowMeta(**{k: getattr(body, k) for k in FlowMeta.model_fields})
    notes = [f"Migrado de: {body.source_bot}"] if body.source_bot else []
    meta.prerequisites = [*meta.prerequisites, *notes, *body.migration_notes]
    bot = db.scalar(select(Bot).where(Bot.key == body.key))
    if bot is not None and bot.adapter != "flow":
        raise HTTPException(409, "a chave pertence a um bot do registo (taskt/OpenBots)")
    try:
        defn = _bot_definition(body.key, meta)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    created = bot is None
    if created:
        if not KEY_RE.match(body.key):
            raise HTTPException(422, "chave inválida")
        bot = Bot(key=body.key, source="ui", availability=Availability.AVAILABLE, enabled=False, name="",
                  project_ref="", adapter="flow")
        db.add(bot)
    _apply_definition(bot, defn)
    db.flush()
    try:
        fv = service.save_version(db, bot, body.definition, user, "importado" + (f" de {body.source_bot}" if body.source_bot else ""))
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, f"fluxo inválido: {exc}") from exc
    _initial_files(db, bot, fv.definition, body.persistent_contents, user)
    audit(db, "user", user.username, "flow.imported", "bot", bot.id, details={"key": bot.key, "version": fv.version})
    return bot, fv.version, created


def _initial_files(db: Session, bot: Bot, definition: dict[str, Any], contents: dict[str, str], user: User) -> None:
    import base64
    import binascii

    from ..models import FlowFile

    declared = set(definition.get("persistent_files") or [])
    for name, b64 in contents.items():
        if name not in declared:
            continue
        if db.scalar(select(FlowFile.id).where(FlowFile.bot_id == bot.id, FlowFile.name == name)):
            continue  # já existe: mantém o estado atual (ex.: reimportação)
        try:
            data = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, f"conteúdo inválido para {name}") from exc
        if len(data) > FLOW_FILE_MAX_BYTES:
            raise HTTPException(413, f"{name} demasiado grande (máx. 5 MB)")
        save_flow_file(db, bot, name, data, f"import:{user.username}")


@router.post("/import")
def import_flow_endpoint(body: FlowImport, user: User = Depends(require_role(Role.ADMIN)), db: Session = Depends(get_db)):
    bot, version, created = import_flow(db, body, user)
    db.commit()
    return {"key": bot.key, "version": version, "created": created, "enabled": bot.enabled}


class ConvertIn(BaseModel):
    filename: str = Field(min_length=1, max_length=300)
    content_b64: str = Field(max_length=70_000_000)
    test_email: str = Field(default="", max_length=254)


@router.post("/convert")
def convert_robot(body: ConvertIn, user: User = Depends(require_role(Role.ADMIN)), db: Session = Depends(get_db)):
    """Converte um robô taskt/OpenBots num fluxo (pré-visualização; não grava nada)."""
    import base64
    import binascii

    from ..flows.converters import convert, read_robot
    from ..flows.converters.readers import RobotFormatError
    from ..flows.schema import validate_flow
    from ..models import Credential

    try:
        data = base64.b64decode(body.content_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "conteúdo inválido") from exc
    try:
        if body.filename.lower().endswith(".zip") or data[:2] == b"PK":
            from ..flows.converters.batch import split_robots

            robots = split_robots(data)
            if len(robots) > 1:
                raise HTTPException(422, f"Este .zip tem {len(robots)} robôs. Use o cartão 'Importar vários robôs de uma "
                                         "vez', que cria um fluxo para cada um.")
        result = convert(read_robot(data, body.filename), test_email=body.test_email)
    except RobotFormatError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:  # valida a estrutura assumindo que as credenciais referidas existem
        validate_flow(result.definition, result.credentials, [])
        valid, error = True, None
    except (ValidationError, ValueError) as exc:
        valid, error = False, str(exc)[:1000]
    existing = {c.name: c.kind for c in db.scalars(select(Credential))}
    out = result.as_dict()
    out["credentials"] = [{"name": n, "kind": k, "exists": existing.get(n) == k} for n, k in result.credentials.items()]
    out["valid"], out["validation_error"] = valid, error
    out["key_taken"] = db.scalar(select(Bot.id).where(Bot.key == result.key)) is not None
    audit(db, "user", user.username, "flow.converted", "file", body.filename[:120], details={"stats": result.stats})
    db.commit()
    return out


class BatchIn(BaseModel):
    content_b64: str = Field(max_length=140_000_000)
    test_email: str = Field(default="", max_length=254)
    approval_for_high_risk: bool = True


@router.post("/import-batch")
def import_batch(body: BatchIn, user: User = Depends(require_role(Role.ADMIN)), db: Session = Depends(get_db)):
    """Converte e importa todos os robôs de um .zip. Cada fluxo entra desativado; os que precisam de credenciais
    ainda não criadas ficam de fora (crie-as e volte a importar: os já importados recebem uma nova versão)."""
    import base64
    import binascii

    from ..flows.converters import convert, read_robot
    from ..flows.converters.batch import split_robots
    from ..flows.converters.readers import RobotFormatError
    from ..models import Credential

    try:
        robots = split_robots(base64.b64decode(body.content_b64, validate=True))
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "conteúdo inválido") from exc
    except RobotFormatError as exc:
        raise HTTPException(422, str(exc)) from exc
    existing = {c.name: c.kind for c in db.scalars(select(Credential))}
    results = []
    for filename, data in robots:
        item: dict[str, Any] = {"file": filename}
        try:
            res = convert(read_robot(data, filename), test_email=body.test_email)
        except RobotFormatError as exc:
            results.append({**item, "status": "erro", "error": str(exc)})
            continue
        item.update(key=res.key, name=res.name, stats=res.stats, risk_level=res.risk_level,
                    persistent_files=res.definition.get("persistent_files", []),
                    files_loaded=sorted(res.data_files))
        missing = [n for n, k in res.credentials.items() if existing.get(n) != k]
        if missing:
            results.append({**item, "status": "faltam_credenciais", "missing_credentials": missing})
            continue
        problems = [r for r in res.report if r.level in ("nao_convertivel", "aproximado")]
        imp = FlowImport(
            key=res.key, name=res.name, category="Importado", risk_level=res.risk_level, timeout_seconds=7200,
            requires_approval=body.approval_for_high_risk and res.risk_level == "high",
            description=f"Convertido automaticamente de {filename} ({res.source_format}). Rever antes de usar.",
            source_bot=filename, definition=res.definition,
            migration_notes=[f"Conversão: {res.stats.get('convertido', 0)} convertidos, {res.stats.get('aproximado', 0)} "
                             f"aproximados, {res.stats.get('nao_convertivel', 0)} não convertíveis.",
                             *[f"Linha {r.line} ({r.command}): {r.message}" for r in problems[:20]]],
            persistent_contents={n: base64.b64encode(d).decode() for n, d in res.data_files.items()})
        try:
            with db.begin_nested():
                bot, version, created = import_flow(db, imp, user)
        except HTTPException as exc:
            results.append({**item, "status": "erro", "error": str(exc.detail)[:500]})
            continue
        results.append({**item, "status": "criado" if created else "nova_versao", "version": version})
    audit(db, "user", user.username, "flow.batch_imported", "file", "batch",
          details={"robots": len(robots), "imported": sum(r["status"] in ("criado", "nova_versao") for r in results)})
    db.commit()
    return results


@router.delete("/{key}")
def delete_flow(key: str, request: Request, user: User = Depends(require_role(Role.ADMIN)), db: Session = Depends(get_db)):
    """Elimina um fluxo. Com histórico de execuções fica arquivado (escondido), para manter a auditoria."""
    from ..models import Run

    bot = _flow_bot(db, key)
    active = db.scalar(select(Run.id).where(Run.bot_id == bot.id, Run.status.in_(["PENDING", "WAITING_APPROVAL", "QUEUED", "RUNNING"])))
    if active:
        raise HTTPException(409, "o fluxo tem uma execução em curso")
    has_runs = db.scalar(select(Run.id).where(Run.bot_id == bot.id).limit(1)) is not None
    if has_runs:
        bot.enabled, bot.in_registry = False, False
        from ..models import TriggerRule

        for r in db.scalars(select(TriggerRule).where(TriggerRule.bot_id == bot.id)):
            r.enabled = False
        outcome = "archived"
    else:
        db.delete(bot)
        outcome = "deleted"
    audit(db, "user", user.username, "flow.deleted", "bot", bot.id, details={"key": key, "result": outcome},
          ip=client_ip(request))
    db.commit()
    return {"result": outcome}


# ------------------------------------------------------------------ ficheiros persistentes

FLOW_FILE_MAX_BYTES = 5 * 1024 * 1024


class FlowFileIn(BaseModel):
    content_b64: str = Field(max_length=8_000_000)


def _check_file_name(name: str) -> str:
    from ..flows.schema import FILE_NAME_RE

    if not FILE_NAME_RE.match(name) or name.startswith(".") or ".." in name:
        raise HTTPException(422, "nome de ficheiro inválido")
    return name


def _declared_files(db: Session, bot: Bot) -> list[str]:
    fv = service.get_version(db, bot, bot.current_flow_version)
    return list((fv.definition if fv else {}).get("persistent_files") or [])


@router.get("/{key}/files")
def list_flow_files(key: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..models import FlowFile

    bot = _flow_bot(db, key)
    ensure_bot_permission(db, user, bot, Permission.VIEW, request)
    stored = {f.name: f for f in db.scalars(select(FlowFile).where(FlowFile.bot_id == bot.id))}
    declared = _declared_files(db, bot)
    out = []
    for name in sorted(set(declared) | set(stored)):
        f = stored.get(name)
        out.append({"name": name, "declared": name in declared, "exists": f is not None,
                    "size_bytes": len(f.content) if f else 0, "updated_at": f.updated_at.isoformat() if f else None,
                    "updated_by": f.updated_by if f else None, "has_previous": bool(f and f.previous_content is not None)})
    return out


@router.get("/{key}/files/{name}")
def download_flow_file(key: str, name: str, request: Request, previous: bool = False,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    from urllib.parse import quote

    from fastapi import Response

    from ..models import FlowFile

    bot = _flow_bot(db, key)
    ensure_bot_permission(db, user, bot, Permission.VIEW, request)
    f = db.scalar(select(FlowFile).where(FlowFile.bot_id == bot.id, FlowFile.name == name))
    data = (f.previous_content if previous else f.content) if f else None
    if data is None:
        raise HTTPException(404, "ficheiro não encontrado")
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.put("/{key}/files/{name}")
def put_flow_file(key: str, name: str, body: FlowFileIn, request: Request, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    import base64
    import binascii

    bot = _flow_bot(db, key)
    ensure_bot_permission(db, user, bot, Permission.CONFIGURE, request)
    _check_file_name(name)
    try:
        data = base64.b64decode(body.content_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "conteúdo inválido") from exc
    if len(data) > FLOW_FILE_MAX_BYTES:
        raise HTTPException(413, "ficheiro demasiado grande (máx. 5 MB)")
    from ..models import Run

    if db.scalar(select(Run.id).where(Run.bot_id == bot.id, Run.status == "RUNNING")):
        raise HTTPException(409, "o fluxo está em execução; aguarde que termine")
    save_flow_file(db, bot, name, data, f"user:{user.username}")
    audit(db, "user", user.username, "flow.file_updated", "bot", bot.id, details={"file": name, "size": len(data)},
          ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.delete("/{key}/files/{name}")
def delete_flow_file(key: str, name: str, request: Request, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    from ..models import FlowFile

    bot = _flow_bot(db, key)
    ensure_bot_permission(db, user, bot, Permission.CONFIGURE, request)
    f = db.scalar(select(FlowFile).where(FlowFile.bot_id == bot.id, FlowFile.name == name))
    if f is None:
        raise HTTPException(404, "ficheiro não encontrado")
    from ..models import Run

    if db.scalar(select(Run.id).where(Run.bot_id == bot.id, Run.status == "RUNNING")):
        raise HTTPException(409, "o fluxo está em execução; aguarde que termine")
    db.delete(f)
    audit(db, "user", user.username, "flow.file_deleted", "bot", bot.id, details={"file": name}, ip=client_ip(request))
    db.commit()
    return {"ok": True}


def save_flow_file(db: Session, bot: Bot, name: str, data: bytes, who: str) -> bool:
    """Grava (guardando a versão anterior). Devolve False se o conteúdo não mudou."""
    import hashlib

    from ..models import FlowFile

    sha = hashlib.sha256(data).hexdigest()
    f = db.scalar(select(FlowFile).where(FlowFile.bot_id == bot.id, FlowFile.name == name))
    if f is None:
        db.add(FlowFile(bot_id=bot.id, name=name, content=data, sha256=sha, updated_by=who))
        return True
    if f.sha256 == sha:
        return False
    f.previous_content, f.content, f.sha256, f.updated_by = f.content, data, sha, who
    return True


@router.get("/{key}")
def get_flow(key: str, request: Request, version: int | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    bot = _flow_bot(db, key)
    ensure_bot_permission(db, user, bot, Permission.VIEW, request)
    fv = service.get_version(db, bot, version or bot.current_flow_version)
    versions = db.scalars(select(FlowVersion).where(FlowVersion.bot_id == bot.id).order_by(FlowVersion.version.desc()))
    names = {u.id: u.username for u in db.scalars(select(User))}
    return {
        "bot": bot_out(bot, full=True),
        "current_version": bot.current_flow_version,
        "version": fv.version if fv else None,
        "definition": fv.definition if fv else None,
        "versions": [{"version": v.version, "comment": v.comment, "created_at": v.created_at.isoformat(),
                      "created_by": names.get(v.created_by or "", None)} for v in versions],
    }


@router.post("/validate")
def validate_flow(body: FlowSave, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        flow = service.validate(db, body.definition)
    except service.GroovyCompileError as exc:
        return {"valid": False, "error": str(exc), "errors": exc.errors}
    except (ValidationError, ValueError) as exc:
        return {"valid": False, "error": str(exc), "errors": _line_errors(str(exc))}
    out: dict[str, Any] = {"valid": True}
    if flow.language == "groovy":
        from ..flows.schema import groovy_credentials

        out["credentials"] = sorted(groovy_credentials(flow.code))
    return out


def _line_errors(msg: str) -> list[dict[str, Any]]:
    m = re.match(r"linha (\d+): (.*)", msg)
    return [{"line": int(m.group(1)), "col": 0, "message": m.group(2)}] if m else [{"line": 0, "col": 0, "message": msg}]


class CodeIn(BaseModel):
    code: str = Field(max_length=300_000)


@router.post("/check-code")
def check_code(body: CodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Verifica código Groovy sem o executar: sintaxe, regras de segurança e credenciais."""
    from ..flows.schema import groovy_credentials

    errors: list[dict[str, Any]] = []
    try:
        service.validate(db, {"language": "groovy", "code": body.code or " "}, compile_groovy=False)
    except (ValidationError, ValueError) as exc:
        errors += _line_errors(str(exc).split("\n")[-1] if isinstance(exc, ValidationError) else str(exc))
    res = service.check_groovy(body.code) if body.code.strip() else {"checked": True, "errors": [], "reason": ""}
    errors += res["errors"]
    existing = service.credential_kinds(db)
    return {"checked": res["checked"], "reason": res["reason"], "errors": errors,
            "credentials": [{"name": n, "exists": n in existing, "kind": existing.get(n)}
                            for n in sorted(groovy_credentials(body.code))]}


class TransformIn(BaseModel):
    definition: dict[str, Any]
    target: Literal["flow", "groovy"]
    force: bool = False


def _transform(definition: dict[str, Any], target: str, force: bool) -> dict[str, Any]:
    from ..flows.groovy_convert import flow_to_groovy, groovy_to_flow
    from ..flows.schema import FlowDefinition

    try:
        current = FlowDefinition.model_validate(definition)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, f"definição inválida: {exc}") from exc
    if current.language == target:
        raise HTTPException(422, f"o robô já está no formato {target}")
    if target == "groovy":
        new_def, report = flow_to_groovy(service.dump_definition(current))
    else:
        try:
            ast = service.groovy_tool("ast", current.code)
        except Exception as exc:  # noqa: BLE001 - Java/Groovy indisponível no servidor
            raise HTTPException(503, f"a conversão de Groovy para fluxo precisa do Java/Groovy no servidor: {exc}") from exc
        if ast.get("status") != "ok":
            raise HTTPException(422, "o código tem erros: " + "; ".join(
                f"linha {e.get('line')}: {e.get('message')}" for e in ast.get("errors", [])[:5]))
        new_def, report = groovy_to_flow(service.dump_definition(current), ast, force)
    return {"definition": new_def, "report": report.items, "complete": report.complete}


@router.post("/transform")
def transform(body: TransformIn, user: User = Depends(current_user)):
    """Converte entre fluxo e Groovy. Não grava nada: o editor mostra o resultado e o relatório; o utilizador
    revê e grava como nova versão (as versões anteriores continuam disponíveis)."""
    return _transform(body.definition, body.target, body.force)


class DuplicateIn(BaseModel):
    key: str
    name: str = Field(min_length=3, max_length=200)
    target: Literal["flow", "groovy"] | None = None  # converter ao duplicar
    force: bool = False


@router.post("/{key}/duplicate", status_code=201)
def duplicate_flow(key: str, body: DuplicateIn, request: Request, user: User = Depends(require_role(Role.ADMIN)),
                   db: Session = Depends(get_db)):
    """Novo robô (desativado) a partir da versão em uso de outro, opcionalmente noutro formato."""
    bot = _flow_bot(db, key)
    fv = service.get_version(db, bot, bot.current_flow_version)
    if fv is None:
        raise HTTPException(409, "o robô não tem versões")
    definition, report = fv.definition, []
    if body.target and body.target != definition.get("language", "flow"):
        res = _transform(definition, body.target, body.force)
        if not res["complete"] and not body.force:
            raise HTTPException(422, {"message": "conversão incompleta", "report": res["report"]})
        definition, report = res["definition"], res["report"]
    meta = FlowMeta(**{k: v for k, v in bot.definition.items() if k in FlowMeta.model_fields
                       and k not in ("concurrency",)})
    meta.name = body.name
    meta.concurrency = (bot.definition.get("concurrency") or {}).get("policy", "single")
    created = create_flow(FlowCreate(**meta.model_dump(), key=body.key, definition=definition,
                                     comment=f"duplicado de {key} v{fv.version}"), request, user, db)
    created["report"] = report
    return created


@router.put("/{key}")
def save_flow(key: str, body: FlowSave, request: Request, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    bot = _flow_bot(db, key)
    ensure_bot_permission(db, user, bot, Permission.CONFIGURE, request)
    try:
        fv = service.save_version(db, bot, body.definition, user, body.comment)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, f"fluxo inválido: {exc}") from exc
    db.commit()
    return {"version": fv.version}


@router.patch("/{key}")
def update_meta(key: str, body: FlowMeta, request: Request, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    bot = _flow_bot(db, key)
    ensure_bot_permission(db, user, bot, Permission.CONFIGURE, request)
    if body.risk_level == "high" and body.requires_approval is False and user.role != Role.ADMIN:
        raise HTTPException(403, "só um administrador pode dispensar a aprovação de um fluxo de risco elevado")
    try:
        defn = _bot_definition(bot.key, body)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    before = {k: bot.definition.get(k) for k in ("risk_level", "requires_approval", "timeout_seconds", "triggers_allowed")}
    _apply_definition(bot, defn)
    audit(db, "user", user.username, "flow.meta_updated", "bot", bot.id,
          details={"before": before, "after": body.model_dump()}, ip=client_ip(request))
    db.commit()
    return bot_out(bot, full=True)
