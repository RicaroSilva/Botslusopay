from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Command:
    """Comando normalizado, independente do formato de origem (XML taskt ou JSON OpenBots)."""

    type: str  # ex.: RESTCommand
    attrs: dict[str, str] = field(default_factory=dict)  # atributos v_* em texto
    tables: dict[str, list[dict[str, str]]] = field(default_factory=dict)  # tabelas (linhas como dicionários)
    comment: str = ""
    line: int = 0
    enabled: bool = True


@dataclass
class Robot:
    name: str
    source_format: str  # taskt | openbots
    commands: list[Command]
    variables: dict[str, str] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)  # nomes dos ficheiros lidos
    notes: list[str] = field(default_factory=list)
    subscripts: dict[str, "Robot"] = field(default_factory=dict)  # outros scripts do projeto (nome em minúsculas)
    data_files: dict[str, bytes] = field(default_factory=dict)  # ficheiros de dados do projeto (nome do ficheiro)


def table_rows_as_pairs(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Converte linhas {'Parameter Name': x, 'Parameter Value': y} num dicionário x → y."""
    out: dict[str, str] = {}
    for r in rows:
        name = r.get("Parameter Name")
        if name is not None:
            out[str(name)] = "" if r.get("Parameter Value") is None else str(r.get("Parameter Value"))
    return out
