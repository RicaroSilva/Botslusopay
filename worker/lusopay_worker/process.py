"""Lançamento e terminação de processos (árvore completa, incluindo Chrome/chromedriver)."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def start(argv: list[str], cwd: Path | None, stdin_data: bytes | None = None,
          env: dict[str, str] | None = None) -> subprocess.Popen:
    """Inicia sem shell (argv é uma lista; nada é interpretado por cmd.exe)."""
    kwargs: dict = {"cwd": str(cwd) if cwd else None,
                    "stdin": subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                    "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "env": env}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(argv, shell=False, **kwargs)
    if stdin_data is not None:
        assert proc.stdin is not None
        try:
            proc.stdin.write(stdin_data)
        finally:
            proc.stdin.close()
    return proc


def kill_tree(pid: int) -> None:
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def is_alive(pid: int) -> bool:
    if IS_WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
