"""Conversão entre robôs de fluxo (passos) e robôs Groovy (código).

Fluxo → Groovy: cada passo passa a uma instrução legível; as expressões e modelos Jinja são traduzidos para
Groovy com as mesmas funções auxiliares do motor (text, num, jsonpath, …), por isso o resultado executa da
mesma forma. O que não tem tradução fiel fica assinalado no relatório.

Groovy → fluxo: o código é analisado pelo compilador do Groovy (modo "ast" do anfitrião isolado) e cada
instrução reconhecida passa a um passo. Instruções sem equivalente (classes, métodos, closures complexas…)
impedem a conversão completa; com "forçar", ficam como passos "Falhar" com o código original na mensagem.

Nenhuma conversão grava nada: o resultado é proposto ao utilizador, que o revê e grava como nova versão
(as versões anteriores ficam sempre disponíveis).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from jinja2 import nodes
from jinja2.sandbox import SandboxedEnvironment

from .schema import NAME_RE

# --------------------------------------------------------------------------------------------- relatório


@dataclass
class Report:
    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, level: str, where: str, message: str) -> None:
        for it in self.items:  # o mesmo aviso em vários sítios fica numa só linha
            if it["level"] == level and it["message"] == message:
                if where and where not in it["where"]:
                    it["where"] = f"{it['where']}, {where}" if it["where"] else where
                return
        self.items.append({"level": level, "where": where, "message": message})

    @property
    def complete(self) -> bool:
        return not any(i["level"] == "erro" for i in self.items)


class Untranslatable(Exception):
    pass


# --------------------------------------------------------------------------------------------- fluxo → Groovy

_env = SandboxedEnvironment()
GROOVY_KEYWORDS = {"as", "assert", "break", "case", "catch", "class", "const", "continue", "def", "default", "do",
                   "else", "enum", "extends", "false", "finally", "for", "goto", "if", "implements", "import", "in",
                   "instanceof", "interface", "new", "null", "package", "return", "super", "switch", "this", "throw",
                   "throws", "trait", "true", "try", "var", "while", "it"}
RESERVED_BINDING = {"http", "email", "sql", "ficheiro", "log", "params", "run_id"}
HELPER_FILTERS = {"text", "num", "parsejson", "as_list", "jsonpath", "regex", "regex_replace", "regex_split",
                  "split_text", "between", "after", "before", "date", "add_days", "add_time", "todate", "money",
                  "decimal", "tojson", "fromjson", "find", "sample", "row_values"}
HELPER_GLOBALS = {"now", "today", "first_day_of_month", "taskt_compare", "is_numeric", "file_exists"}
STR_METHODS = {"upper": "toUpperCase", "lower": "toLowerCase", "strip": "trim", "replace": "replace",
               "startswith": "startsWith", "endswith": "endsWith", "lstrip": "stripLeading",
               "rstrip": "stripTrailing"}
CMPOPS = {"eq": "==", "ne": "!=", "gt": ">", "gteq": ">=", "lt": "<", "lteq": "<="}


def gstr(s: str) -> str:
    """Literal Groovy entre plicas (sem interpolação)."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "'"


def _gstring_part(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


class JinjaToGroovy:
    def __init__(self, local_names: set[str] | None = None):
        self.local_names = local_names or set()
        self.rename: dict[str, str] = {}  # variáveis de ciclos encaixados com o mesmo nome

    def expr(self, source: str) -> str:
        tpl = _env.parse("{{ (" + source + ") }}")
        out = tpl.body[0]
        assert isinstance(out, nodes.Output)
        return self.node(out.nodes[0])

    def template(self, source: str) -> str:
        """Modelo de texto → literal Groovy (GString quando tem expressões)."""
        tpl = _env.parse(source)
        parts: list[tuple[str, str]] = []
        for n in tpl.body:
            if not isinstance(n, nodes.Output):
                raise Untranslatable("modelo com {% … %} (blocos Jinja)")
            for x in n.nodes:
                if isinstance(x, nodes.TemplateData):
                    parts.append(("lit", x.data))
                else:
                    parts.append(("expr", self.node(x)))
        if all(k == "lit" for k, _ in parts):
            return gstr("".join(v for _, v in parts))
        if len(parts) == 1:
            return self._interp(parts[0][1])
        body = "".join(_gstring_part(v) if k == "lit" else "${" + self._interp(v) + "}" for k, v in parts)
        return '"' + body + '"'

    @staticmethod
    def _interp(code: str) -> str:
        # texto produzido por funções de texto não precisa de text(); o resto passa por text() (JSON, None → "")
        if re.fullmatch(r"(text|date|money|decimal|tojson|regex|regex_replace|between|after|before)\(.*\)", code):
            return code
        return f"text({code})"

    def node(self, n: nodes.Node) -> str:  # noqa: C901 - tradução nó a nó
        if isinstance(n, nodes.Const):
            v = n.value
            if v is None:
                return "null"
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, (int, float)):
                return repr(v)
            if isinstance(v, str):
                return gstr(v)
            raise Untranslatable(f"constante {v!r}")
        if isinstance(n, nodes.Name):
            if n.name in ("true", "True"):
                return "true"
            if n.name in ("false", "False"):
                return "false"
            if n.name in ("none", "None"):
                return "null"
            if n.name == "files":
                raise Untranslatable("a variável 'files' (lista de ficheiros criados) não existe no Groovy")
            return self.rename.get(n.name, n.name)
        if isinstance(n, nodes.Getattr):
            return f"{self._atom(n.node)}.{n.attr}"
        if isinstance(n, nodes.Getitem):
            if isinstance(n.arg, nodes.Slice):
                raise Untranslatable("fatias [a:b]")
            return f"{self._atom(n.node)}[{self.node(n.arg)}]"
        if isinstance(n, nodes.Filter):
            return self._filter(n)
        if isinstance(n, nodes.Call):
            return self._call(n)
        if isinstance(n, nodes.Compare):
            left = self._atom(n.expr)
            parts = []
            for op in n.ops:
                right = self._atom(op.expr)
                if op.op == "in":
                    parts.append(f"contem({right}, {left})")
                elif op.op == "notin":
                    parts.append(f"!contem({right}, {left})")
                else:
                    parts.append(f"{left} {CMPOPS[op.op]} {right}")
                left = right
            return " && ".join(parts) if len(parts) > 1 else parts[0]
        if isinstance(n, nodes.And):
            return f"({self.node(n.left)} && {self.node(n.right)})"
        if isinstance(n, nodes.Or):
            # "a or b" devolve o valor (como o ?: do Groovy), não um booleano
            return f"({self.node(n.left)} ?: {self.node(n.right)})"
        if isinstance(n, nodes.Not):
            return f"!{self._atom(n.node)}"
        if isinstance(n, nodes.Neg):
            return f"-{self._atom(n.node)}"
        if isinstance(n, nodes.Pos):
            return self.node(n.node)
        if isinstance(n, nodes.FloorDiv):
            return f"({self._atom(n.left)}).intdiv({self.node(n.right)})"
        if isinstance(n, nodes.Concat):
            return "(" + " + ".join(f"text({self.node(x)})" for x in n.nodes) + ")"
        if isinstance(n, nodes.BinExpr):
            op = n.operator if n.operator in ("+", "-", "*", "/", "%", "**") else None
            if not op:
                raise Untranslatable(f"operador {n.operator}")
            return f"({self.node(n.left)} {op} {self.node(n.right)})"
        if isinstance(n, nodes.CondExpr):
            other = self.node(n.expr2) if n.expr2 is not None else "null"
            return f"({self.node(n.test)} ? {self.node(n.expr1)} : {other})"
        if isinstance(n, (nodes.List, nodes.Tuple)):
            return "[" + ", ".join(self.node(x) for x in n.items) + "]"
        if isinstance(n, nodes.Dict):
            if not n.items:
                return "[:]"
            return "[" + ", ".join(f"({self.node(p.key)}): {self.node(p.value)}" if not isinstance(p.key, nodes.Const)
                                   else f"{gstr(str(p.key.value))}: {self.node(p.value)}" for p in n.items) + "]"
        if isinstance(n, nodes.Test):
            if n.name == "defined":
                return f"({self.node(n.node)} != null)"
            if n.name == "contains" and len(n.args) == 1:
                return f"contem({self.node(n.node)}, {self.node(n.args[0])})"
            raise Untranslatable(f"teste 'is {n.name}'")
        raise Untranslatable(f"expressão {type(n).__name__}")

    def _atom(self, n: nodes.Node) -> str:
        code = self.node(n)
        if re.fullmatch(r"[\w.]+(\[[^\]]*\])?|'[^']*'|\(.*\)|\w+\(.*\)", code):
            return code
        return f"({code})"

    def _args(self, n: nodes.Filter | nodes.Call) -> list[str]:
        if n.dyn_args or n.dyn_kwargs:
            raise Untranslatable("argumentos *args/**kwargs")
        return [self.node(a) for a in n.args]

    def _filter(self, n: nodes.Filter) -> str:
        name, args = n.name, self._args(n)
        kw = {k.key: self.node(k.value) for k in n.kwargs}
        v = self.node(n.node)
        if name == "text" and not args and not kw and (isinstance(n.node, nodes.Const) and isinstance(n.node.value, str)
                                                         or v.startswith("text(")):
            return v
        if name in HELPER_FILTERS and not kw:
            return f"{name}({', '.join([v, *args])})"
        if name in ("length", "count"):
            return f"length({v})"
        if name == "default":
            d = args[0] if args else "''"
            return f"({v} != null ? {v} : {d})"
        if name == "join":
            return f"as_list({v}).join({args[0] if args else gstr('')})"
        if name == "upper":
            return f"text({v}).toUpperCase()"
        if name == "lower":
            return f"text({v}).toLowerCase()"
        if name == "trim":
            return f"text({v}).trim()"
        if name == "string":
            return f"text({v})"
        if name == "int":
            return f"(num({v}) as long)"
        if name == "float":
            return f"(num({v}) as double)"
        if name == "abs":
            return f"Math.abs(num({v}))"
        if name == "replace" and len(args) == 2:
            return f"text({v}).replace({args[0]}, {args[1]})"
        if name == "first":
            return f"as_list({v})[0]"
        if name == "last":
            return f"as_list({v})[-1]"
        if name == "list":
            return f"as_list({v})"
        if name == "reverse":
            return f"as_list({v}).reverse()"
        if name == "unique":
            return f"as_list({v}).unique(false)"
        if name == "sort" and not args and not kw:
            return f"as_list({v}).sort(false)"
        if name == "round":
            places = args[0] if args else (kw.get("precision") or "0")
            return f"(num({v}) as BigDecimal).setScale({places}, java.math.RoundingMode.HALF_UP)"
        if name == "sum":
            if "attribute" in kw:
                return f"as_list({v}).sum(0) {{ num(it[{kw['attribute']}]) }}"
            return f"as_list({v}).sum(0) {{ num(it) }}"
        if name == "map" and "attribute" in kw and not args:
            return f"as_list({v}).collect {{ it[{kw['attribute']}] }}"
        if name == "selectattr" and args:
            attr = args[0]
            if len(args) == 1:
                return f"as_list({v}).findAll {{ it[{attr}] }}"
            if len(args) == 3 and args[1] in ("'equalto'", "'eq'", "'=='"):
                return f"as_list({v}).findAll {{ it[{attr}] == {args[2]} }}"
        if name == "rejectattr" and len(args) == 1:
            return f"as_list({v}).findAll {{ !it[{args[0]}] }}"
        raise Untranslatable(f"filtro '{name}'")

    def _call(self, n: nodes.Call) -> str:
        args = self._args(n)
        if n.kwargs:
            raise Untranslatable("argumentos com nome numa chamada")
        f = n.node
        if isinstance(f, nodes.Name):
            if f.name in HELPER_GLOBALS:
                return f"{f.name}({', '.join(args)})"
            if f.name == "range":
                if len(args) == 1:
                    return f"(0..<{args[0]})"
                if len(args) == 2:
                    return f"({args[0]}..<{args[1]})"
            raise Untranslatable(f"função '{f.name}'")
        if isinstance(f, nodes.Getattr):
            obj = self._atom(f.node)
            m = f.attr
            if m in STR_METHODS:
                base = obj if obj.startswith("text(") else f"text({obj})"
                return f"{base}.{STR_METHODS[m]}({', '.join(args)})"
            if m == "split":
                return f"split_text({obj}, {args[0]})" if args else f"text({obj}).split() as List"
            if m == "join" and len(args) == 1:
                return f"as_list({args[0]}).join({obj})"
            if m == "get" and args:
                d = args[1] if len(args) > 1 else "null"
                return f"({obj}[{args[0]}] != null ? {obj}[{args[0]}] : {d})"
            if m in ("keys", "values") and not args:
                return f"({obj} as Map).{m}() as List"
            if m == "items" and not args:
                return f"({obj} as Map).collect {{ k, v -> [k, v] }}"
            if m == "find" and len(args) == 1:
                return f"text({obj}).indexOf({args[0]})"
            if m == "count" and len(args) == 1:
                return f"text({obj}).count({args[0]})"
            if m in ("isdigit", "isnumeric") and not args:
                return f"(text({obj}) ==~ /\\d+/)"
            if m == "zfill" and len(args) == 1:
                return f"text({obj}).padLeft({args[0]}, '0')"
            if m == "format":
                raise Untranslatable("str.format()")
            if m in ("year", "month", "day", "hour", "minute", "second"):
                return f"{obj}.{m}"
            raise Untranslatable(f"método '.{m}()'")
        raise Untranslatable("chamada")


class FlowToGroovy:
    def __init__(self, definition: dict[str, Any]):
        self.d = definition
        self.report = Report()
        self.lines: list[str] = []
        self.ind = 0
        self.tr = JinjaToGroovy()
        self.catch_depth = 0
        self.loop_vars: list[str] = []

    def emit(self, line: str = "") -> None:
        self.lines.append(("    " * self.ind + line) if line else "")

    def safe(self, sid: str, fn, *a) -> str | None:
        try:
            return fn(*a)
        except Untranslatable as exc:
            self.report.add("erro", sid, f"sem tradução: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001 - modelo/expressão inválidos
            self.report.add("erro", sid, f"expressão inválida: {exc}")
            return None

    def T(self, sid: str, tpl: str) -> str:  # noqa: N802 - modelo → Groovy
        r = self.safe(sid, self.tr.template, tpl)
        return r if r is not None else gstr(tpl)

    def E(self, sid: str, expr: str) -> str:  # noqa: N802 - expressão → Groovy
        r = self.safe(sid, self.tr.expr, expr)
        return r if r is not None else f"null /* não traduzido: {expr.replace('*/', '* /')} */"

    def convert(self) -> tuple[str, Report]:
        d = self.d
        self.emit(f"// {d.get('description') or 'Robô'}")
        self.emit("// Convertido automaticamente do editor de fluxos. Variáveis do robô, params e run_id estão disponíveis")
        self.emit("// pelo nome; http/email/sql/ficheiro usam as credenciais do cofre (ver Ajuda no editor).")
        self.emit()
        needs_last_error = "last_error" in json.dumps(d.get("steps", []))
        if needs_last_error and "last_error" not in (d.get("variables") or {}):
            self.emit("last_error = null")
        for name in sorted(self._append_targets(d.get("steps", []))):
            init = (d.get("variables") or {}).get(name)
            if not isinstance(init, list):
                self.emit(f"{name} = []  // lista usada por 'Acrescentar a lista'")
                if name in (d.get("variables") or {}):
                    self.report.add("aviso", name, f"a variável '{name}' passa a começar como lista vazia")
        for name in (d.get("variables") or {}):
            if name in RESERVED_BINDING or name in GROOVY_KEYWORDS:
                self.report.add("erro", name, f"o nome de variável '{name}' é reservado no Groovy")
        self.block(d.get("steps", []))
        code = "\n".join(self.lines).rstrip() + "\n"
        return code, self.report

    def _append_targets(self, steps: list[dict]) -> set[str]:
        out = set()
        for st in steps:
            if st.get("type") == "append":
                out.add(st["variable"])
            for k in ("steps", "then", "otherwise", "on_error"):
                out |= self._append_targets(st.get(k) or [])
        return out

    def block(self, steps: list[dict]) -> None:
        for st in steps:
            if st.get("name"):
                self.emit(f"// {st['name']}")
            if st.get("continue_on_error") and st["type"] not in ("if", "foreach", "try"):
                self.emit("try {")
                self.ind += 1
                self.step(st)
                self.ind -= 1
                ev = "e" if self.catch_depth == 0 else f"e{self.catch_depth + 1}"
                self.emit(f"}} catch ({ev}) {{")
                self.ind += 1
                self.emit(f"last_error = {ev}.message")
                self.emit('aviso "erro ignorado: ${' + ev + '.message}"')
                self.ind -= 1
                self.emit("}")
            else:
                self.step(st)

    def step(self, s: dict) -> None:  # noqa: C901 - um ramo por tipo de passo
        t, sid = s["type"], s["id"]
        if t == "set":
            v = self.T(sid, s["value"]) if s.get("value") is not None else self.E(sid, s["expr"])
            self.emit(f"{s['variable']} = {v}")
        elif t == "extract":
            self.emit(f"{s['save_as']} = extrair({self.E(sid, s['source_expr'])}, {gstr(s['path'])})")
        elif t == "append":
            self.emit(f"{s['variable']} << {self.E(sid, s['expr'])}")
        elif t == "log":
            fn = {"WARNING": "aviso", "ERROR": "erro"}.get(s.get("level", "INFO"), "log")
            self.emit(f"{fn} {self.T(sid, s['message'])}")
        elif t == "fail":
            self.emit(f"falhar({self.T(sid, s['message'])})")
        elif t == "stop":
            self.emit(f"terminar({self.T(sid, s.get('message', ''))})")
        elif t == "http_request":
            self._http(s)
        elif t == "csv_write":
            cols = [c["header"] for c in s["columns"]]
            tr = JinjaToGroovy()
            values = []
            for c in s["columns"]:
                r = self.safe(sid, tr.template, c["value"])
                values.append(f"{gstr(c['header'])}: {r if r is not None else gstr(c['value'])}")
            rows = self.E(sid, s["rows_expr"])
            sep = f", separador: {gstr(s['delimiter'])}" if s.get("delimiter", ";") != ";" else ""
            self.emit(f"ficheiro.csv({self.T(sid, s['file'])}, as_list({rows}).collect {{ row -> [{', '.join(values)}] }},")
            self.emit(f"             colunas: [{', '.join(gstr(c) for c in cols)}]{sep})")
        elif t == "text_write":
            fn = "acrescentar" if s.get("append") else "gravar"
            self.emit(f"ficheiro.{fn}({self.T(sid, s['file'])}, {self.T(sid, s['content'])})")
        elif t == "text_read":
            if s.get("missing_ok"):
                self.emit(f"{s['save_as']} = ficheiro.ler({self.T(sid, s['file'])}) ?: ''")
            else:
                f = self.T(sid, s["file"])
                self.emit(f"{s['save_as']} = ficheiro.ler({f})")
                self.emit(f'if ({s["save_as"]} == null) falhar("ficheiro ${{{f}}} não existe nesta execução")')
        elif t == "email":
            parts = [f"credencial: {gstr(s['credential'])}", f"para: [{', '.join(self.T(sid, x) for x in s['to'])}]"]
            if s.get("cc"):
                parts.append(f"cc: [{', '.join(self.T(sid, x) for x in s['cc'])}]")
            parts += [f"assunto: {self.T(sid, s['subject'])}", f"corpo: {self.T(sid, s['body'])}"]
            if s.get("attachments"):
                parts.append(f"anexos: [{', '.join(self.T(sid, x) for x in s['attachments'])}]")
            self.emit("email.enviar(" + (",\n" + "    " * self.ind + "             ").join(parts) + ")")
        elif t == "sql_query":
            names: list[str] = []
            query = re.sub(r"%\((\w+)\)s", lambda m: names.append(m.group(1)) or f":{m.group(1)}", s["query"])
            query = query.replace("%%", "%")
            params = s.get("params") or {}
            pmap = ", ".join(f"{k}: {self.T(sid, v)}" for k, v in params.items())
            fn = "consultar" if s.get("read_only", True) else "executar"
            q = '"""' + query.replace("\\", "\\\\").replace('"""', '\\"\\"\\"').replace("$", "\\$") + '"""'
            target = f"{s['save_as']} = " if s.get("save_as") else ""
            self.emit(f"{target}sql.{fn}({gstr(s['credential'])}, {q}" + (f", [{pmap}])" if pmap else ")"))
        elif t == "foreach":
            self._foreach(s)
        elif t == "if":
            self.emit(f"if ({self.E(sid, s['condition'])}) {{")
            self.ind += 1
            self.block(s.get("then") or [])
            self.ind -= 1
            if s.get("otherwise"):
                self.emit("} else {")
                self.ind += 1
                self.block(s["otherwise"])
                self.ind -= 1
            self.emit("}")
        elif t == "try":
            self.emit("try {")
            self.ind += 1
            self.block(s.get("steps") or [])
            self.ind -= 1
            self.catch_depth += 1
            ev = "e" if self.catch_depth == 1 else f"e{self.catch_depth}"  # catch encaixado não pode repetir o nome
            self.emit(f"}} catch ({ev}) {{")
            self.ind += 1
            self.emit(f"last_error = {ev}.message")
            self.emit('aviso "erro tratado: ${' + ev + '.message}"')
            self.block(s.get("on_error") or [])
            self.ind -= 1
            self.catch_depth -= 1
            self.emit("}")
        elif t == "break":
            self.emit("break")
        elif t == "continue":
            self.emit("continue")
        else:
            self.report.add("erro", sid, f"tipo de passo '{t}' sem equivalente")
            self.emit(f"falhar('passo {sid} ({t}) não convertido')")

    def _http(self, s: dict) -> None:
        sid = s["id"]
        method = s.get("method", "GET").lower()
        opts: list[str] = []
        if s.get("credential"):
            opts.append(f"credencial: {gstr(s['credential'])}")
        if s.get("headers"):
            opts.append("headers: [" + ", ".join(f"{gstr(k)}: {self.T(sid, v)}" for k, v in s["headers"].items()) + "]")
        if s.get("query"):
            opts.append("query: [" + ", ".join(f"{gstr(k)}: {self.T(sid, v)}" for k, v in s["query"].items()) + "]")
        # o Groovy aceita qualquer 2xx; só se escreve "esperar" quando o fluxo aceitava outros códigos
        expect = s.get("expect_status") or [200]
        if not set(expect) <= {200, 201, 202, 204}:
            opts.append(f"esperar: [{', '.join(str(x) for x in expect)}]")
        if s.get("response") == "text":
            opts.append("resposta: 'texto'")
        retries = int(s.get("retries", 0))
        if retries and retries != 2:
            opts.append(f"tentativas: {retries}")
        timeout = s.get("timeout_seconds", 30)
        if timeout not in (30, 60):
            opts.append(f"timeout: {timeout}")
        args = [self.T(sid, s["url"])]
        if method in ("post", "put", "patch"):
            if s.get("body_json_expr"):
                args.append(self.E(sid, s["body_json_expr"]))
            elif s.get("body_text") is not None:
                args.append(self.T(sid, s["body_text"]))
        target = f"{s['save_as']} = " if s.get("save_as") else ""
        if s.get("save_as") and f"{s['save_as']}_status" in json.dumps(self.d.get("steps", [])):
            self.report.add("erro", sid, f"'{s['save_as']}_status' (código HTTP) não existe no Groovy: use 'esperar: [...]'")
        self.emit(f"{target}http.{method}({', '.join(args + opts)})")

    def _foreach(self, s: dict) -> None:
        sid = s["id"]
        items = self.E(sid, s["items_expr"])
        var = s.get("item_variable", "item")
        original = var
        if var in self.loop_vars:  # ciclo dentro de outro com a mesma variável: o Groovy não deixa repetir o nome
            n = 2
            while f"{var}{n}" in self.loop_vars:
                n += 1
            var = f"{var}{n}"
        previous = self.tr.rename.get(original)
        self.tr.rename[original] = var
        self.loop_vars.append(var)
        try:
            self._foreach_body(s, sid, items, var)
        finally:
            self.loop_vars.pop()
            if previous is None:
                self.tr.rename.pop(original, None)
            else:
                self.tr.rename[original] = previous

    def _foreach_body(self, s: dict, sid: str, items: str, var: str) -> None:
        body_json = json.dumps(s.get("steps") or [])
        uses_index = "loop_index" in body_json
        par = int(s.get("parallel", 1))
        assigned = _assigned(s.get("steps") or []) - set(s.get("carry") or []) - {var}
        if assigned:
            self.report.add("aviso", sid, "no Groovy, as variáveis alteradas dentro do ciclo (" + ", ".join(sorted(assigned))
                            + ") ficam com o último valor depois do ciclo")
        if par > 1:
            if '"type": "break"' in body_json:
                self.report.add("erro", sid, "'Sair do ciclo' num ciclo em paralelo não tem equivalente")
            self.emit(f"paralelo({self._iterable(items)}, {par}) {{ {var} ->")
            self.ind += 1
            if uses_index:
                self.report.add("erro", sid, "loop_index num ciclo em paralelo não tem equivalente")
            self._loop_body(s, parallel=True)
            self.ind -= 1
            self.emit("}")
            return
        if uses_index:
            self.emit("loop_index = -1")
        self.emit(f"for ({var} in {self._iterable(items)}) {{")
        self.ind += 1
        if uses_index:
            self.emit("loop_index++")
        self._loop_body(s, parallel=False)
        self.ind -= 1
        self.emit("}")

    @staticmethod
    def _iterable(items: str) -> str:
        if re.fullmatch(r"\(\S+\.\.<\S+\)", items) or items.startswith("as_list("):
            return items
        return f"as_list({items})"

    def _loop_body(self, s: dict, parallel: bool) -> None:
        if parallel and '"type": "continue"' in json.dumps(s.get("steps") or []):
            # continue numa closure = return
            start = len(self.lines)
            self.block(s.get("steps") or [])
            for i in range(start, len(self.lines)):
                if self.lines[i].strip() == "continue":
                    self.lines[i] = self.lines[i].replace("continue", "return")
        else:
            self.block(s.get("steps") or [])


def _assigned(steps: list[dict]) -> set[str]:
    out: set[str] = set()
    for st in steps:
        for key in ("variable", "save_as"):
            if st.get(key) and st["type"] in ("set", "http_request", "extract", "sql_query", "text_read"):
                out.add(st[key])
        for k in ("steps", "then", "otherwise", "on_error"):
            out |= _assigned(st.get(k) or [])
    return out


def flow_to_groovy(definition: dict[str, Any]) -> tuple[dict[str, Any], Report]:
    code, report = FlowToGroovy(definition).convert()
    new_def = {k: v for k, v in definition.items() if k not in ("steps", "code")}
    new_def["language"] = "groovy"
    new_def["code"] = code
    return new_def, report


# --------------------------------------------------------------------------------------------- Groovy → fluxo

GROOVY_HELPERS_AS_FILTERS = HELPER_FILTERS
STR_METHODS_BACK = {"toUpperCase": "upper", "toLowerCase": "lower", "trim": "strip", "replace": "replace",
                    "startsWith": "startswith", "endsWith": "endswith"}
BIN_BACK = {"==": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">=", "+": "+", "-": "-", "*": "*",
            "/": "/", "%": "%", "**": "**", "&&": "and", "||": "or"}


def jstr(s: str) -> str:
    """Literal de texto Jinja."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r") + "'"


class GroovyToFlow:
    def __init__(self, code: str, ast: dict[str, Any], force: bool):
        self.code_lines = code.splitlines()
        self.ast = ast
        self.force = force
        self.report = Report()
        self.n = 0
        self.catch_vars: list[str] = []
        self.loop_vars: list[str] = []

    def sid(self) -> str:
        self.n += 1
        return f"s{self.n}"

    def source(self, node: dict) -> str:
        a, b = node.get("line", 0), node.get("lastLine", 0)
        if a < 1 or b < a:
            return ""
        lines = self.code_lines[a - 1:b]
        if len(lines) == 1:
            return lines[0][max(node.get("col", 1) - 1, 0):max(node.get("lastCol", 0) - 1, 0)] or lines[0].strip()
        return "\n".join(lines)

    def unsupported(self, node: dict, why: str) -> list[dict]:
        line = node.get("line", 0)
        self.report.add("erro", f"linha {line}", why)
        src = self.source(node).strip()[:500]
        return [{"id": self.sid(), "type": "fail", "name": f"NÃO CONVERTIDO (linha {line})",
                 "message": self.tpl_lit(f"Código Groovy sem equivalente no editor de fluxos ({why}): {src}")}]

    @staticmethod
    def tpl_lit(s: str) -> str:
        """Texto literal dentro de um campo de modelo (protege {{ }} e {% %})."""
        if "{{" in s or "{%" in s or "{#" in s:
            return "{% raw %}" + s + "{% endraw %}"
        return s

    def convert(self) -> tuple[list[dict], Report]:
        for m in self.ast.get("methods", []):
            self.report.add("erro", f"linha {m.get('line')}", f"o método '{m.get('name')}' não tem equivalente em fluxo")
        for c in self.ast.get("classes", []):
            self.report.add("erro", f"linha {c.get('line')}", f"a classe '{c.get('name')}' não tem equivalente em fluxo")
        steps = self.block(self.ast["body"])
        if not steps:
            steps = [{"id": self.sid(), "type": "log", "message": "(robô vazio)"}]
        return steps, self.report

    def block(self, node: dict | None) -> list[dict]:
        if node is None:
            return []
        if node["k"] == "block":
            out: list[dict] = []
            for st in node["body"]:
                new = self.stmt(st)
                # "if (x == null) falhar(...)" logo a seguir a "x = ficheiro.ler(...)" é o comportamento do passo
                if (len(new) == 1 and new[0]["type"] == "if" and out and out[-1]["type"] == "text_read"
                        and not out[-1].get("missing_ok") and new[0]["condition"] == f"({out[-1]['save_as']} == none)"
                        and len(new[0]["then"]) == 1 and new[0]["then"][0]["type"] == "fail" and not new[0]["otherwise"]):
                    continue
                out += new
            return out
        return self.stmt(node)

    # ------------------------------------------------------------- instruções

    def stmt(self, st: dict) -> list[dict]:  # noqa: C901
        k = st["k"]
        try:
            if k == "empty":
                return []
            if k == "block":
                return self.block(st)
            if k == "expr":
                return self.expr_stmt(st["expr"])
            if k == "if":
                return [{"id": self.sid(), "type": "if", "condition": self.E(st["cond"]),
                         "then": self.block(st["then"]), "otherwise": self.block(st.get("else"))}]
            if k == "for":
                self.loop_vars.append(st["var"])
                try:
                    body = self.block(st["body"])
                finally:
                    self.loop_vars.pop()
                return [self._loop(self.items(st["coll"]), st["var"], body)]
            if k == "while":
                cond = st["cond"]
                body = self.block(st["body"])
                if not (cond["k"] == "const" and cond.get("value") is True):
                    body = [{"id": self.sid(), "type": "if", "condition": f"not ({self.E(cond)})",
                             "then": [{"id": self.sid(), "type": "break"}], "otherwise": []}, *body]
                self.report.add("aviso", f"linha {st['line']}", "ciclo 'while' convertido num ciclo com até 100000 voltas")
                return [self._loop("range(100000)", "volta", body)]
            if k == "try":
                if st.get("finally"):
                    return self.unsupported(st, "bloco 'finally'")
                catches = st.get("catches") or []
                if len(catches) > 1:
                    return self.unsupported(st, "vários 'catch'")
                self.catch_vars.append(catches[0]["var"] if catches else "")
                try:
                    body = catches[0]["body"] if catches else None
                    if body and body["k"] == "block":
                        # "last_error = e.message" e o aviso "erro tratado" são automáticos no passo "Tentar"
                        body = {**body, "body": [x for x in body["body"] if not self._auto_catch_line(x, catches[0]["var"])]}
                    on_error = self.block(body) if body else []
                finally:
                    self.catch_vars.pop()
                return [{"id": self.sid(), "type": "try", "steps": self.block(st["body"]) or self._empty(),
                         "on_error": on_error}]
            if k == "break":
                return [{"id": self.sid(), "type": "break"}]
            if k == "continue":
                return [{"id": self.sid(), "type": "continue"}]
            if k == "return":
                if self.loop_vars:
                    return self.unsupported(st, "'return' dentro de um ciclo")
                return [{"id": self.sid(), "type": "stop", "message": ""}]
            if k == "throw":
                return [{"id": self.sid(), "type": "fail", "message": "{{ " + self.E(st["expr"]) + " }}"}]
            return self.unsupported(st, st.get("what") or k)
        except Untranslatable as exc:
            return self.unsupported(st, str(exc))

    @staticmethod
    def _auto_catch_line(st: dict, var: str) -> bool:
        if st["k"] != "expr":
            return False
        e = st["expr"]
        if e["k"] == "assign" and e["target"].get("name") == "last_error" and e["value"]["k"] == "prop" \
                and e["value"]["obj"].get("name") == var and e["value"]["prop"] == "message":
            return True
        return (e["k"] == "call" and e.get("obj") is None and e["method"] == "aviso" and len(e["args"]) == 1
                and e["args"][0]["k"] == "gstring" and e["args"][0]["strings"][:1] == ["erro tratado: "])

    def _loop(self, items: str, var: str, body: list[dict]) -> dict:
        step = {"id": self.sid(), "type": "foreach", "items_expr": items, "item_variable": var, "parallel": 1,
                "steps": body or self._empty()}
        # no Groovy as variáveis alteradas no ciclo mantêm o valor; no fluxo isso é o "carry"
        carry = sorted(_assigned(body) - {var})
        if carry:
            step["carry"] = carry
        return step

    @staticmethod
    def _empty() -> list[dict]:
        return [{"id": "vazio", "type": "log", "message": "(sem passos)"}]

    def items(self, e: dict) -> str:
        if e["k"] == "range":
            a, b = self.E(e["from"]), self.E(e["to"])
            return f"range({a}, ({b}) + 1)" if e.get("inclusive") else f"range({a}, {b})"
        return self.E(e)

    def expr_stmt(self, e: dict) -> list[dict]:  # noqa: C901
        k = e["k"]
        if k == "assign":
            tgt = e["target"]
            if tgt["k"] != "var":
                raise Untranslatable("atribuição a uma propriedade ou índice")
            name = tgt["name"]
            if not re.match(NAME_RE, name):
                raise Untranslatable(f"nome de variável '{name}'")
            v = e["value"]
            if v["k"] == "call" and v.get("obj") and v["obj"].get("k") == "var":
                api = self.api_call(v, save_as=name)
                if api is not None:
                    return api
            if v["k"] == "elvis" and v["left"]["k"] == "call" and v["left"].get("method") == "ler" \
                    and (v["left"].get("obj") or {}).get("name") == "ficheiro" and v["right"]["k"] == "const" and v["right"].get("value") == "":
                return [{"id": self.sid(), "type": "text_read", "file": self.T(v["left"]["args"][0]), "save_as": name,
                         "missing_ok": True}]
            if v["k"] == "call" and v.get("obj") is None and v["method"] == "extrair" and len(v["args"]) == 2 \
                    and v["args"][1]["k"] == "const":
                return [{"id": self.sid(), "type": "extract", "source_expr": self.E(v["args"][0]),
                         "path": v["args"][1]["value"], "save_as": name}]
            if v["k"] in ("gstring",) or (v["k"] == "const" and isinstance(v.get("value"), str)):
                return [{"id": self.sid(), "type": "set", "variable": name, "value": self.T(v)}]
            return [{"id": self.sid(), "type": "set", "variable": name, "expr": self.E(v)}]
        if k == "bin" and e["op"] == "<<" and e["left"]["k"] == "var":
            return [{"id": self.sid(), "type": "append", "variable": e["left"]["name"], "expr": self.E(e["right"])}]
        if k == "incdec" and e["expr"]["k"] == "var":
            name = e["expr"]["name"]
            op = "+" if e["op"] == "++" else "-"
            return [{"id": self.sid(), "type": "set", "variable": name, "expr": f"({name} | num) {op} 1"}]
        if k == "call":
            if e.get("obj") and e["obj"].get("k") == "var" and e["obj"]["name"] not in self.loop_vars:
                if e["method"] == "add" and len(e["args"]) == 1 and e["obj"]["name"] not in ("http", "email", "sql", "ficheiro"):
                    return [{"id": self.sid(), "type": "append", "variable": e["obj"]["name"], "expr": self.E(e["args"][0])}]
                api = self.api_call(e, save_as=None)
                if api is not None:
                    return api
            if e.get("obj") is None:
                m, args = e["method"], e["args"]
                if m in ("log", "println", "aviso", "erro") and len(args) <= 1:
                    level = {"aviso": "WARNING", "erro": "ERROR"}.get(m, "INFO")
                    step = {"id": self.sid(), "type": "log", "message": self.T(args[0]) if args else ""}
                    if level != "INFO":
                        step["level"] = level
                    return [step]
                if m == "falhar" and len(args) == 1:
                    return [{"id": self.sid(), "type": "fail", "message": self.T(args[0])}]
                if m == "terminar" and len(args) <= 1:
                    return [{"id": self.sid(), "type": "stop", "message": self.T(args[0]) if args else ""}]
                if m == "paralelo" and len(args) == 3 and args[2]["k"] == "closure" and len(args[2]["params"]) == 1:
                    var = args[2]["params"][0]
                    self.loop_vars.append(var)
                    try:
                        body = self.block(args[2]["body"])
                    finally:
                        self.loop_vars.pop()
                    return [{"id": self.sid(), "type": "foreach", "items_expr": self.items(args[0]), "item_variable": var,
                             "parallel": max(1, min(20, int(self.E(args[1])) if args[1]["k"] == "const" else 10)),
                             "steps": body or self._empty()}]
        raise Untranslatable("instrução sem equivalente: " + (e.get("method") or k))

    def named(self, call: dict) -> tuple[dict[str, dict], list[dict]]:
        """Separa os argumentos com nome (credencial: …) dos posicionais."""
        named: dict[str, dict] = {}
        pos: list[dict] = []
        for a in call["args"]:
            # argumentos com nome (credencial: "x") chegam como mapa; um mapa literal começa por "["
            if a["k"] == "named" or (a["k"] == "map" and not self.source(a).lstrip().startswith("[")):
                for ent in a["entries"]:
                    if ent["key"]["k"] != "const":
                        raise Untranslatable("nome de opção dinâmico")
                    named[str(ent["key"]["value"])] = ent["value"]
            else:
                pos.append(a)
        return named, pos

    def const_str(self, e: dict, what: str) -> str:
        if e["k"] != "const" or not isinstance(e.get("value"), str):
            raise Untranslatable(f"{what} tem de ser texto fixo")
        return e["value"]

    def api_call(self, e: dict, save_as: str | None) -> list[dict] | None:  # noqa: C901
        obj, m = e["obj"]["name"], e["method"]
        named, pos = self.named(e)
        if obj == "http" and m in ("get", "post", "put", "patch", "delete"):
            if not pos:
                raise Untranslatable("http sem URL")
            step: dict[str, Any] = {"id": self.sid(), "type": "http_request", "method": m.upper(), "url": self.T(pos[0]),
                                    "expect_status": [200, 201, 202, 204], "retries": 2 if m == "get" else 0,
                                    "timeout_seconds": 60,
                                    "response": "json"}
            for key, val in named.items():
                if key == "credencial":
                    step["credential"] = self.const_str(val, "o nome da credencial")
                elif key in ("headers", "query"):
                    if val["k"] != "map":
                        raise Untranslatable(f"'{key}' tem de ser um mapa [nome: valor]")
                    step[key] = {str(self.const_str(ent["key"], "o nome")): self.T(ent["value"]) for ent in val["entries"]}
                elif key == "esperar":
                    items = val["items"] if val["k"] == "list" else [val]
                    step["expect_status"] = [int(self.const_str_num(x)) for x in items]
                elif key == "resposta":
                    step["response"] = "text" if self.const_str(val, "resposta") == "texto" else "json"
                    if step["response"] == "json":
                        self.report.add("aviso", f"linha {e['line']}", "resposta JSON: no fluxo, uma resposta que não seja JSON dá erro")
                elif key == "tentativas":
                    step["retries"] = int(self.const_str_num(val))
                elif key == "timeout":
                    step["timeout_seconds"] = int(self.const_str_num(val))
                else:
                    raise Untranslatable(f"opção http '{key}'")
            if len(pos) > 1:
                body = pos[1]
                text_fns = {"text", "date", "money", "decimal", "tojson", "regex", "regex_replace", "between", "after", "before"}
                if body["k"] in ("gstring",) or (body["k"] == "const" and isinstance(body.get("value"), str)) or \
                        (body["k"] == "call" and body.get("obj") is None and body["method"] in text_fns):
                    step["body_text"] = self.T(body)
                else:
                    if body["k"] == "var":
                        self.report.add("aviso", f"linha {e['line']}", f"o corpo '{body['name']}' passa a ser enviado como JSON; "
                                        f"se for texto, escreva text({body['name']}) no Groovy antes de converter")
                    step["body_json_expr"] = self.E(body)
            if save_as:
                step["save_as"] = save_as
            if "resposta" not in named:
                self.report.add("aviso", f"linha {e['line']}", "no Groovy, uma resposta que não seja JSON é devolvida como texto; "
                                "no fluxo dá erro (use resposta: 'texto' se for o caso)")
            return [step]
        if obj == "email" and m == "enviar" and not save_as:
            cred = named.get("credencial")
            if cred is None:
                raise Untranslatable("email sem credencial")

            def lst(v: dict | None) -> list[str]:
                if v is None:
                    return []
                return [self.T(x) for x in v["items"]] if v["k"] == "list" else [self.T(v)]

            step = {"id": self.sid(), "type": "email", "credential": self.const_str(cred, "o nome da credencial"),
                    "to": lst(named.get("para")), "subject": self.T(named.get("assunto") or {"k": "const", "value": ""}),
                    "body": self.T(named.get("corpo") or {"k": "const", "value": ""})}
            if named.get("cc"):
                step["cc"] = lst(named["cc"])
            if named.get("anexos"):
                step["attachments"] = lst(named["anexos"])
            extra = set(named) - {"credencial", "para", "cc", "assunto", "corpo", "anexos"}
            if extra:
                raise Untranslatable(f"opções de email {sorted(extra)}")
            return [step]
        if obj == "sql" and m in ("consultar", "executar"):
            if len(pos) < 2:
                raise Untranslatable("sql sem credencial ou consulta")
            cred = self.const_str(pos[0], "o nome da credencial")
            query = self.const_str(pos[1], "a consulta SQL")
            q = re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", r"%(\1)s", query.replace("%", "%%"))
            params = {}
            if len(pos) > 2:
                if pos[2]["k"] != "map":
                    raise Untranslatable("parâmetros SQL têm de ser um mapa [nome: valor]")
                params = {self.const_str(ent["key"], "o nome do parâmetro"): self.T(ent["value"]) for ent in pos[2]["entries"]}
            step = {"id": self.sid(), "type": "sql_query", "credential": cred, "query": q, "read_only": m == "consultar"}
            if params:
                step["params"] = params
            if save_as:
                step["save_as"] = save_as
            return [step]
        if obj == "ficheiro":
            if m in ("gravar", "acrescentar") and len(pos) == 2 and not save_as:
                step = {"id": self.sid(), "type": "text_write", "file": self.T(pos[0]), "content": self.T(pos[1])}
                if m == "acrescentar":
                    step["append"] = True
                return [step]
            if m == "ler" and len(pos) == 1 and save_as:
                self.report.add("aviso", f"linha {e['line']}", "ficheiro.ler: no fluxo, um ficheiro inexistente dá erro "
                                "(no Groovy devolvia null); use '?: \"\"' para o tornar opcional")
                return [{"id": self.sid(), "type": "text_read", "file": self.T(pos[0]), "save_as": save_as}]
            if m == "csv" and len(pos) == 2 and not save_as:
                rows = pos[1]
                cols = named.get("colunas")
                if rows["k"] == "call" and rows["method"] == "collect" and len(rows["args"]) == 1 \
                        and rows["args"][0]["k"] == "closure" and len(rows["args"][0]["params"]) == 1:
                    clo = rows["args"][0]
                    body = clo["body"]["body"] if clo["body"]["k"] == "block" else [clo["body"]]
                    if len(body) == 1 and body[0]["k"] == "expr" and body[0]["expr"]["k"] == "map":
                        rv = clo["params"][0]
                        self.loop_vars.append(rv)
                        try:
                            columns = [{"header": self.const_str(ent["key"], "o nome da coluna"),
                                        "value": self.T(ent["value"]).replace("{{ " + rv + ".", "{{ row.").replace("{{ " + rv + " ", "{{ row ")}
                                       for ent in body[0]["expr"]["entries"]]
                        finally:
                            self.loop_vars.pop()
                        src = rows["obj"]
                        return [{"id": self.sid(), "type": "csv_write", "file": self.T(pos[0]),
                                 "rows_expr": self.E(src) if src else "[]", "columns": columns,
                                 **({"delimiter": self.const_str(named["separador"], "o separador")} if named.get("separador") else {})}]
                if cols is None or cols["k"] != "list":
                    raise Untranslatable("ficheiro.csv sem 'colunas: [...]'")
                columns = [{"header": self.const_str(c, "o nome da coluna"),
                            "value": "{{ row[" + jstr(self.const_str(c, "o nome da coluna")) + "] }}"} for c in cols["items"]]
                return [{"id": self.sid(), "type": "csv_write", "file": self.T(pos[0]), "rows_expr": self.E(rows),
                         "columns": columns}]
        return None

    def const_str_num(self, e: dict) -> str:
        if e["k"] != "const":
            raise Untranslatable("valor tem de ser fixo")
        return str(e["value"])

    # ------------------------------------------------------------- expressões

    def T(self, e: dict) -> str:  # noqa: N802 - expressão → modelo de texto
        if e["k"] == "const" and isinstance(e.get("value"), str):
            return self.tpl_lit(e["value"])
        if e["k"] == "gstring":
            out = []
            for i, s in enumerate(e["strings"]):
                out.append(self.tpl_lit(s))
                if i < len(e["values"]):
                    out.append("{{ " + self._untext(e["values"][i]) + " }}")
            return "".join(out)
        return "{{ " + self._untext(e) + " }}"

    def _untext(self, e: dict) -> str:
        # text(x) dentro de um modelo é o comportamento normal do modelo
        if e["k"] == "call" and e.get("obj") is None and e["method"] == "text" and len(e["args"]) == 1:
            return self.E(e["args"][0])
        return self.E(e)

    def E(self, e: dict) -> str:  # noqa: N802,C901 - expressão Groovy → expressão Jinja
        k = e["k"]
        if k == "const":
            v = e.get("value")
            t = e.get("type")
            if v is None:
                return "none"
            if isinstance(v, bool):
                return "true" if v else "false"
            if t in ("Integer", "Long", "BigInteger", "BigDecimal", "Double", "Float"):
                return str(v)
            return jstr(str(v))
        if k == "var":
            name = e["name"]
            if name in self.catch_vars and name:
                return "last_error"
            if name in ("http", "email", "sql", "ficheiro"):
                raise Untranslatable(f"'{name}' só pode ser usado como chamada")
            return name
        if k == "prop":
            obj = e["obj"]
            if obj["k"] == "var" and obj["name"] in self.catch_vars and e["prop"] == "message":
                return "last_error"
            return f"{self.A(obj)}.{e['prop']}"
        if k == "index":
            return f"{self.A(e['obj'])}[{self.E(e['index'])}]"
        if k == "list":
            return "[" + ", ".join(self.E(x) for x in e["items"]) + "]"
        if k == "map":
            return "{" + ", ".join(f"{self.E(ent['key'])}: {self.E(ent['value'])}" for ent in e["entries"]) + "}"
        if k == "not":
            return f"not {self.A(e['expr'])}"
        if k == "neg":
            return f"-{self.A(e['expr'])}"
        if k == "ternary":
            return f"({self.E(e['then'])} if {self.E(e['cond'])} else {self.E(e['else'])})"
        if k == "elvis":
            return f"({self.E(e['left'])} or {self.E(e['right'])})"
        if k == "gstring":
            parts = []
            for i, s in enumerate(e["strings"]):
                if s:
                    parts.append(jstr(s))
                if i < len(e["values"]):
                    parts.append(f"({self._untext(e['values'][i])} | text)")
            return "(" + " ~ ".join(parts or ["''"]) + ")"
        if k == "range":
            a, b = self.E(e["from"]), self.E(e["to"])
            return f"range({a}, ({b}) + 1)" if e.get("inclusive") else f"range({a}, {b})"
        if k == "cast":
            typ = e["type"].split(".")[-1]
            conv = {"int": "int", "Integer": "int", "long": "int", "Long": "int", "double": "float", "Double": "float",
                    "float": "float", "BigDecimal": "num", "String": "text", "List": "as_list"}.get(typ)
            if not conv:
                raise Untranslatable(f"conversão 'as {typ}'")
            return f"({self.E(e['expr'])} | {conv})"
        if k == "bin":
            op = e["op"]
            if op == "in":
                return f"({self.E(e['left'])} in {self.E(e['right'])})"
            if op not in BIN_BACK:
                raise Untranslatable(f"operador '{op}'")
            return f"({self.E(e['left'])} {BIN_BACK[op]} {self.E(e['right'])})"
        if k == "call":
            return self.call(e)
        raise Untranslatable(f"expressão {k if k != 'unsupported' else e.get('what')}")

    def A(self, e: dict) -> str:  # noqa: N802 - átomo
        code = self.E(e)
        if re.fullmatch(r"[\w.]+(\[[^\]]*\])?|'[^']*'|\(.*\)", code):
            return code
        return f"({code})"

    def call(self, e: dict) -> str:  # noqa: C901
        m = e["method"]
        args = [a for a in e["args"] if a["k"] != "named"]
        if any(a["k"] == "named" for a in e["args"]):
            raise Untranslatable(f"argumentos com nome em '{m}'")
        obj = e.get("obj")
        if obj is None:
            if m in HELPER_FILTERS and args:
                rest = ", ".join(self.E(a) for a in args[1:])
                return f"({self.E(args[0])} | {m}({rest}))" if rest else f"({self.E(args[0])} | {m})"
            if m == "length" and len(args) == 1:
                return f"({self.E(args[0])} | length)"
            if m in HELPER_GLOBALS:
                return f"{m}({', '.join(self.E(a) for a in args)})"
            if m == "contem" and len(args) == 2:
                return f"({self.E(args[1])} in {self.E(args[0])})"
            if m == "extrair" and len(args) == 2 and args[1]["k"] == "const":
                raise Untranslatable("extrair() dentro de uma expressão (use uma atribuição)")
            raise Untranslatable(f"função '{m}'")
        o = self.A(obj)
        if any(a["k"] == "closure" for a in args):
            clo = args[-1]
            if len(args) == 1 and clo["k"] == "closure":
                single = self._closure_expr(clo)
                if single is not None:
                    p, body = single
                    # it.campo / it['campo'] → map(attribute) / selectattr
                    fld = rf"{p}(?:\.(\w+)|\['(\w+)'\])"
                    mm = re.fullmatch(fld, body)
                    if m == "collect" and mm:
                        return f"({o} | map(attribute={jstr(mm.group(1) or mm.group(2))}) | list)"
                    mm = re.fullmatch(rf"\({fld} == (.+)\)", body)
                    if m == "findAll" and mm:
                        return f"({o} | selectattr({jstr(mm.group(1) or mm.group(2))}, 'equalto', {mm.group(3)}) | list)"
                    mm = re.fullmatch(fld, body)
                    if m == "findAll" and mm:
                        return f"({o} | selectattr({jstr(mm.group(1) or mm.group(2))}) | list)"
            raise Untranslatable(f"closure em '.{m} {{ … }}'")
        a = [self.E(x) for x in args]
        if m in STR_METHODS_BACK:
            return f"({o} | text).{STR_METHODS_BACK[m]}({', '.join(a)})"
        if m == "size" and not a:
            return f"({o} | length)"
        if m == "join":
            return f"({o} | join({', '.join(a)}))"
        if m == "contains" and len(a) == 1:
            return f"({a[0]} in {o})"
        if m == "isEmpty" and not a:
            return f"(({o} | length) == 0)"
        if m == "get" and len(a) == 1:
            return f"{o}[{a[0]}]"
        if m == "toString" and not a:
            return f"({o} | text)"
        if m in ("toInteger", "toLong") and not a:
            return f"({o} | int)"
        if m in ("toBigDecimal", "toDouble") and not a:
            return f"({o} | num)"
        raise Untranslatable(f"método '.{m}()'")

    def _closure_expr(self, clo: dict) -> tuple[str, str] | None:
        params = clo["params"] or ["it"]
        body = clo["body"]["body"] if clo["body"]["k"] == "block" else [clo["body"]]
        if len(params) != 1 or len(body) != 1 or body[0]["k"] != "expr":
            return None
        try:
            return params[0], self.E(body[0]["expr"])
        except Untranslatable:
            return None


def groovy_to_flow(definition: dict[str, Any], ast: dict[str, Any], force: bool = False) -> tuple[dict[str, Any], Report]:
    conv = GroovyToFlow(definition.get("code", ""), ast, force)
    steps, report = conv.convert()
    _renumber(steps)
    new_def = {k: v for k, v in definition.items() if k not in ("steps", "code", "language")}
    new_def["steps"] = steps
    return new_def, report


def _renumber(steps: list[dict], counter: list[int] | None = None) -> None:
    counter = counter if counter is not None else [0]
    for st in steps:
        counter[0] += 1
        st["id"] = f"s{counter[0]}"
        for k in ("steps", "then", "otherwise", "on_error"):
            _renumber(st.get(k) or [], counter)
