"""Adaptador OpenBots Studio — NÃO VALIDADO.

O orquestrador atual abre 'project.obconfig' com StartProcess (associação de
ficheiro do Windows), o que não permite saber o resultado. Não foi possível
confirmar uma interface de linha de comandos suportada pela versão instalada
do OpenBots (Studio/Agent). Até essa validação (docs/validacao-piloto.md),
este adaptador recusa executar — de propósito, para não inventar opções."""
from __future__ import annotations

from .base import Adapter, AdapterRejected, LaunchSpec, Outcome, RunContext


class OpenBotsStudioAdapter(Adapter):
    name = "openbots_studio"

    def prepare(self, ctx: RunContext) -> LaunchSpec:
        raise AdapterRejected(
            "mecanismo de execução OpenBots ainda não validado; ver docs/validacao-piloto.md"
        )

    def evaluate(self, ctx: RunContext, exit_code: int | None, output: str) -> Outcome:  # pragma: no cover
        return Outcome("FAILED", "result_undetermined")
