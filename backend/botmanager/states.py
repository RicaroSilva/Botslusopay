"""Máquina de estados explícita das execuções.

    PENDING ──► QUEUED ──► RUNNING ──► SUCCEEDED
       │          │           │    └─► FAILED
       │          │           └──────► CANCELLED
       │          └─► CANCELLED
       ├─► WAITING_APPROVAL ──► QUEUED
       │                    └─► CANCELLED (rejeitada / cancelada)
       ├─► CANCELLED
       └─► FAILED (pré-requisitos falharam na promoção)

QUEUED também pode passar a FAILED quando o worker recusa o trabalho
(ex.: script inexistente ou adaptador não validado) antes de iniciar o processo.
SUCCEEDED, FAILED e CANCELLED são terminais.
"""
from __future__ import annotations

import enum


class RunStatus(str, enum.Enum):
    PENDING = "PENDING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED})
ACTIVE = frozenset({RunStatus.PENDING, RunStatus.WAITING_APPROVAL, RunStatus.QUEUED, RunStatus.RUNNING})

ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.WAITING_APPROVAL, RunStatus.QUEUED, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.WAITING_APPROVAL: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.RUNNING: frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


class InvalidTransition(Exception):
    def __init__(self, current: RunStatus, target: RunStatus):
        super().__init__(f"Transição inválida: {current.value} -> {target.value}")
        self.current = current
        self.target = target


def check_transition(current: RunStatus, target: RunStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(current, target)


class FailureReason(str, enum.Enum):
    """Motivo normalizado de uma falha (campo runs.failure_reason)."""

    BOT_REPORTED_ERROR = "bot_reported_error"  # o runtime registou erro
    EXIT_CODE = "exit_code"  # código de saída diferente do esperado
    TIMEOUT = "timeout"  # excedeu o timeout e foi terminado
    RESULT_UNDETERMINED = "result_undetermined"  # não foi possível confirmar o resultado
    SUCCESS_CHECK_FAILED = "success_check_failed"  # validação específica do bot falhou
    WORKER_LOST = "worker_lost"  # sem heartbeat; efeitos externos desconhecidos
    WORKER_REJECTED = "worker_rejected"  # worker recusou antes de iniciar o processo
    LAUNCH_ERROR = "launch_error"  # erro ao iniciar o processo
    DEPENDENCY_UNMET = "dependency_unmet"
