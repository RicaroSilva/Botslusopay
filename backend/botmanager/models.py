"""Modelo de dados do Bot Manager (SQLAlchemy 2)."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    LargeBinary,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .states import RunStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Role(str, enum.Enum):
    """Funções globais, por ordem crescente de privilégio."""

    VIEWER = "viewer"  # consulta
    OPERATOR = "operator"  # executa bots autorizados
    APPROVER = "approver"  # aprova execuções de risco elevado
    ADMIN = "admin"  # administra bots, regras, utilizadores


class Permission(str, enum.Enum):
    VIEW = "view"
    EXECUTE = "execute"
    APPROVE = "approve"
    CONFIGURE = "configure"


class Availability(str, enum.Enum):
    AVAILABLE = "available"
    DISABLED = "disabled"  # desativado por um administrador
    UNVALIDATED = "unvalidated"  # mecanismo de execução ainda não validado
    MAINTENANCE = "maintenance"


class TZDateTime(TypeDecorator):
    """DateTime sempre com timezone (SQLite guarda naive; normalizamos para UTC)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            if dialect.name == "sqlite":
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    email: Mapped[str | None] = mapped_column(String(254))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20), nullable=False, default=Role.VIEWER)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # None => só SSO
    auth_source: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(TZDateTime())
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime())


class Bot(Base):
    """Bot registado. A definição técnica vem do registo YAML (controlado em Git);
    os campos operacionais (enabled, availability) são geridos na aplicação."""

    __tablename__ = "bots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    adapter: Mapped[str] = mapped_column(String(40), nullable=False)
    project_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    availability: Mapped[Availability] = mapped_column(
        Enum(Availability, native_enum=False, length=20), nullable=False, default=Availability.UNVALIDATED
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    in_registry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # registry = definido em bots/registry/*.yaml; ui = fluxo nativo criado na aplicação
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="registry", server_default="registry")
    current_flow_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow, onupdate=utcnow)

    @property
    def timeout_seconds(self) -> int:
        return int(self.definition.get("timeout_seconds", 3600))

    @property
    def requires_approval(self) -> bool:
        return bool(self.definition.get("requires_approval", False))

    @property
    def concurrency(self) -> str:
        return self.definition.get("concurrency", {}).get("policy", "single")

    @property
    def exclusive_resources(self) -> list[str]:
        return list(self.definition.get("concurrency", {}).get("exclusive_resources", []))


class BotPermission(Base):
    """Concessão explícita de uma permissão sobre um bot a um utilizador.
    As concessões por função vêm do registo YAML (definition.permissions)."""

    __tablename__ = "bot_permissions"
    __table_args__ = (UniqueConstraint("bot_id", "user_id", "permission", name="uq_bot_perm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    permission: Mapped[Permission] = mapped_column(Enum(Permission, native_enum=False, length=20), nullable=False)
    granted_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)  # adaptadores suportados
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)


class TriggerRule(Base):
    __tablename__ = "trigger_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # segredo HMAC dos webhooks (guardado com hash não é possível: é preciso para verificar)
    secret: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)  # ex.: último disparo
    next_fire_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    created_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow, onupdate=utcnow)

    bot: Mapped[Bot] = relationship()

    __table_args__ = (Index("ix_trigger_rules_type_enabled", "trigger_type", "enabled"),)


class TriggerEvent(Base):
    """Cada evento recebido/gerado por uma regra. A restrição única (rule_id, dedup_key)
    garante que o mesmo evento não origina várias execuções."""

    __tablename__ = "trigger_events"
    __table_args__ = (UniqueConstraint("rule_id", "dedup_key", name="uq_trigger_event_dedup"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    rule_id: Mapped[str] = mapped_column(ForeignKey("trigger_rules.id", ondelete="CASCADE"), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False, default="accepted")
    run_id: Mapped[str | None] = mapped_column(String(32))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class BotDependency(Base):
    """bot_id só pode executar se depends_on tiver terminado com sucesso
    dentro da janela definida."""

    __tablename__ = "bot_dependencies"
    __table_args__ = (
        UniqueConstraint("bot_id", "depends_on_bot_id", name="uq_bot_dependency"),
        CheckConstraint("bot_id <> depends_on_bot_id", name="ck_dependency_not_self"),
        CheckConstraint("condition IN ('succeeded_within','succeeded_today')", name="ck_dependency_condition"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    depends_on_bot_id: Mapped[str] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    condition: Mapped[str] = mapped_column(String(30), nullable=False, default="succeeded_within")
    within_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_bot_created", "bot_id", "created_at"),
        Index("ix_runs_status_created", "status", "created_at"),
        Index("ix_runs_requested_by", "requested_by"),
        # exclusive_key = bot_id enquanto a execução está ativa e a política é "single";
        # NULL quando terminal. NULLs não colidem, logo no máximo 1 execução ativa por bot.
        UniqueConstraint("exclusive_key", name="uq_runs_exclusive_key"),
        UniqueConstraint("idempotency_key", name="uq_runs_idempotency_key"),
        CheckConstraint(
            "status IN ('PENDING','WAITING_APPROVAL','QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')",
            name="ck_runs_status",
        ),
        CheckConstraint("exclusive_key IS NULL OR status IN ('PENDING','WAITING_APPROVAL','QUEUED','RUNNING')",
                        name="ck_runs_exclusive_only_active"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(ForeignKey("bots.id"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, native_enum=False, length=20), nullable=False, default=RunStatus.PENDING
    )
    trigger_source: Mapped[str] = mapped_column(String(40), nullable=False)  # manual|schedule|webhook|after_bot|poll_http|retry
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    trigger_rule_id: Mapped[str | None] = mapped_column(ForeignKey("trigger_rules.id", ondelete="SET NULL"))
    trigger_event_id: Mapped[str | None] = mapped_column(String(32))
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    retry_of_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    exclusive_key: Mapped[str | None] = mapped_column(String(64))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)  # só não sensíveis
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)
    queued_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # simulação (teste): só leituras; POST/PUT/DELETE, emails e escritas SQL não são feitos
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    exit_code: Mapped[int | None] = mapped_column(Integer)
    failure_reason: Mapped[str | None] = mapped_column(String(40))
    # True quando a execução pode ter produzido efeitos externos sem confirmação
    # (ex.: worker perdido a meio). Exige revisão humana antes de repetir.
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    log_lines: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flow_version: Mapped[int | None] = mapped_column(Integer)  # versão do fluxo executada

    bot: Mapped[Bot] = relationship(foreign_keys=[bot_id])


class RunLog(Base):
    __tablename__ = "run_logs"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_logs_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="INFO")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="worker")  # worker|runtime|system
    message: Mapped[str] = mapped_column(Text, nullable=False)


class ResourceLock(Base):
    """Recursos exclusivos (ex.: 'desktop' do servidor de bots, ficheiros partilhados).
    A chave primária impede que duas execuções detenham o mesmo recurso."""

    __tablename__ = "resource_locks"

    resource: Mapped[str] = mapped_column(String(120), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)  # user|system|worker|webhook
    actor_id: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(120))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="success")  # success|denied|error
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))


class SchedulerLease(Base):
    """Garante uma única instância ativa do scheduler."""

    __tablename__ = "scheduler_leases"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    holder: Mapped[str] = mapped_column(String(120), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)


class Setting(Base):
    """Configurações operacionais não sensíveis editáveis pela administração."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow, onupdate=utcnow)


class FlowVersion(Base):
    """Versões imutáveis de um fluxo nativo. Cada gravação cria uma nova versão;
    as execuções registam a versão usada."""

    __tablename__ = "flow_versions"
    __table_args__ = (UniqueConstraint("bot_id", "version", name="uq_flow_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    comment: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)


class Credential(Base):
    """Cofre de credenciais: os dados sensíveis ficam cifrados (Fernet, chave
    BM_VAULT_KEY) e nunca são devolvidos pela API nem escritos em logs."""

    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('http_basic','http_bearer','http_header','smtp','mssql')", name="ck_credentials_kind"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # campos não sensíveis (ex.: host SMTP, utilizador) visíveis na interface
    public_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    encrypted_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow, onupdate=utcnow)


class RunArtifact(Base):
    """Ficheiros produzidos por uma execução (ex.: CSV). Guardados na BD com limite de tamanho."""

    __tablename__ = "run_artifacts"
    __table_args__ = (UniqueConstraint("run_id", "name", name="uq_run_artifact_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow)


class FlowFile(Base):
    """Ficheiros persistentes de um fluxo (ex.: ficheiros de controlo 'último id processado').
    Disponíveis no início de cada execução e atualizados no fim (mesmo que a execução falhe,
    para refletir o trabalho já feito). Guarda-se a versão anterior para recuperação."""

    __tablename__ = "flow_files"
    __table_args__ = (UniqueConstraint("bot_id", "name", name="uq_flow_file_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_content: Mapped[bytes | None] = mapped_column(LargeBinary)
    updated_by: Mapped[str] = mapped_column(String(120), nullable=False, default="")  # utilizador ou run:<id>
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, default=utcnow, onupdate=utcnow)
