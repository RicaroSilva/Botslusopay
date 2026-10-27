"""Leitura do log do motor taskt para determinar o resultado de uma execução.

Comportamento confirmado no código-fonte do taskt (saucepleez/taskt, master):
* taskt.exe "<script.xml>" executa o script e fecha no fim (Program.cs);
* o processo NÃO devolve código de saída significativo (WinForms);
* o motor regista em <RootFolder>\\Logs\\taskt Engine Logs<yyyyMMdd>.txt
  (Serilog, rotação diária) as linhas "Script Path: <ficheiro>" no início e
  "Result Code: Successful|Error|Cancelled" no fim;
* scripts chamados por "Run Task" geram os seus próprios pares
  Script Path / Result Code; quando o ficheiro está ocupado o Serilog pode
  escrever num ficheiro com sufixo _001.

Por isso lemos todos os ficheiros "taskt Engine Logs*.txt" a partir do
tamanho que tinham antes do lançamento, ordenamos pela marca temporal e
emparelhamos Script Path/Result Code por profundidade. A versão instalada no
servidor tem de ser validada (docs/validacao-piloto.md).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

LOG_GLOB = "taskt Engine Logs*.txt"
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)")
_SCRIPT = re.compile(r"Script Path: (.+?)\s*$")
_RESULT = re.compile(r"Result Code: (\w+)")
_ERROR = re.compile(r"\] Error: (.+)$")
_HANDLED = re.compile(r"Error Occured at Line (\d+)")


class LogTailer:
    """Acompanha os ficheiros de log do taskt a partir de um instante."""

    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.offsets: dict[Path, int] = {}
        self.lines: list[str] = []

    def snapshot(self) -> None:
        self.offsets = {p: p.stat().st_size for p in self._files()}

    def _files(self) -> list[Path]:
        if not self.logs_dir or not self.logs_dir.is_dir():
            return []
        return sorted(self.logs_dir.glob(LOG_GLOB))

    def read_new(self) -> list[str]:
        new: list[str] = []
        for path in self._files():
            start = self.offsets.get(path, 0)
            try:
                size = path.stat().st_size
                if size < start:  # ficheiro recriado
                    start = 0
                if size == start:
                    continue
                with path.open("rb") as fh:
                    fh.seek(start)
                    chunk = fh.read(size - start)
            except OSError:
                continue
            # só consome até à última quebra de linha completa
            cut = chunk.rfind(b"\n")
            if cut < 0:
                continue
            self.offsets[path] = start + cut + 1
            text = chunk[: cut + 1].decode("utf-8-sig", errors="replace")
            new.extend(l for l in text.splitlines() if l.strip())
        self.lines.extend(new)
        return new


@dataclass
class TasktResult:
    result_code: str | None = None  # Successful | Error | Cancelled | None (indeterminado)
    matched_script: bool = False
    errors: list[str] = field(default_factory=list)
    handled_error_lines: list[int] = field(default_factory=list)
    nested_scripts: list[str] = field(default_factory=list)
    reason: str = ""


def _same_script(logged: str, expected: Path) -> bool:
    a = PureWindowsPath(logged.strip().strip('"'))
    b = PureWindowsPath(str(expected))
    return str(a).lower() == str(b).lower() or a.name.lower() == b.name.lower()


def _sort_key(item: tuple[int, str]) -> tuple[str, int]:
    idx, line = item
    m = _TS.match(line)
    return (m.group(1) if m else "", idx)


def parse_result(lines: list[str], script_path: Path) -> TasktResult:
    res = TasktResult()
    ordered = [l for _, l in sorted(enumerate(lines), key=_sort_key)]
    depth = 0
    started = False
    for line in ordered:
        sm = _SCRIPT.search(line)
        if sm:
            if not started:
                if _same_script(sm.group(1), script_path):
                    started, depth, res.matched_script = True, 1, True
                continue
            depth += 1
            res.nested_scripts.append(PureWindowsPath(sm.group(1)).name)
            continue
        if not started:
            continue
        hm = _HANDLED.search(line)
        if hm:
            res.handled_error_lines.append(int(hm.group(1)))
        em = _ERROR.search(line)
        if em and em.group(1).strip() != "None" and depth == 1:
            res.errors.append(em.group(1).strip()[:500])
        rm = _RESULT.search(line)
        if rm:
            depth -= 1
            if depth == 0:
                res.result_code = rm.group(1)
                break
    if not res.matched_script:
        res.reason = "linha 'Script Path' do script não encontrada no log do taskt"
    elif res.result_code is None:
        res.reason = "linha 'Result Code' final não encontrada no log do taskt"
    return res
