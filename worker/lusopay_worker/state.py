"""Estado local persistente (sobrevive a reinícios do worker/servidor).

Guarda a execução em curso (run_id, pid) e uma conclusão por enviar, para que
após um reinício o worker: 1) reenvie a conclusão pendente; 2) termine um
processo órfão que já não está a ser supervisionado; 3) informe o backend de
que não tem execuções ativas (o backend marca as restantes como perdidas)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class LocalState:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self.path)  # escrita atómica

    def clear(self) -> None:
        self.save({})
