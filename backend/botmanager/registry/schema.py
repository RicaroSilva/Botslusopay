"""Esquema das definições de bots (ficheiros YAML em bots/registry/).

Uma definição é a única forma de tornar um bot executável: a interface nunca
aceita caminhos, comandos ou XML fornecidos pelo utilizador.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
SAFE_REL_PATH = re.compile(r"^(?![\\/])(?!.*\.\.)(?!.*:)[^\x00]+$")

ADAPTERS = {"taskt_cli", "openbots_studio", "simulated", "flow"}
# Adaptadores que, pelo que se conseguiu confirmar, não aceitam parâmetros na linha de comandos.
ADAPTERS_WITHOUT_PARAMETERS = {"taskt_cli", "openbots_studio"}
TRIGGER_TYPES = {"manual", "schedule", "webhook", "after_bot", "poll_http"}
ROLE_NAMES = {"viewer", "operator", "approver", "admin"}


class ParameterDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    type: Literal["string", "integer", "date", "boolean", "enum"]
    description: str = ""
    required: bool = False
    default: Any = None
    pattern: str | None = None
    max_length: int = 200
    min: int | None = None
    max: int | None = None
    choices: list[str] = []
    sensitive: bool = False  # nunca guardado em runs.parameters

    @model_validator(mode="after")
    def _enum_has_choices(self) -> "ParameterDef":
        if self.type == "enum" and not self.choices:
            raise ValueError(f"parâmetro {self.name}: enum sem choices")
        if self.pattern:
            re.compile(self.pattern)
        return self


class ExecutionDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: str
    # Caminho do ficheiro de entrada RELATIVO à pasta de scripts configurada no worker.
    script: str
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # true apenas depois de validado no ambiente real (ver docs/validacao-piloto.md)
    validated: bool = False

    @field_validator("adapter")
    @classmethod
    def _known_adapter(cls, v: str) -> str:
        if v not in ADAPTERS:
            raise ValueError(f"adaptador desconhecido: {v}")
        return v

    @field_validator("script")
    @classmethod
    def _safe_path(cls, v: str) -> str:
        if not SAFE_REL_PATH.match(v):
            raise ValueError("script deve ser um caminho relativo, sem '..' nem unidade")
        return v


class SuccessCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["file_exists"]
    # relativo à pasta de scripts; aceita glob e {date} (AAAA-MM-DD do início da execução)
    path: str
    modified_after_start: bool = True

    @field_validator("path")
    @classmethod
    def _safe_path(cls, v: str) -> str:
        if not SAFE_REL_PATH.match(v):
            raise ValueError("path deve ser relativo, sem '..' nem unidade")
        return v


class SuccessDetection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # taskt_log: lê "Result Code" no log do motor taskt; exit_code: só código de saída.
    method: Literal["taskt_log", "exit_code", "simulated", "flow"] = "taskt_log"
    expected_exit_codes: list[int] = [0]
    checks: list[SuccessCheck] = []
    # No taskt, o comando "Stop Current Task" termina com "Result Code: Cancelled".
    # Alguns bots usam-no como fim normal (ex.: "sem ficheiros para processar").
    taskt_cancelled_is_success: bool = False
    # Com "Error Handling: Continue Processing", o taskt regista
    # "Error Occured at Line" mas termina como Successful. Por omissão isso é
    # reportado como aviso; com true passa a falha.
    fail_on_handled_errors: bool = False


class ConcurrencyDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: Literal["single", "parallel"] = "single"
    exclusive_resources: list[str] = []


class RetryDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Repetição automática só é permitida para bots marcados como idempotentes e
    # apenas quando o processo nunca chegou a iniciar.
    automatic: bool = False
    idempotent: bool = False

    @model_validator(mode="after")
    def _only_idempotent(self) -> "RetryDef":
        if self.automatic and not self.idempotent:
            raise ValueError("retry.automatic exige retry.idempotent: true")
        return self


class BotDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    description: str = ""
    category: str = ""
    risk_level: Literal["low", "medium", "high"] = "medium"
    source_file: str = ""  # nome do XML original (referência ao inventário)
    execution: ExecutionDef
    parameters: list[ParameterDef] = []
    prerequisites: list[str] = []
    external_effects: list[str] = []
    config_files: list[str] = []
    known_limitations: list[str] = []
    concurrency: ConcurrencyDef = ConcurrencyDef()
    timeout_seconds: int = Field(default=3600, ge=30, le=86400)
    success_detection: SuccessDetection = SuccessDetection()
    triggers_allowed: list[str] = ["manual"]
    requires_approval: bool = False
    retry: RetryDef = RetryDef()
    permissions: dict[str, list[str]] = {}

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not KEY_RE.match(v):
            raise ValueError("key deve ter 3-80 caracteres [a-z0-9-]")
        return v

    @field_validator("triggers_allowed")
    @classmethod
    def _triggers(cls, v: list[str]) -> list[str]:
        unknown = set(v) - TRIGGER_TYPES
        if unknown:
            raise ValueError(f"tipos de disparo desconhecidos: {sorted(unknown)}")
        return v

    @field_validator("permissions")
    @classmethod
    def _perms(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for perm, roles in v.items():
            if perm not in {"view", "execute", "approve", "configure"}:
                raise ValueError(f"permissão desconhecida: {perm}")
            if set(roles) - ROLE_NAMES:
                raise ValueError(f"funções desconhecidas em {perm}: {roles}")
        return v

    @model_validator(mode="after")
    def _coherence(self) -> "BotDefinition":
        if self.execution.adapter in ADAPTERS_WITHOUT_PARAMETERS and self.parameters:
            raise ValueError(
                f"o adaptador {self.execution.adapter} não suporta parâmetros de entrada (confirmado no código do taskt)"
            )
        if self.risk_level == "high" and not self.requires_approval:
            raise ValueError("bots de risco elevado têm de ter requires_approval: true")
        if (self.execution.adapter == "flow") != (self.success_detection.method == "flow"):
            raise ValueError("fluxos nativos usam success_detection.method=flow (e só eles)")
        if self.execution.adapter == "taskt_cli" and self.success_detection.method == "exit_code":
            raise ValueError("taskt não devolve código de saída fiável: use success_detection.method=taskt_log")
        return self


class ParameterError(ValueError):
    pass


def validate_parameters(defn: BotDefinition, supplied: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Valida parâmetros fornecidos. Devolve (todos, apenas_não_sensíveis).
    Parâmetros não declarados são rejeitados."""
    supplied = dict(supplied or {})
    declared = {p.name: p for p in defn.parameters}
    unknown = set(supplied) - set(declared)
    if unknown:
        raise ParameterError(f"parâmetros não permitidos: {sorted(unknown)}")
    clean: dict[str, Any] = {}
    for name, p in declared.items():
        if name not in supplied or supplied[name] in (None, ""):
            if p.required and p.default is None:
                raise ParameterError(f"parâmetro obrigatório em falta: {name}")
            if p.default is not None:
                clean[name] = p.default
            continue
        v = supplied[name]
        if p.type == "string":
            if not isinstance(v, str) or len(v) > p.max_length:
                raise ParameterError(f"{name}: texto inválido")
            if p.pattern and not re.fullmatch(p.pattern, v):
                raise ParameterError(f"{name}: formato inválido")
        elif p.type == "integer":
            if isinstance(v, bool) or not isinstance(v, int):
                raise ParameterError(f"{name}: inteiro inválido")
            if (p.min is not None and v < p.min) or (p.max is not None and v > p.max):
                raise ParameterError(f"{name}: fora do intervalo")
        elif p.type == "date":
            try:
                v = date.fromisoformat(str(v)).isoformat()
            except ValueError as exc:
                raise ParameterError(f"{name}: data inválida (AAAA-MM-DD)") from exc
        elif p.type == "boolean":
            if not isinstance(v, bool):
                raise ParameterError(f"{name}: booleano inválido")
        elif p.type == "enum":
            if v not in p.choices:
                raise ParameterError(f"{name}: valor não permitido")
        clean[name] = v
    public = {k: v for k, v in clean.items() if not declared[k].sensitive}
    return clean, public
