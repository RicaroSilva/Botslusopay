from __future__ import annotations

import glob
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import WorkerConfig


class AdapterRejected(Exception):
    """O trabalho é recusado antes de iniciar qualquer processo."""


@dataclass
class LaunchSpec:
    argv: list[str]
    cwd: Path | None = None
    stdin_data: bytes | None = None  # dados enviados pelo stdin (nunca por argv/ambiente)
    env: dict[str, str] | None = None  # ambiente do processo (None = herdado)


@dataclass
class Outcome:
    status: str  # SUCCEEDED | FAILED | CANCELLED
    failure_reason: str | None = None
    result_summary: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Path] = field(default_factory=list)  # ficheiros a enviar ao backend


@dataclass
class RunContext:
    job: dict[str, Any]
    started_at: datetime | None = None
    script_path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def safe_join(root: Path | None, relative: str, suffixes: tuple[str, ...]) -> Path:
    """Resolve 'relative' dentro de 'root' e garante que não sai de lá."""
    if root is None:
        raise AdapterRejected("pasta de scripts não configurada no worker")
    root_r = root.resolve()
    candidate = (root_r / relative.replace("\\", "/")).resolve()
    if root_r != candidate and root_r not in candidate.parents:
        raise AdapterRejected("caminho do script fora da pasta autorizada")
    if suffixes and candidate.suffix.lower() not in suffixes:
        raise AdapterRejected(f"extensão não permitida: {candidate.suffix}")
    if not candidate.is_file():
        raise AdapterRejected(f"ficheiro de entrada não encontrado: {relative}")
    return candidate


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_success_checks(job: dict[str, Any], root: Path | None, ctx: RunContext) -> list[str]:
    """Validações específicas do bot (ex.: ficheiro de saída criado). Devolve falhas."""
    failures = []
    checks = (job.get("success_detection") or {}).get("checks") or []
    for chk in checks:
        if chk.get("type") != "file_exists" or root is None:
            failures.append(f"verificação não suportada: {chk.get('type')}")
            continue
        date_str = (ctx.started_at or datetime.now()).strftime("%Y-%m-%d")
        rel = chk["path"].replace("{date}", date_str)
        root_r = root.resolve()
        matches = [Path(m) for m in glob.glob(str(root_r / rel))]
        matches = [m for m in matches if root_r in m.resolve().parents]
        if chk.get("modified_after_start", True) and ctx.started_at:
            ts = ctx.started_at.timestamp() - 2
            matches = [m for m in matches if m.stat().st_mtime >= ts]
        if not matches:
            failures.append(f"ficheiro esperado não encontrado: {rel}")
    return failures


class Adapter:
    name: str = ""

    def __init__(self, cfg: WorkerConfig):
        self.cfg = cfg

    def prepare(self, ctx: RunContext) -> LaunchSpec:
        raise NotImplementedError

    def on_started(self, ctx: RunContext) -> None:
        pass

    def progress_lines(self, ctx: RunContext) -> list[str]:
        return []

    def secrets(self, ctx: RunContext) -> list[str]:
        """Valores a redigir nos logs desta execução."""
        return []

    def cleanup(self, ctx: RunContext) -> None:
        pass

    def persistent_updates(self, ctx: RunContext) -> list[tuple[str, bytes]]:
        """Ficheiros persistentes alterados pela execução (a gravar no backend)."""
        return []

    def evaluate(self, ctx: RunContext, exit_code: int | None, output: str) -> Outcome:
        raise NotImplementedError
