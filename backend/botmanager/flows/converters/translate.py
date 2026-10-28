"""Tradução de comandos taskt/OpenBots para passos de fluxo nativo.

Princípios:
* Fidelidade: as variáveis do taskt são globais e guardam texto; os ciclos
  propagam as alterações (`carry`), as respostas HTTP ficam em texto e os
  comandos JSON fazem o parse quando precisam (`parsejson`), como no original.
* Nada é inventado: o que não tem equivalente (browser, teclado, programas
  externos, sub-robôs) vira um passo "Falhar" com a explicação, para que o
  fluxo não corra em silêncio sem essa parte, e fica no relatório.
* As credenciais nunca são copiadas: cabeçalhos Authorization, passwords SMTP
  e connection strings são substituídos por referências a credenciais do cofre.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Any, Callable
from urllib.parse import urlsplit

from ..schema import FILE_NAME_RE
from .model import Command, Robot, table_rows_as_pairs

# Nomes de comandos do OpenBots que correspondem a comandos do taskt (por validar com projetos reais).
ALIASES = {
    "SetVariableCommand": "VariableCommand",
    "NewVariableCommand": "VariableCommand",
    "AddVariableCommand": "VariableCommand",
    "ShowMessageCommand": "MessageBoxCommand",
    "SendSMTPEmailCommand": "SMTPSendEmailCommand",
    "SMTPCommand": "SMTPSendEmailCommand",
    "ExecuteRESTAPICommand": "RESTCommand",
    "LoopCollectionCommand": "BeginListLoopCommand",
    "LoopNumberOfTimesCommand": "BeginNumberOfTimesLoopCommand",
    "LoopContinuouslyCommand": "BeginContinousLoopCommand",
    "BeginContinuousLoopCommand": "BeginContinousLoopCommand",
    "ReplaceTextCommand": "StringReplaceCommand",
    "SplitTextCommand": "StringSplitCommand",
    "SubstringCommand": "StringSubstringCommand",
    "ExtractTextCommand": "TextExtractorCommand",
    "GetTextLengthCommand": "GetWordLengthCommand",
    "ModifyTextCommand": "ModifyVariableCommand",
    "RegexExtractorCommand": "RegExExtractorCommand",
    "ThrowCommand": "StopTaskCommand",
}

UI_PREFIXES = ("Selenium", "SendKeys", "SendMouse", "SendAdvancedKeyStrokes", "SendHotkey", "ActivateWindow",
               "SetWindowState", "CloseWindow", "MoveWindow", "ResizeWindow", "WaitForWindow", "UIAutomation",
               "ImageRecognition", "Clipboard", "Screenshot", "IE", "Excel", "Word", "Outlook", "PDF", "Thick",
               "OCR", "WebBrowser", "Chrome", "Edge", "Firefox", "Browser")

CONFIG_SCRIPTS = ("recolha das configura", "recolhe senha api", "recolha de configura")

SECRET_NAME = re.compile(r"(?i)senha|pass|pwd|token|secret|apikey|api_key")

_DOTNET_TOKENS = [("yyyy", "%Y"), ("yy", "%y"), ("MMMM", "%B"), ("MMM", "%b"), ("MM", "%m"), ("M", "%m"),
                  ("dddd", "%A"), ("ddd", "%a"), ("dd", "%d"), ("d", "%d"), ("HH", "%H"), ("H", "%H"),
                  ("hh", "%I"), ("h", "%I"), ("mm", "%M"), ("m", "%M"), ("ss", "%S"), ("s", "%S"),
                  ("fff", "%f"), ("tt", "%p")]
_DOTNET_RE = re.compile("|".join(re.escape(t) for t, _ in _DOTNET_TOKENS))


def dotnet_date_format(fmt: str) -> str:
    fmt = fmt or "yyyy-MM-dd HH:mm:ss"
    out, pos = [], 0
    for m in _DOTNET_RE.finditer(fmt):
        out.append(fmt[pos:m.start()].replace("%", "%%"))
        out.append(dict(_DOTNET_TOKENS)[m.group(0)])
        pos = m.end()
    out.append(fmt[pos:].replace("%", "%%"))
    return "".join(out)


@dataclass
class ReportItem:
    level: str  # convertido | aproximado | ignorado | nao_convertivel | info
    line: int
    command: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "line": self.line, "command": self.command, "message": self.message}


@dataclass
class ConversionResult:
    name: str
    key: str
    source_format: str
    definition: dict[str, Any]
    report: list[ReportItem]
    credentials: dict[str, str]  # nome → tipo
    risk_level: str
    notes: list[str] = field(default_factory=list)

    @property
    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.report:
            out[r.level] = out.get(r.level, 0) + 1
        return out

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "key": self.key, "source_format": self.source_format,
                "definition": self.definition, "report": [r.as_dict() for r in self.report],
                "credentials": self.credentials, "risk_level": self.risk_level, "stats": self.stats,
                "notes": self.notes}


class _Unsupported(Exception):
    pass


class Translator:
    def __init__(self, robot: Robot, test_email: str = ""):
        self.robot = robot
        self.test_email = test_email.strip()
        self.report: list[ReportItem] = []
        self.credentials: dict[str, str] = {}
        self.written: set[str] = set()
        self.loop_lists: list[str] = []  # variáveis de ciclos sobre listas ativos
        self.referenced: set[str] = set()
        self.declared = {self.var(k): v for k, v in robot.variables.items() if k}
        self.continue_on_error = False
        self.pending_comment = ""
        self.counter = 0
        self.writes_external = False
        self.sends_email = False
        self.cmd: Command | None = None
        self.persistent = self._control_files(robot)  # ficheiros de controlo entre execuções

    def _control_files(self, robot: Robot) -> set[str]:
        """Ficheiros de nome fixo que o robô lê (ex.: 'ultimo id processado.txt'): guardam estado entre execuções e
        passam a ser ficheiros persistentes do fluxo."""
        out = set()
        for c in robot.commands:
            if c.enabled and ALIASES.get(c.type, c.type) == "ReadTextFileCommand":
                name = self.basename(c.attrs.get("v_FilePath", ""))
                if name and "{{" not in name and "config" not in name.lower() and FILE_NAME_RE.match(name):
                    out.add(name)
        return out

    def collection(self, raw: str) -> str:
        """Expressão da lista/tabela; dentro de um ciclo sobre a própria lista, o nome da variável passa a ser o
        elemento atual, por isso usa-se a cópia guardada antes do ciclo."""
        name = self.var(raw)
        if name in self.loop_lists:
            return f"{name}_colecao"
        return self.expr(raw)

    # ------------------------------------------------------------------ nomes e texto

    def var(self, raw: str) -> str:
        name = raw.strip()
        if name.startswith("{") and name.endswith("}"):
            name = name[1:-1]
        if name.startswith("[") and name.endswith("]"):
            name = name[1:-1]
        name = re.sub(r"\W", "_", name)
        if not name or name[0].isdigit():
            name = "v_" + name
        return name[:64]

    def _ref(self, token: str) -> str | None:
        """Expressão Jinja para uma referência {xxx} do taskt (None = não é variável)."""
        t = token
        if t.startswith("DateTime.Now"):
            rest = t[len("DateTime.Now"):]
            return {
                "": "(now() | date('%Y-%m-%d %H:%M:%S'))",
                ".YearLong": "now().year", ".Year": "now().year", ".YearShort": "(now() | date('%y'))",
                ".Month": "now().month", ".MonthName": "(now() | date('%B'))", ".Day": "now().day",
                ".Hour": "now().hour", ".Minute": "now().minute", ".Second": "now().second",
                ".FileSafe": "(now() | date('%m-%d-%Y %H-%M-%S'))", ".DayOfWeek": "(now() | date('%A'))",
            }.get(rest)
        if t.startswith(("Folder.", "Env.", "Engine.")):
            return "''"
        if t.startswith("Loop.CurrentIndex"):
            return "loop_index"
        base, _, prop = t.partition(".")
        if prop in ("Count", "Length"):
            name = self.var(base)
            self.referenced.add(name)
            return f"({name} | parsejson | length)" if prop == "Count" else f"({name} | text | length)"
        if prop:
            return None  # propriedade desconhecida: mantém-se como texto
        name = self.var(t)
        self.referenced.add(name)
        return name

    _TOKEN = re.compile(r"\{([A-Za-z_][\w\-]*(?:\.[A-Za-z_]+)?)\}|\[(v[\w\-]*)\]")

    def _known(self, name: str) -> bool:
        return self.var(name) in self.declared or self.var(name) in self.referenced

    def _parts(self, s: str) -> list[tuple[str, str]]:
        """Divide texto do taskt em partes ('lit', texto) e ('ref', expressão)."""
        s = (s or "").replace("[crLF]", "\n").replace("[chr13]", "\r").replace("[chr10]", "\n").replace("\r\n", "\n")
        parts, pos = [], 0
        for m in self._TOKEN.finditer(s):
            token = m.group(1) or m.group(2)
            if m.group(2) and not self._known(token):
                continue  # [texto] que não é variável
            ref = self._ref(token)
            if ref is None:
                continue
            if m.start() > pos:
                parts.append(("lit", s[pos:m.start()]))
            parts.append(("ref", ref))
            pos = m.end()
        if pos < len(s):
            parts.append(("lit", s[pos:]))
        return parts

    def tpl(self, s: str) -> str:
        out = []
        for kind, v in self._parts(s):
            if kind == "ref":
                out.append("{{ " + v + " }}")
            elif any(d in v for d in ("{{", "{%", "{#", "}}", "%}", "#}")):
                out.append("{{ " + json.dumps(v, ensure_ascii=False) + " }}")
            else:
                out.append(v)
        return "".join(out)

    def expr(self, s: str) -> str:
        """Expressão: uma variável sozinha mantém o tipo; texto misto é concatenado."""
        parts = self._parts(s)
        if len(parts) == 1 and parts[0][0] == "ref":
            return parts[0][1]
        if not parts:
            return "''"
        return " ~ ".join(f"({v} | text)" if k == "ref" else json.dumps(v, ensure_ascii=False) for k, v in parts)

    def basename(self, path: str) -> str:
        """Nome do ficheiro (sem pastas) como modelo."""
        raw = (path or "").replace("/", "\\")
        name = PureWindowsPath(raw).name if "\\" in raw else raw
        name = re.sub(r"\{Folder\.[A-Za-z]+\}", "", name)
        return self.tpl(name).strip()

    # ------------------------------------------------------------------ relatório e passos

    def note(self, level: str, message: str, cmd: Command | None = None) -> None:
        c = cmd or self.cmd
        self.report.append(ReportItem(level, c.line if c else 0, c.type if c else "", message))

    def step(self, type_: str, name: str = "", **fields: Any) -> dict[str, Any]:
        self.counter += 1
        st: dict[str, Any] = {"id": f"s{self.counter}", "type": type_}
        label = self.pending_comment or name
        if label:
            st["name"] = label[:200]
        self.pending_comment = ""
        st.update({k: v for k, v in fields.items() if v is not None})
        if self.continue_on_error and type_ not in ("if", "foreach", "try", "break", "continue", "stop", "fail"):
            st["continue_on_error"] = True
        return st

    def placeholder(self, cmd: Command, why: str) -> dict[str, Any]:
        self.note("nao_convertivel", why, cmd)
        desc = f" — {cmd.comment}" if cmd.comment else ""
        return self.step("fail", f"NÃO CONVERTIDO: {cmd.type}",
                         message=self.tpl(f"Passo do robô original não convertido (linha {cmd.line}: {cmd.type}{desc}). "
                                          f"{why} Reveja e substitua este passo."))

    def credential(self, kind: str, host: str) -> str:
        host = (host or "").lower()
        if kind == "http_basic":
            if "app.lusopay.com" in host:
                name = "cyclos-producao"
            elif "dev.lusopay.com" in host:
                name = "cyclos-dev"
            else:
                name = "api-" + re.sub(r"[^a-z0-9]+", "-", host).strip("-")[:60]
        elif kind == "smtp":
            if not host or "{" in host or "lusopay" in host:
                name = "smtp-lusopay"
            else:
                name = "smtp-" + re.sub(r"[^a-z0-9]+", "-", host).strip("-")[:60]
        else:
            name = "sql-magnimeios"
        self.credentials[name] = kind
        return name

    # ------------------------------------------------------------------ estrutura (blocos)

    def convert(self) -> list[dict[str, Any]]:
        cmds = [c for c in self.robot.commands if c.enabled]
        skipped = len(self.robot.commands) - len(cmds)
        if skipped:
            self.report.append(ReportItem("info", 0, "", f"{skipped} comando(s) comentado(s)/desativado(s) ignorados"))
        for c in cmds:
            c.type = ALIASES.get(c.type, c.type)
        steps, i, end = self.block(cmds, 0, ())
        while i < len(cmds):  # terminadores órfãos
            self.note("info", "fim de bloco sem início correspondente (ignorado)", cmds[i])
            more, i, _ = self.block(cmds, i + 1, ())
            steps.extend(more)
        return steps

    def block(self, cmds: list[Command], i: int, terminators: tuple[str, ...]) -> tuple[list[dict], int, str | None]:
        steps: list[dict[str, Any]] = []
        while i < len(cmds):
            c = cmds[i]
            if c.type in terminators:
                return steps, i, c.type
            if c.type in ("EndIfCommand", "EndLoopCommand", "ElseCommand", "EndTryCommand",
                          "CatchExceptionCommand", "FinallyCommand"):
                return steps, i, c.type  # terminador que não é deste bloco
            self.cmd = c
            if c.type in ("BeginIfCommand", "BeginMultiIfCommand"):
                step, i = self.if_block(cmds, i)
                steps.extend(step)
                continue
            if c.type in ("BeginListLoopCommand", "BeginNumberOfTimesLoopCommand", "BeginContinousLoopCommand",
                          "BeginLoopCommand"):
                step, i = self.loop_block(cmds, i)
                steps.extend(step)
                continue
            if c.type == "TryCommand":
                step, i = self.try_block(cmds, i)
                steps.extend(step)
                continue
            try:
                steps.extend(self.simple(c))
            except _Unsupported as exc:
                steps.append(self.placeholder(c, str(exc)))
            except (KeyError, ValueError, IndexError) as exc:
                steps.append(self.placeholder(c, f"Não foi possível ler os parâmetros ({type(exc).__name__}: {exc})."))
            i += 1
        return steps, i, None

    def if_block(self, cmds: list[Command], i: int) -> tuple[list[dict], int]:
        c = cmds[i]
        comment = self.pending_comment or c.comment
        self.pending_comment = ""
        try:
            cond = self.condition(c)
        except _Unsupported as exc:
            cond = None
            why = str(exc)
        then, j, term = self.block(cmds, i + 1, ("ElseCommand", "EndIfCommand"))
        otherwise: list[dict] = []
        if term == "ElseCommand":
            otherwise, j, term = self.block(cmds, j + 1, ("EndIfCommand",))
        if term != "EndIfCommand":
            self.note("aproximado", "If sem End If: o bloco foi fechado no fim do script", c)
        nxt = j + 1 if term == "EndIfCommand" else j
        if cond is None:
            self.pending_comment = comment
            return [self.placeholder(c, why)], nxt
        self.pending_comment = comment
        st = self.step("if", "Condição", condition=cond, then=then, otherwise=otherwise)
        self.note("convertido", "condição", c)
        return [st], nxt

    def loop_block(self, cmds: list[Command], i: int) -> tuple[list[dict], int]:
        c = cmds[i]
        comment = self.pending_comment or c.comment
        self.pending_comment = ""
        list_var = self.var(c.attrs.get("v_LoopParameter", "")) if c.type == "BeginListLoopCommand" else ""
        self.loop_lists.append(list_var)
        try:
            body, j, term = self.block(cmds, i + 1, ("EndLoopCommand",))
        finally:
            self.loop_lists.pop()
        nxt = j + 1 if term == "EndLoopCommand" else j
        if term != "EndLoopCommand":
            self.note("aproximado", "ciclo sem End Loop: fechado no fim do script", c)
        if not body:
            body = [self.step("log", "Ciclo vazio", message="(ciclo sem passos no robô original)")]
        a = c.attrs
        before: list[dict] = []
        if c.type == "BeginListLoopCommand":
            param = a.get("v_LoopParameter", "")
            items, item_var = f"{list_var}_colecao", list_var
            before = [self.step("set", "Lista do ciclo", variable=f"{list_var}_colecao",
                                expr=f"(({self.collection(param)}) | parsejson) or []")]
            self.note("convertido", "ciclo sobre lista", c)
        elif c.type == "BeginNumberOfTimesLoopCommand":
            start = self.num_expr(a.get("v_LoopStart") or "0")
            count = self.num_expr(a.get("v_LoopParameter") or "0")
            items, item_var = f"range({start}, {count})", "loop_counter"
            self.note("convertido", "ciclo N vezes", c)
        elif c.type == "BeginContinousLoopCommand":
            items, item_var = "range(100000)", "loop_counter"
            self.note("aproximado", "ciclo contínuo limitado a 100000 iterações (termina com 'Sair do ciclo')", c)
        else:  # BeginLoopCommand: repete enquanto a condição for verdadeira
            try:
                cond = self.condition(c)
            except _Unsupported as exc:
                self.pending_comment = comment
                return [self.placeholder(c, str(exc))], nxt
            self.counter += 1
            body = [{"id": f"s{self.counter}", "type": "if", "condition": f"not ({cond})",
                     "then": [{"id": f"s{self.counter}b", "type": "break"}], "otherwise": []}, *body]
            items, item_var = "range(100000)", "loop_counter"
            self.note("aproximado", "ciclo com condição convertido em ciclo com saída quando a condição deixa de ser verdadeira", c)
        carry = sorted(n for n in assigned_vars(body) if n != item_var)
        self.pending_comment = comment
        return [*before, self.step("foreach", "Ciclo", items_expr=items, item_variable=item_var, parallel=1,
                          carry=carry or None, steps=body)], nxt

    def try_block(self, cmds: list[Command], i: int) -> tuple[list[dict], int]:
        c = cmds[i]
        comment = self.pending_comment or c.comment
        self.pending_comment = ""
        body, j, term = self.block(cmds, i + 1, ("CatchExceptionCommand", "FinallyCommand", "EndTryCommand"))
        on_error: list[dict] = []
        if term == "CatchExceptionCommand":
            on_error, j, term = self.block(cmds, j + 1, ("FinallyCommand", "EndTryCommand"))
        final: list[dict] = []
        if term == "FinallyCommand":
            final, j, term = self.block(cmds, j + 1, ("EndTryCommand",))
        nxt = j + 1 if term == "EndTryCommand" else j
        if not body:
            return final, nxt
        self.pending_comment = comment
        self.note("convertido", "bloco Try/Catch", c)
        return [self.step("try", "Tentar", steps=body, on_error=on_error), *final], nxt

    # ------------------------------------------------------------------ condições

    def num_expr(self, s: str) -> str:
        e = self.expr(s)
        return f"(({e}) | num)"

    def condition(self, c: Command) -> str:
        if c.type == "BeginMultiIfCommand":
            conds = []
            for row in c.tables.get("v_IfConditionsTable", []):
                data = row.get("CommandData") or ""
                try:
                    sub = json.loads(data)
                except ValueError as exc:
                    raise _Unsupported("condição múltipla ilegível") from exc
                rows = sub.get("v_IfActionParameterTable") or []
                inner = Command(type="BeginIfCommand", attrs={"v_IfActionType": sub.get("v_IfActionType", "")},
                                tables={"v_IfActionParameterTable": [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows]},
                                line=c.line)
                conds.append(f"({self.condition(inner)})")
            if not conds:
                raise _Unsupported("condição múltipla sem condições")
            return " and ".join(conds)
        kind = c.attrs.get("v_IfActionType", "")
        p = table_rows_as_pairs(c.tables.get("v_IfActionParameterTable", []) or c.tables.get("v_LoopActionParameterTable", []))
        if kind in ("Value", "Variable Compare", "Date Compare"):
            v1, v2 = p.get("Value1", ""), p.get("Value2", "")
            if "{" not in v1 and "[" not in v1 and self._known(v1):
                self.note("aproximado", f"'{v1}' sem chavetas interpretado como variável", c)
                v1 = "{" + v1 + "}"
            cs = (p.get("Case Sensitive") or "No").lower().startswith("y")
            mode = "date" if kind == "Date Compare" else "text"
            op = p.get("Operand") or "is equal to"
            return f"taskt_compare({self.expr(v1)}, {json.dumps(op)}, {self.expr(v2)}, {cs}, {json.dumps(mode)})"
        if kind == "Variable Has Value":
            return f"(({self.expr(p.get('Variable Name', ''))}) | text) != ''"
        if kind == "Variable Is Numeric":
            return f"is_numeric({self.expr(p.get('Variable Name', ''))})"
        if kind == "File Exists":
            name = self.basename(p.get("File Path", ""))
            if name in self.persistent:
                self.note("convertido", f"verificação do ficheiro de controlo '{name}' (ficheiro persistente do fluxo)", c)
            else:
                self.note("aproximado", "'File Exists' só vê ficheiros criados nesta execução do fluxo", c)
            test = f"file_exists({json.dumps(name)})" if "{{" not in name else f"file_exists({self.expr(p.get('File Path', '').split(chr(92))[-1])})"
            return test if (p.get("True When") or "").lower().find("not") < 0 else f"not {test}"
        if kind == "Error Occured":
            self.note("aproximado", "'Error Occured' convertido para 'houve um erro tratado anteriormente'", c)
            return "last_error is defined"
        raise _Unsupported(f"tipo de condição '{kind}' (depende do ecrã/browser ou não tem equivalente).")

    # ------------------------------------------------------------------ comandos simples

    def simple(self, c: Command) -> list[dict[str, Any]]:
        t = c.type
        if t.startswith(UI_PREFIXES):
            raise _Unsupported("Automação de ecrã/browser não existe nos fluxos nativos; é preciso um equivalente por API.")
        handler: Callable[[Command], list[dict]] | None = getattr(self, "c_" + t, None)
        if handler is None:
            raise _Unsupported("Comando sem equivalente conhecido.")
        return handler(c)

    def c_CommentCommand(self, c):
        text = (c.comment or c.attrs.get("v_Comment", "")).strip()
        if text and not text.lower().startswith(("items in this section", "this section executes")):
            self.pending_comment = text[:200]
        return []

    def c_PauseCommand(self, c):
        self.note("ignorado", "pausa removida (o fluxo não precisa de esperar pelo ecrã)", c)
        return []

    c_SetEngineDelayCommand = c_PauseCommand

    def c_ErrorHandlingCommand(self, c):
        action = c.attrs.get("v_ErrorHandlingAction", "")
        self.continue_on_error = action.lower().startswith("continue")
        self.note("convertido", f"tratamento de erros: {action} (aplicado aos passos seguintes)", c)
        return []

    def c_StopTaskCommand(self, c):
        self.note("convertido", "terminar", c)
        return [self.step("stop", "Terminar", message="fim do robô")]

    def c_ExitLoopCommand(self, c):
        return [self.step("break", "Sair do ciclo")]

    def c_NextLoopCommand(self, c):
        return [self.step("continue", "Próxima iteração")]

    def c_VariableCommand(self, c):
        name = self.var(c.attrs.get("v_userVariableName", ""))
        self.note("convertido", f"variável {name}", c)
        return [self.step("set", f"Definir {name}", variable=name, value=self.tpl(c.attrs.get("v_Input", "")))]

    def _out(self, c, *keys):
        for k in keys:
            if c.attrs.get(k):
                return self.var(c.attrs[k])
        raise KeyError(keys[0])

    def _set_expr(self, c, out, expr, label):
        self.note("convertido", label, c)
        return [self.step("set", label, variable=out, expr=expr)]

    def c_RESTCommand(self, c):
        a = c.attrs
        url_raw = (a.get("v_BaseURL", "") + a.get("v_APIEndPoint", "")).strip()
        url = self.tpl(url_raw)
        if not url.lower().startswith("https://"):
            raise _Unsupported("O pedido usa http sem TLS ou um endereço variável; os fluxos só permitem https com host fixo.")
        method = (a.get("v_APIMethodType") or "GET").upper()
        headers, body, credential, query = {}, None, None, {}
        for row in c.tables.get("v_AdvancedParameters", []):
            ptype, pname, pval = row.get("Parameter Type", ""), row.get("Parameter Name", ""), row.get("Parameter Value", "")
            if ptype == "HttpHeader":
                if pname.lower() == "authorization":
                    credential = self.credential("http_basic", urlsplit(url_raw).hostname or "")
                else:
                    headers[pname] = self.tpl(pval)
            elif ptype == "RequestBody":
                body = self.tpl(pval)
                if row.get("Content Type"):
                    headers.setdefault("Content-Type", row["Content Type"])
            elif ptype in ("QueryString", "GetOrPost", "Query"):
                query[pname] = self.tpl(pval)
        for row in c.tables.get("v_RESTParameters", []):
            ptype, pname, pval = row.get("Parameter Type", ""), row.get("Parameter Name", ""), row.get("Parameter Value", "")
            if ptype.upper() in ("QUERYSTRING", "GETORPOST", "QUERY") and pname:
                query[pname] = self.tpl(pval)
            elif pname or pval:
                if body is None:
                    body = self.tpl(pval)
                self.note("aproximado", f"parâmetro REST '{ptype} {pname}' usado como corpo do pedido; confirme", c)
        if credential:
            self.note("convertido", f"autenticação substituída pela credencial '{credential}'", c)
        if method != "GET":
            self.writes_external = True
        out = self.var(a.get("v_userVariableName") or "resposta")
        self.note("convertido", f"pedido {method} à API", c)
        return [self.step("http_request", f"{method} {urlsplit(url_raw).path[:60]}", method=method, url=url,
                          headers=headers or None, query=query or None, body_text=body, credential=credential,
                          response="text", expect_status=[200, 201, 202, 204], timeout_seconds=300,
                          save_as=out, retries=2 if method == "GET" else 0)]

    def c_HTTPRequestCommand(self, c):
        url_raw = c.attrs.get("v_WebRequestURL", "")
        url = self.tpl(url_raw)
        if not url.lower().startswith("https://"):
            raise _Unsupported("O pedido usa http sem TLS ou um endereço que vem de uma variável; não é permitido nos fluxos.")
        if (c.attrs.get("v_WebRequestCredentials") or "No").lower().startswith("y"):
            self.note("aproximado", "o pedido usava as credenciais do Windows; sem credencial no fluxo", c)
        out = self.var(c.attrs.get("v_userVariableName") or "resposta")
        self.note("convertido", "download HTTP", c)
        return [self.step("http_request", "Download", method="GET", url=url, response="text",
                          expect_status=[200], timeout_seconds=300, save_as=out, retries=2)]

    def c_ParseJsonCommand(self, c):
        path = c.attrs.get("v_JsonExtractor", "")
        if "[?" in path:
            raise _Unsupported(f"JSONPath com filtro ({path}) não é suportado; use um ciclo com condição.")
        out = self._out(c, "v_applyToVariableName")
        return self._set_expr(c, out, f"({self.expr(c.attrs.get('v_InputValue', ''))}) | jsonpath({json.dumps(path)})",
                              f"Extrair {path}")

    def c_ParseJSONArrayCommand(self, c):
        out = self._out(c, "v_applyToVariableName")
        return self._set_expr(c, out, f"(({self.expr(c.attrs.get('v_InputValue', ''))}) | parsejson) or []", "Lista JSON")

    def c_ParseJsonModelCommand(self, c):
        steps = []
        src = self.expr(c.attrs.get("v_InputValue", ""))
        for row in c.tables.get("v_ParseObjects", []):
            sel, out = row.get("Json Selector", ""), row.get("Output Variable", "")
            if not out:
                continue
            if "[?" in sel:
                steps.append(self.placeholder(c, f"JSONPath com filtro ({sel}) não suportado."))
                continue
            steps.append(self.step("set", f"Extrair {sel}", variable=self.var(out),
                                   expr=f"({src}) | jsonpath({json.dumps(sel)})"))
        self.note("convertido", f"extração de {len(steps)} campo(s) JSON", c)
        return steps

    def c_GetListCountCommand(self, c):
        out = self._out(c, "v_UserVariableName", "v_applyToVariableName")
        return self._set_expr(c, out, f"(({self.collection(c.attrs.get('v_ListName', ''))}) | parsejson) | length", "Contar elementos")

    def c_GetListItemCommand(self, c):
        out = self._out(c, "v_UserVariableName", "v_applyToVariableName")
        return self._set_expr(c, out, f"(({self.collection(c.attrs.get('v_ListName', ''))}) | parsejson)[{self.num_expr(c.attrs.get('v_ItemIndex', '0'))}]",
                              "Obter elemento da lista")

    def c_StringReplaceCommand(self, c):
        out = self._out(c, "v_applyToVariableName", "v_userVariableName")
        src = self.expr(c.attrs.get("v_userVariableName", ""))
        find = self.expr(c.attrs.get("v_replacementText", ""))
        repl = self.expr(c.attrs.get("v_replacementValue", ""))
        return self._set_expr(c, out, f"(({src}) | text).replace(({find}) | text, ({repl}) | text)", "Substituir texto")

    def c_StringSplitCommand(self, c):
        out = self._out(c, "v_applyConvertToUserVariableName", "v_applyToVariableName")
        sep = c.attrs.get("v_splitCharacter", ",")
        return self._set_expr(c, out, f"({self.expr(c.attrs.get('v_userVariableName', ''))}) | split_text({self.expr(sep)})",
                              "Dividir texto")

    def c_TextExtractorCommand(self, c):
        out = self._out(c, "v_applyToVariableName")
        src = self.expr(c.attrs.get("v_InputValue", ""))
        p = table_rows_as_pairs(c.tables.get("v_TextExtractionTable", []))
        lead, trail = self.expr(p.get("Leading Text", "")), self.expr(p.get("Trailing Text", ""))
        skip = self.num_expr(p.get("Skip Past Occurences", "0") or "0")
        kind = c.attrs.get("v_TextExtractionType", "")
        if "Between" in kind:
            e = f"({src}) | between({lead}, {trail}, {skip})"
        elif "After" in kind:
            e = f"({src}) | after({lead}, {skip})"
        elif "Before" in kind:
            e = f"({src}) | before({trail}, {skip})"
        else:
            raise _Unsupported(f"tipo de extração '{kind}'")
        return self._set_expr(c, out, e, "Extrair texto")

    def c_ModifyVariableCommand(self, c):
        out = self._out(c, "v_applyToVariableName", "v_userVariableName")
        src = f"(({self.expr(c.attrs.get('v_userVariableName', ''))}) | text)"
        conv = (c.attrs.get("v_ConvertType") or "").lower()
        e = {"to upper case": f"{src}.upper()", "to lower case": f"{src}.lower()",
             "to base64 string": None}.get(conv, f"{src}.strip()" if "trim" in conv else None)
        if e is None:
            raise _Unsupported(f"conversão '{conv}'")
        return self._set_expr(c, out, e, "Modificar texto")

    def c_RegExExtractorCommand(self, c):
        out = self._out(c, "v_applyToVariableName")
        group = c.attrs.get("v_MatchGroupIndex") or "0"
        return self._set_expr(c, out, f"({self.expr(c.attrs.get('v_InputValue', ''))}) | regex({json.dumps(c.attrs.get('v_RegExExtractor', ''))}, {self.num_expr(group)})",
                              "Expressão regular")

    def c_StringSubstringCommand(self, c):
        out = self._out(c, "v_applyToVariableName", "v_userVariableName")
        src = f"(({self.expr(c.attrs.get('v_userVariableName', ''))}) | text)"
        start = self.num_expr(c.attrs.get("v_startIndex", "0") or "0")
        length = c.attrs.get("v_stringLength", "")
        e = f"{src}[{start}:]" if length in ("", "-1") else f"{src}[{start}:{start} + {self.num_expr(length)}]"
        return self._set_expr(c, out, e, "Parte do texto")

    def c_GetWordLengthCommand(self, c):
        out = self._out(c, "v_applyToVariableName")
        return self._set_expr(c, out, f"(({self.expr(c.attrs.get('v_InputValue', ''))}) | text) | length", "Comprimento")

    def c_MathCalculationCommand(self, c):
        out = self._out(c, "v_applyToVariableName")
        raw = c.attrs.get("v_InputValue", "")
        parts = self._parts(raw)
        pieces = []
        for kind, v in parts:
            if kind == "ref":
                pieces.append(f"({v} | num)")
            else:
                if not re.fullmatch(r"[\d\s+\-*/().,%]*", v):
                    raise _Unsupported(f"cálculo com texto não numérico: {raw}")
                if (c.attrs.get("v_DecimalSeperator") or ".") == ",":
                    v = re.sub(r"(\d),(\d)", r"\1.\2", v)
                pieces.append(v)
        e = "".join(pieces).strip() or "0"
        return self._set_expr(c, out, f"(({e})) | num", "Cálculo")

    def _date_input(self, raw: str) -> str:
        if raw.strip() in ("{DateTime.Now}", ""):
            return "now()"
        return f"(({self.expr(raw)}) | text | trim | todate)"

    def c_FormatDataCommand(self, c):
        out = self._out(c, "v_applyToVariableName")
        kind = (c.attrs.get("v_FormatType") or "").lower()
        fmt = c.attrs.get("v_ToStringFormat", "")
        raw = c.attrs.get("v_InputValue", "")
        if kind == "date":
            value = "{{ " + self._date_input(raw) + " | date(" + json.dumps(dotnet_date_format(fmt)) + ") }}"
        elif kind == "number":
            m = re.fullmatch(r"[NnFf](\d+)", fmt or "N2")
            if not m:
                raise _Unsupported(f"formato numérico '{fmt}'")
            value = "{{ " + f"(({self.expr(raw)}) | num) | decimal({m.group(1)})" + " }}"
            if fmt.upper().startswith("N"):
                self.note("aproximado", "formato N (com separador de milhares) convertido sem separador de milhares", c)
        else:
            raise _Unsupported(f"tipo de formatação '{kind}'")
        self.note("convertido", "formatação", c)
        return [self.step("set", "Formatar", variable=out, value=value)]

    def c_DateCalculationCommand(self, c):
        out = self._out(c, "v_applyToVariableName")
        method = c.attrs.get("v_CalculationMethod", "Add Days")
        sign = "-" if method.lower().startswith("subtract") else ""
        unit = method.split(" ", 1)[1].lower() if " " in method else "days"
        n = self.num_expr(c.attrs.get("v_Increment") or "0")
        fmt = dotnet_date_format(c.attrs.get("v_ToStringFormat", ""))
        value = "{{ " + f"{self._date_input(c.attrs.get('v_InputValue', ''))} | add_time({json.dumps(unit)}, {sign}{n}) | date({json.dumps(fmt)})" + " }}"
        self.note("convertido", "cálculo de data", c)
        return [self.step("set", "Calcular data", variable=out, value=value)]

    def c_WriteTextFileCommand(self, c):
        name = self.basename(c.attrs.get("v_FilePath", ""))
        if not name:
            raise _Unsupported("ficheiro sem nome")
        append = (c.attrs.get("v_Overwrite") or "").lower() == "append"
        self.written.add(name)
        if name in self.persistent:
            self.note("convertido", f"atualização do ficheiro de controlo '{name}' (gravado no fim da execução, mesmo que falhe)", c)
        else:
            self.note("convertido", f"escrita do ficheiro {name} (fica disponível na execução)", c)
        return [self.step("text_write", "Escrever ficheiro", file=name, content=self.tpl(c.attrs.get("v_TextToWrite", "")),
                          append=append or None)]

    def c_ReadTextFileCommand(self, c):
        name = self.basename(c.attrs.get("v_FilePath", ""))
        out = self.var(c.attrs.get("v_userVariableName") or "texto")
        if name in self.persistent:
            self.note("convertido", f"leitura do ficheiro de controlo '{name}' (ficheiro persistente do fluxo)", c)
            return [self.step("text_read", "Ler ficheiro de controlo", file=name, save_as=out, missing_ok=True)]
        if name in self.written:
            self.note("convertido", f"leitura de {name}", c)
            return [self.step("text_read", "Ler ficheiro", file=name, save_as=out)]
        if "config" in name.lower():
            self.note("ignorado", "leitura do Config.txt removida: as credenciais vêm do cofre", c)
            return [self.step("set", "Config.txt (removido)", variable=out, value="")]
        self.note("aproximado", f"o ficheiro '{name}' vivia no servidor de bots; fica vazio — forneça os dados por API, SQL ou variável", c)
        return [self.step("set", "Ficheiro do servidor de bots (vazio)", variable=out, value=""),
                self.step("log", "Aviso", level="WARNING",
                          message=self.tpl(f"Ficheiro '{name}' do servidor de bots não disponível: valor vazio"))]

    def c_DeleteFileCommand(self, c):
        name = self.basename(c.attrs.get("v_SourceFilePath", "") or c.attrs.get("v_FilePath", ""))
        if name in self.written or name in self.persistent:
            self.note("convertido", f"apagar {name} (o ficheiro é esvaziado)", c)
            return [self.step("text_write", "Apagar ficheiro", file=name, content="")]
        self.note("ignorado", "apagar ficheiro do servidor de bots (não se aplica)", c)
        return []

    def c_GetFilesCommand(self, c):
        out = self._out(c, "v_UserVariableName")
        self.note("aproximado", "listagem de pastas do servidor de bots: lista vazia", c)
        return [self.step("set", "Lista de ficheiros (vazia)", variable=out, expr="[]")]

    def _skip_file_op(self, c):
        self.note("ignorado", "operação sobre ficheiros/pastas do servidor de bots (não se aplica)", c)
        return []

    c_MoveFileCommand = c_RenameFileCommand = c_CreateFolderCommand = c_DeleteFolderCommand = _skip_file_op

    def c_SMTPSendEmailCommand(self, c):
        a = c.attrs
        cred = self.credential("smtp", a.get("v_SMTPHost", ""))
        to = self.tpl(a.get("v_SMTPToEmail", ""))
        if not to.strip():
            raise _Unsupported("email sem destinatários")
        att = []
        for raw in re.split(r"[;|]", a.get("v_SMTPAttachment", "") or ""):
            if raw.strip():
                name = self.basename(raw)
                att.append(name)
                if name not in self.written:
                    self.note("aproximado", f"anexo '{name}' não é criado pelo fluxo; o envio vai falhar até ser corrigido", c)
        self.sends_email = True
        self.note("convertido", f"email (credencial '{cred}'; a password do XML não foi copiada)", c)
        if self.test_email:
            # Enquanto email_teste tiver valor, todos os emails vão para lá; vazio = destinatários originais.
            to = "{{ email_teste if email_teste else (" + self.expr(a.get("v_SMTPToEmail", "")) + ") }}"
        return [self.step("email", "Enviar email", credential=cred, to=[to], subject=self.tpl(a.get("v_SMTPSubject", "")),
                          body=self.tpl(a.get("v_SMTPBody", "")), attachments=att or None)]

    def c_DatabaseDefineConnectionCommand(self, c):
        self.credential("mssql", "")
        self.note("convertido", "ligação à BD substituída pela credencial 'sql-magnimeios' (a connection string não foi copiada)", c)
        return []

    def c_DatabaseExecuteQueryCommand(self, c):
        cred = self.credential("mssql", "")
        query = (c.attrs.get("v_Query") or "").replace("[crLF]", "\n")
        params: dict[str, str] = {}

        def sub(m: re.Match) -> str:
            name = self.var(m.group(1))
            params[name] = "{{ " + (self._ref(m.group(1)) or name) + " | text }}"
            return f"%({name})s"

        query = re.sub(r"'?\{([A-Za-z_][\w\-]*)\}'?", sub, query)
        read_only = query.lstrip().lower().startswith(("select", "with"))
        if not read_only:
            self.writes_external = True
            self.note("aproximado", "consulta de escrita na base de dados: o fluxo fica de risco elevado", c)
        out = self.var(c.attrs.get("v_DatasetName") or "linhas")
        self.note("convertido", "consulta SQL (valores passados como parâmetros)", c)
        return [self.step("sql_query", "Consulta SQL", credential=cred, query=query, params=params or None,
                          save_as=out, read_only=read_only)]

    def c_GetDataRowCountCommand(self, c):
        out = self._out(c, "v_UserVariableName")
        return self._set_expr(c, out, f"({self.collection(c.attrs.get('v_DataTableName', ''))}) | length", "Número de linhas")

    def c_GetDataRowCommand(self, c):
        out = self._out(c, "v_UserVariableName")
        return self._set_expr(c, out, f"({self.collection(c.attrs.get('v_DataTableName', ''))})[{self.num_expr(c.attrs.get('v_DataRowIndex', '0'))}]",
                              "Obter linha")

    def c_GetDataRowValueCommand(self, c):
        out = self._out(c, "v_UserVariableName")
        row = self.expr(c.attrs.get("v_DataRowName", ""))
        if (c.attrs.get("v_Option") or "Index").lower() == "index":
            e = f"(({row}) | row_values)[{self.num_expr(c.attrs.get('v_DataValueIndex', '0'))}]"
        else:
            e = f"({row})[{self.expr(c.attrs.get('v_DataValueIndex', ''))}]"
        return self._set_expr(c, out, e, "Valor da linha")

    def c_LogDataCommand(self, c):
        self.note("convertido", "registo no log", c)
        return [self.step("log", "Registar", message=self.tpl(c.attrs.get("v_LogText", "")) or "-")]

    def c_MessageBoxCommand(self, c):
        self.note("convertido", "mensagem no ecrã passa a linha de log", c)
        return [self.step("log", "Mensagem", message=self.tpl(c.attrs.get("v_Message", "")) or "-")]

    def c_UserInputCommand(self, c):
        steps = []
        for row in c.tables.get("v_UserInputConfig", []):
            var = row.get("ApplyToVariable") or row.get("Apply To Variable") or ""
            if not var:
                continue
            name = self.var(var)
            default = row.get("DefaultValue") or row.get("Default Value") or ""
            steps.append(self.step("set", f"Valor pedido ao utilizador: {row.get('Label', name)}", variable=name,
                                   value=self.tpl(default)))
        self.note("aproximado", "o robô pedia valores ao utilizador; agora usa o valor por omissão — defina-o na variável", c)
        return steps

    def c_RunTaskCommand(self, c):
        path = c.attrs.get("v_taskPath", "")
        name = PureWindowsPath(path.replace("{Folder.ScriptPath}", "")).name
        if any(k in name.lower() for k in CONFIG_SCRIPTS):
            self.note("ignorado", f"sub-robô '{name}' (lia credenciais do Config.txt) removido: as credenciais vêm do cofre", c)
            return []
        raise _Unsupported(f"Chama o sub-robô '{name}'. Importe-o também e ligue os fluxos com uma regra 'Após outro bot', "
                           "ou copie os passos dele para aqui.")

    def c_StartProcessCommand(self, c):
        raise _Unsupported(f"Executa um programa no Windows ({PureWindowsPath(c.attrs.get('v_ProgramName', '')).name}).")


def assigned_vars(steps: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for st in steps:
        for key in ("variable", "save_as"):
            if st.get(key) and st["type"] in ("set", "append", "http_request", "extract", "sql_query", "text_read"):
                out.add(st[key])
        for key in ("steps", "then", "otherwise", "on_error"):
            if isinstance(st.get(key), list):
                out |= assigned_vars(st[key])
    return out


def suggest_key(name: str) -> str:
    import unicodedata

    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"\.(xml|obscript|json|zip)$", "", base)
    base = re.sub(r"^(ok|old|rever|old_ok)[ _-]+", "", base)
    key = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:70] or "fluxo"
    return f"{key}-importado"[:80]


def convert(robot: Robot, test_email: str = "") -> ConversionResult:
    tr = Translator(robot, test_email)
    steps = tr.convert()
    if not steps:
        steps = [{"id": "s1", "type": "log", "message": "robô vazio"}]
    names = (tr.referenced | assigned_vars(steps)) - {"loop_index", "loop_counter", "last_error", "files", "params", "run_id"}
    variables: dict[str, Any] = {}
    for n in sorted(names | set(tr.declared)):
        val = tr.declared.get(n, "")
        if SECRET_NAME.search(n) and val:
            tr.report.append(ReportItem("info", 0, "", f"valor inicial da variável '{n}' não copiado (parece um segredo)"))
            val = ""
        variables[n] = val
    if tr.sends_email and tr.test_email:
        variables["email_teste"] = tr.test_email
        tr.report.insert(0, ReportItem("info", 0, "", f"todos os emails vão para {tr.test_email} enquanto a variável "
                                                     "'email_teste' tiver valor; deixe-a vazia para usar os destinatários originais"))
    if tr.persistent:
        definition_files = sorted(tr.persistent)
        tr.report.insert(0, ReportItem("info", 0, "", "ficheiros de controlo (guardam o estado entre execuções): "
                                       + ", ".join(definition_files) + ". Depois de criar o fluxo, carregue o conteúdo "
                                       "atual em Editar fluxo → Ficheiros persistentes, antes da primeira execução"))
    title = re.sub(r"\.(xml|obscript|json)$", "", robot.name, flags=re.I)
    risk = "high" if tr.writes_external else ("medium" if tr.sends_email or tr.credentials else "low")
    definition = {"description": f"Importado de {robot.name} ({robot.source_format})", "variables": variables,
                  "steps": steps}
    if tr.persistent:
        definition["persistent_files"] = sorted(tr.persistent)
    return ConversionResult(name=title[:200], key=suggest_key(robot.name), source_format=robot.source_format,
                            definition=definition, report=tr.report, credentials=dict(sorted(tr.credentials.items())),
                            risk_level=risk, notes=robot.notes)
