"""Configuração do backend, lida de variáveis de ambiente / ficheiro .env.

Nenhum segredo tem valor por omissão utilizável em produção: o arranque falha
se BM_SECRET_KEY não estiver definido (exceto em modo de desenvolvimento).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BM_", env_file=".env", extra="ignore")

    environment: str = Field("production", description="production | development | test")
    database_url: str = "sqlite:///./botmanager.db"
    secret_key: str = ""
    session_minutes: int = 480
    cookie_secure: bool = True
    registry_dir: Path = REPO_ROOT / "bots" / "registry"
    # Pastas adicionais (ex.: bots/registry-dev com o bot simulado, só em desenvolvimento)
    extra_registry_dirs: list[Path] = []
    # Lista de hosts que as regras poll_http podem consultar (proteção SSRF).
    poll_allowed_hosts: list[str] = []
    # Tempo sem heartbeat após o qual uma execução RUNNING é considerada perdida.
    worker_heartbeat_timeout_seconds: int = 180
    # Margem para disparos agendados falhados (ex.: scheduler parado).
    schedule_misfire_grace_seconds: int = 300
    scheduler_interval_seconds: int = 30
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    cors_origins: list[str] = []
    timezone: str = "Europe/Lisbon"
    # Quatro olhos: quem pediu uma execução não a pode aprovar.
    allow_self_approval: bool = False
    # Execuções pedidas manualmente por um administrador não ficam à espera de aprovação (fica auditado).
    # Em produção com várias pessoas, pôr BM_ADMIN_SKIPS_APPROVAL=false para manter os quatro olhos.
    admin_skips_approval: bool = True
    # Chave Fernet do cofre de credenciais (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    vault_key: str = ""
    vault_key_old: str = ""
    # Hosts que os fluxos nativos podem contactar (vazio = qualquer host). Ex.: ["dev.lusopay.com","app.lusopay.com"]
    flow_allowed_hosts: list[str] = []
    artifact_max_bytes: int = 20 * 1024 * 1024
    # Arranque em Docker: cria o worker dos fluxos e o primeiro administrador se ainda não existirem.
    bootstrap_runner_token: str = ""
    bootstrap_admin_username: str = ""
    bootstrap_admin_password: str = ""

    @model_validator(mode="after")
    def _check_secret(self) -> "Settings":
        if not self.secret_key:
            if self.environment == "production":
                raise ValueError("BM_SECRET_KEY é obrigatório em produção")
            self.secret_key = "dev-only-insecure-key-change-me-0123456789"
        if not self.vault_key and self.environment != "production":
            # chave fixa SÓ para desenvolvimento/testes
            self.vault_key = "ZGV2LW9ubHktdmF1bHQta2V5LTAxMjM0NTY3ODlhYmM="
        if len(self.secret_key) < 32:
            raise ValueError("BM_SECRET_KEY deve ter pelo menos 32 caracteres")
        return self


    @property
    def registry_dirs(self) -> list[Path]:
        return [self.registry_dir, *self.extra_registry_dirs]


@lru_cache
def get_settings() -> Settings:
    return Settings()
