"""Esquema dos fluxos nativos (executados pelo flow runner, sem taskt/OpenBots).

Um fluxo é uma lista de passos. Campos de texto aceitam modelos Jinja2
(`{{ variavel }}`); campos *_expr / condition / items são expressões Jinja2
(sem chavetas). Ambos são avaliados num ambiente *sandbox* no runner.

As credenciais só podem ser referidas pelo nome no campo `credential`; os
valores nunca ficam disponíveis como variáveis do fluxo.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import urlsplit

from jinja2 import TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

NAME_RE = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
MAX_STEPS = 300
MAX_DEPTH = 6

_env = SandboxedEnvironment()


def check_template(value: str) -> str:
    try:
        _env.parse(value)
    except TemplateSyntaxError as exc:
        raise ValueError(f"modelo inválido: {exc.message}") from exc
    return value


def check_expr(value: str) -> str:
    try:
        _env.compile_expression(value)
    except TemplateSyntaxError as exc:
        raise ValueError(f"expressão inválida: {exc.message}") from exc
    return value


class _Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    name: str = Field(default="", max_length=200)
    continue_on_error: bool = False


class HttpRequestStep(_Step):
    type: Literal["http_request"]
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "GET"
    url: str
    headers: dict[str, str] = {}
    query: dict[str, str] = {}
    body_json_expr: str | None = None  # expressão que produz o corpo JSON
    body_text: str | None = None  # modelo de texto
    credential: str | None = None  # http_basic | http_bearer | http_header
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    expect_status: list[int] = [200]
    response: Literal["json", "text"] = "json"
    save_as: str | None = Field(default=None, pattern=NAME_RE)
    # Só pedidos sem efeitos (GET/HEAD) podem ser repetidos automaticamente.
    retries: int = Field(default=0, ge=0, le=5)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        check_template(v)
        if not v.lower().startswith("https://"):
            raise ValueError("o URL tem de começar por https:// (o host não pode vir de um modelo)")
        return v

    @field_validator("headers", "query")
    @classmethod
    def _tpl_dict(cls, v: dict[str, str]) -> dict[str, str]:
        for k, val in v.items():
            if k.lower() in ("authorization", "proxy-authorization", "cookie"):
                raise ValueError("credenciais nos cabeçalhos são proibidas: use o campo 'credential'")
            check_template(val)
        return v

    @model_validator(mode="after")
    def _checks(self) -> "HttpRequestStep":
        if self.body_json_expr and self.body_text:
            raise ValueError("use body_json_expr OU body_text")
        if self.body_json_expr:
            check_expr(self.body_json_expr)
        if self.body_text:
            check_template(self.body_text)
        if self.retries and self.method not in ("GET", "HEAD"):
            raise ValueError("retries só é permitido em GET/HEAD (pedidos com efeitos não são repetidos)")
        return self


class SetStep(_Step):
    type: Literal["set"]
    variable: str = Field(pattern=NAME_RE)
    value: str | None = None  # modelo → texto
    expr: str | None = None  # expressão → qualquer tipo

    @model_validator(mode="after")
    def _one(self) -> "SetStep":
        if (self.value is None) == (self.expr is None):
            raise ValueError("indique value OU expr")
        if self.value is not None:
            check_template(self.value)
        if self.expr is not None:
            check_expr(self.expr)
        return self


class ExtractStep(_Step):
    type: Literal["extract"]
    source_expr: str
    path: str = Field(pattern=r"^[A-Za-z0-9_.\[\]*$-]+$")  # ex.: items[*].id
    save_as: str = Field(pattern=NAME_RE)

    _c = field_validator("source_expr")(lambda cls, v: check_expr(v))


class AppendStep(_Step):
    type: Literal["append"]
    variable: str = Field(pattern=NAME_RE)
    expr: str

    _c = field_validator("expr")(lambda cls, v: check_expr(v))


class LogStep(_Step):
    type: Literal["log"]
    message: str
    level: Literal["INFO", "WARNING", "ERROR"] = "INFO"

    _c = field_validator("message")(lambda cls, v: check_template(v))


class FailStep(_Step):
    type: Literal["fail"]
    message: str

    _c = field_validator("message")(lambda cls, v: check_template(v))


class StopStep(_Step):
    """Termina o fluxo com sucesso (ex.: 'sem dados para processar')."""

    type: Literal["stop"]
    message: str = ""

    _c = field_validator("message")(lambda cls, v: check_template(v))


class CsvColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    header: str = Field(max_length=200)
    value: str  # modelo avaliado com a variável `row`

    _c = field_validator("value")(lambda cls, v: check_template(v))


class CsvWriteStep(_Step):
    type: Literal["csv_write"]
    file: str  # modelo do nome do ficheiro (sem pastas)
    rows_expr: str
    columns: list[CsvColumn] = Field(min_length=1, max_length=100)
    delimiter: Literal[";", ",", "\t"] = ";"

    @field_validator("file")
    @classmethod
    def _file(cls, v: str) -> str:
        check_template(v)
        if "/" in v or "\\" in v or ".." in v:
            raise ValueError("o nome do ficheiro não pode ter pastas")
        return v

    _c = field_validator("rows_expr")(lambda cls, v: check_expr(v))


class TextWriteStep(_Step):
    type: Literal["text_write"]
    file: str
    content: str

    @field_validator("file")
    @classmethod
    def _file(cls, v: str) -> str:
        check_template(v)
        if "/" in v or "\\" in v or ".." in v:
            raise ValueError("o nome do ficheiro não pode ter pastas")
        return v

    _c = field_validator("content")(lambda cls, v: check_template(v))


class EmailStep(_Step):
    type: Literal["email"]
    credential: str  # smtp
    to: list[str] = Field(min_length=1, max_length=50)
    cc: list[str] = []
    subject: str
    body: str
    attachments: list[str] = []  # modelos de nomes de ficheiros produzidos neste fluxo

    @model_validator(mode="after")
    def _tpl(self) -> "EmailStep":
        for v in [*self.to, *self.cc, self.subject, self.body, *self.attachments]:
            check_template(v)
        return self


class SqlQueryStep(_Step):
    type: Literal["sql_query"]
    credential: str  # mssql
    query: str = Field(max_length=20000)
    params: dict[str, str] = {}  # %(nome)s na query; valores são modelos
    save_as: str | None = Field(default=None, pattern=NAME_RE)
    read_only: bool = True  # recusa INSERT/UPDATE/DELETE/... se true

    @model_validator(mode="after")
    def _q(self) -> "SqlQueryStep":
        if "{{" in self.query:
            raise ValueError("a query não pode ter modelos: use params (evita SQL injection)")
        for v in self.params.values():
            check_template(v)
        if self.read_only and re.search(
            r"\b(insert|update|delete|merge|drop|alter|create|truncate|exec|execute|grant|revoke)\b", self.query, re.I
        ):
            raise ValueError("query de escrita num passo read_only")
        return self


class ForEachStep(_Step):
    type: Literal["foreach"]
    items_expr: str
    item_variable: str = Field(default="item", pattern=NAME_RE)
    parallel: int = Field(default=1, ge=1, le=20)
    steps: list["Step"] = Field(min_length=1)

    _c = field_validator("items_expr")(lambda cls, v: check_expr(v))


class IfStep(_Step):
    type: Literal["if"]
    condition: str
    then: list["Step"] = []
    otherwise: list["Step"] = []

    _c = field_validator("condition")(lambda cls, v: check_expr(v))


Step = Annotated[
    Union[
        HttpRequestStep, SetStep, ExtractStep, AppendStep, LogStep, FailStep, StopStep,
        CsvWriteStep, TextWriteStep, EmailStep, SqlQueryStep, ForEachStep, IfStep,
    ],
    Field(discriminator="type"),
]
ForEachStep.model_rebuild()
IfStep.model_rebuild()

STEP_TYPES = sorted(
    m.model_fields["type"].annotation.__args__[0]  # type: ignore[union-attr]
    for m in (HttpRequestStep, SetStep, ExtractStep, AppendStep, LogStep, FailStep, StopStep,
              CsvWriteStep, TextWriteStep, EmailStep, SqlQueryStep, ForEachStep, IfStep)
)

CREDENTIAL_KINDS_BY_STEP = {
    "http_request": {"http_basic", "http_bearer", "http_header"},
    "email": {"smtp"},
    "sql_query": {"mssql"},
}


class FlowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    variables: dict[str, Any] = {}  # valores iniciais (não sensíveis)
    steps: list[Step] = Field(min_length=1)


def iter_steps(steps: list[Any], depth: int = 1):
    for st in steps:
        yield st, depth
        if isinstance(st, ForEachStep):
            yield from iter_steps(st.steps, depth + 1)
        elif isinstance(st, IfStep):
            yield from iter_steps(st.then, depth + 1)
            yield from iter_steps(st.otherwise, depth + 1)


def validate_flow(raw: dict[str, Any], credentials: dict[str, str], allowed_hosts: list[str]) -> FlowDefinition:
    """Valida estrutura, modelos, ids únicos, credenciais e hosts. `credentials` = {nome: tipo}."""
    flow = FlowDefinition.model_validate(raw)
    ids: set[str] = set()
    count = 0
    for st, depth in iter_steps(flow.steps):
        count += 1
        if depth > MAX_DEPTH:
            raise ValueError(f"passo {st.id}: profundidade máxima {MAX_DEPTH}")
        if st.id in ids:
            raise ValueError(f"id de passo repetido: {st.id}")
        ids.add(st.id)
        cred = getattr(st, "credential", None)
        if cred:
            kind = credentials.get(cred)
            if kind is None:
                raise ValueError(f"passo {st.id}: credencial inexistente '{cred}'")
            if kind not in CREDENTIAL_KINDS_BY_STEP[st.type]:
                raise ValueError(f"passo {st.id}: credencial '{cred}' ({kind}) não serve para {st.type}")
        if isinstance(st, HttpRequestStep) and allowed_hosts:
            host = urlsplit(st.url.split("{{")[0]).hostname
            if host not in allowed_hosts:
                raise ValueError(f"passo {st.id}: host '{host}' não autorizado (BM_FLOW_ALLOWED_HOSTS)")
    if count > MAX_STEPS:
        raise ValueError(f"máximo de {MAX_STEPS} passos")
    return flow


def referenced_credentials(flow: FlowDefinition) -> set[str]:
    return {c for st, _ in iter_steps(flow.steps) if (c := getattr(st, "credential", None))}


StepListAdapter = TypeAdapter(list[Step])
