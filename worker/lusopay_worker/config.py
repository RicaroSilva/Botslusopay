"""Configuração do worker (variáveis de ambiente WORKER_*).

O token do worker deve vir de WORKER_TOKEN_FILE (ficheiro com ACL restrita à
conta do worker) em vez de WORKER_TOKEN, para não ficar no ambiente do sistema.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "0.1.0"


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass
class WorkerConfig:
    backend_url: str
    token: str
    adapters: list[str] = field(default_factory=lambda: ["taskt_cli"])
    taskt_exe: Path | None = None
    taskt_scripts_dir: Path | None = None
    taskt_logs_dir: Path | None = None
    openbots_projects_dir: Path | None = None
    state_file: Path = Path("worker-state.json")
    poll_seconds: float = 10.0
    heartbeat_seconds: float = 15.0
    kill_grace_seconds: float = 10.0
    ca_bundle: str | None = None
    # Segredos conhecidos (ex.: lidos de ficheiros locais) a redigir nos logs.
    extra_redactions: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        token = _env("WORKER_TOKEN")
        token_file = _env("WORKER_TOKEN_FILE")
        if token_file:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        if not token:
            raise SystemExit("WORKER_TOKEN_FILE (ou WORKER_TOKEN) é obrigatório")
        url = _env("WORKER_BACKEND_URL")
        if not url:
            raise SystemExit("WORKER_BACKEND_URL é obrigatório")
        if not url.startswith("https://") and _env("WORKER_ALLOW_HTTP") != "1":
            raise SystemExit("WORKER_BACKEND_URL tem de usar https (WORKER_ALLOW_HTTP=1 só para desenvolvimento)")
        p = lambda n: Path(v) if (v := _env(n)) else None  # noqa: E731
        scripts = p("WORKER_TASKT_SCRIPTS_DIR")
        return cls(
            backend_url=url.rstrip("/"),
            token=token,
            adapters=[a.strip() for a in (_env("WORKER_ADAPTERS", "taskt_cli") or "").split(",") if a.strip()],
            taskt_exe=p("WORKER_TASKT_EXE"),
            taskt_scripts_dir=scripts,
            # Por omissão o taskt escreve em <RootFolder>\Logs; RootFolder costuma ser a pasta-mãe de "My Scripts".
            taskt_logs_dir=p("WORKER_TASKT_LOGS_DIR") or (scripts.parent / "Logs" if scripts else None),
            openbots_projects_dir=p("WORKER_OPENBOTS_PROJECTS_DIR"),
            state_file=p("WORKER_STATE_FILE") or Path("worker-state.json"),
            poll_seconds=float(_env("WORKER_POLL_SECONDS", "10")),
            heartbeat_seconds=float(_env("WORKER_HEARTBEAT_SECONDS", "15")),
            kill_grace_seconds=float(_env("WORKER_KILL_GRACE_SECONDS", "10")),
            ca_bundle=_env("WORKER_CA_BUNDLE"),
        )
