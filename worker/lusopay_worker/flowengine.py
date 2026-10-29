"""Motor de fluxos nativos do Bot Manager.

Executado como subprocesso pelo adaptador `flow`:
    python -m lusopay_worker.flowengine   (recebe o trabalho em JSON pelo stdin)

Escreve linhas de log no stdout e termina com uma linha
    @@RESULT {"status": "SUCCEEDED" | "FAILED", ...}

Os modelos e expressões são Jinja2 num ambiente *sandbox*. As credenciais
nunca entram no contexto do fluxo: são usadas apenas pelos passos que as
referem, e os seus valores são redigidos em qualquer log.
"""
from __future__ import annotations

import csv
import json
import random
import re
import smtplib
import ssl
import sys
import threading
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from jinja2 import StrictUndefined
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from .redaction import redact_text

RESULT_PREFIX = "@@RESULT "
EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")
CSV_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")
MAX_RESPONSE_BYTES = 50 * 1024 * 1024


class FlowError(Exception):
    def __init__(self, step_id: str, message: str):
        super().__init__(message)
        self.step_id = step_id


class StopFlow(Exception):
    pass


class BreakLoop(Exception):
    pass


class ContinueLoop(Exception):
    pass


def _json_default(o: Any) -> Any:
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, bytes):
        return o.decode("utf-8", errors="replace")
    return str(o)


def _to_date(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return datetime.fromisoformat(str(v))


def _finalize(v: Any) -> Any:
    """Objetos aparecem em texto como JSON (como no taskt), nunca como repr do Python."""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=_json_default)
    return v


def to_text(v: Any) -> str:
    return str(_finalize(v))


def parse_json(v: Any) -> Any:
    if isinstance(v, (bytes, str)):
        t = v.decode() if isinstance(v, bytes) else v
        return json.loads(t) if t.strip() else None
    return v


def as_list(v: Any) -> list:
    """Lista a partir de uma lista, de JSON de uma lista ou de um valor único (o 'Parse JSON Model' do OpenBots
    devolve listas; os passos convertidos usam o valor tal como vier)."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, (bytes, str)):
        t = v.decode() if isinstance(v, bytes) else v
        if not t.strip():
            return []
        try:
            parsed = json.loads(t)
        except ValueError:
            return [t]
        return parsed if isinstance(parsed, list) else [parsed]
    if isinstance(v, tuple):
        return list(v)
    return [v]


def to_num(v: Any) -> Any:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float, Decimal)):
        n = float(v)
    else:
        t = str(v).strip().replace(" ", "")
        if t == "":
            return 0
        try:
            n = float(t)
        except ValueError:
            # formato português: 1.234,56
            n = float(t.replace(".", "").replace(",", "."))
    return int(n) if n.is_integer() else n


def _nth_index(text: str, sub: str, skip: int) -> int:
    idx = -1
    for _ in range(int(skip) + 1):
        idx = text.find(sub, idx + 1)
        if idx < 0:
            return -1
    return idx


def text_between(v: Any, lead: str, trail: str, skip: int = 0) -> str:
    t = to_text(v)
    i = _nth_index(t, lead, skip)
    if i < 0:
        return ""
    start = i + len(lead)
    j = t.find(trail, start) if trail else len(t)
    return t[start:] if j < 0 else t[start:j]


def text_after(v: Any, lead: str, skip: int = 0) -> str:
    t = to_text(v)
    i = _nth_index(t, lead, skip)
    return "" if i < 0 else t[i + len(lead):]


def text_before(v: Any, trail: str, skip: int = 0) -> str:
    t = to_text(v)
    i = _nth_index(t, trail, skip)
    return t if i < 0 else t[:i]


def regex_find(v: Any, pattern: str, group: int = 0) -> str:
    m = re.search(pattern, to_text(v))
    if not m:
        return ""
    return m.group(int(group or 0)) or ""


def regex_replace(v: Any, pattern: str, replacement: Any = "") -> str:
    """Substituição com expressão regular; aceita referências a grupos no estilo .NET ($1, ${nome})."""
    repl = re.sub(r"\$\{(\w+)\}|\$(\d+)", lambda m: f"\\g<{m.group(1) or m.group(2)}>",
                  to_text(replacement).replace("\\", "\\\\"))
    return re.sub(pattern, repl, to_text(v))


def regex_split(v: Any, pattern: str) -> list[str]:
    return re.split(pattern, to_text(v))


def jsonpath(v: Any, path: str) -> Any:
    """JSONPath simples: $.a.b, $..chave, a[0].b, items[*].id. Filtros [?(...)] não são suportados."""
    data = parse_json(v)
    path = path.strip()
    if "[?" in path:
        raise ValueError(f"JSONPath com filtro não suportado: {path}")
    if path.startswith("$.."):
        rest = path[3:]
        key, _, tail = rest.partition(".")
        found = find_key(data, key)
        return extract_path(found, tail) if tail else found
    return extract_path(data, path)


def split_text(v: Any, sep: str) -> list[str]:
    t = to_text(v).replace("\r\n", "\n")
    return t.split(sep.replace("\r\n", "\n"))


def add_time(v: Any, unit: str, n: Any) -> datetime:
    d = _to_date(v)
    n = to_num(n)
    unit = unit.lower()
    if unit.startswith("second"):
        return d + timedelta(seconds=n)
    if unit.startswith("minute"):
        return d + timedelta(minutes=n)
    if unit.startswith("hour"):
        return d + timedelta(hours=n)
    if unit.startswith("day"):
        return d + timedelta(days=n)
    if unit.startswith("month") or unit.startswith("year"):
        months = int(n) * (12 if unit.startswith("year") else 1)
        m = d.month - 1 + months
        y, m = d.year + m // 12, m % 12 + 1
        import calendar

        return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))
    raise ValueError(f"unidade de tempo desconhecida: {unit}")


def taskt_compare(a: Any, op: str, b: Any, case_sensitive: bool = False, mode: str = "text") -> bool:
    """Comparações com a semântica do 'Begin If' do taskt/OpenBots."""
    op = op.strip().lower()
    if mode == "date":
        x, y = _to_date(to_text(a).strip()), _to_date(to_text(b).strip())
    else:
        x, y = to_text(a), to_text(b)
        if op in ("contains", "does not contain", "is equal to", "is not equal to") and not case_sensitive:
            x, y = x.lower(), y.lower()
        if op in ("is greater than", "is greater than or equal to", "is less than", "is less than or equal to"):
            x, y = to_num(x), to_num(y)
        elif op in ("is equal to", "is not equal to") and is_numeric(x) and is_numeric(y):
            x, y = to_num(x), to_num(y)
    return {
        "is equal to": lambda: x == y,
        "is not equal to": lambda: x != y,
        "is greater than": lambda: x > y,
        "is greater than or equal to": lambda: x >= y,
        "is less than": lambda: x < y,
        "is less than or equal to": lambda: x <= y,
        "contains": lambda: y in x,
        "does not contain": lambda: y not in x,
    }[op]()


def is_numeric(v: Any) -> bool:
    try:
        float(to_text(v).strip().replace(",", "."))
        return to_text(v).strip() != ""
    except ValueError:
        return False


def named_to_pyformat(query: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Converte parâmetros ':nome' (estilo JDBC/Groovy) para '%(nome)s' (pymssql), ignorando texto entre plicas."""
    if not params:
        return query, {}
    out, i, n = [], 0, len(query)
    while i < n:
        ch = query[i]
        if ch == "'":
            j = i + 1
            while j < n:
                if query[j] == "'" and (j + 1 >= n or query[j + 1] != "'"):
                    break
                j += 2 if query[j] == "'" else 1
            out.append(query[i:j + 1].replace("%", "%%"))
            i = j + 1
            continue
        if ch == ":" and i + 1 < n and (query[i + 1].isalpha() or query[i + 1] == "_") and (i == 0 or query[i - 1] != ":"):
            j = i + 1
            while j < n and (query[j].isalnum() or query[j] == "_"):
                j += 1
            name = query[i + 1:j]
            if name not in params:
                raise ValueError(f"parâmetro SQL sem valor: :{name}")
            out.append(f"%({name})s")
            i = j
            continue
        out.append("%%" if ch == "%" else ch)
        i += 1
    return "".join(out), {k: (to_text(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}


def make_env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True,
                               finalize=_finalize)
    env.filters["date"] = lambda v, fmt="%Y-%m-%d": _to_date(v).strftime(fmt)
    env.filters["add_days"] = lambda v, n: _to_date(v) + timedelta(days=int(n))
    env.filters["tojson"] = lambda v: json.dumps(v, ensure_ascii=False, default=_json_default)
    env.filters["fromjson"] = lambda v: json.loads(v)
    env.filters["money"] = lambda v: f"{float(v):.2f}".replace(".", ",")
    env.filters["decimal"] = lambda v, n=2: f"{float(v):.{int(n)}f}".replace(".", ",")
    env.filters["sample"] = lambda v, n: random.sample(list(v), min(int(n), len(v)))
    env.filters["find"] = find_key
    env.filters["text"] = to_text
    env.filters["parsejson"] = parse_json
    env.filters["as_list"] = as_list
    env.filters["num"] = to_num
    env.filters["between"] = text_between
    env.filters["after"] = text_after
    env.filters["before"] = text_before
    env.filters["regex"] = regex_find
    env.filters["regex_replace"] = regex_replace
    env.filters["regex_split"] = regex_split
    env.filters["jsonpath"] = jsonpath
    env.filters["split_text"] = split_text
    env.filters["add_time"] = add_time
    env.filters["todate"] = _to_date
    env.filters["row_values"] = lambda v: list(v.values()) if isinstance(v, dict) else list(v)
    env.tests["contains"] = lambda v, sub: sub in v
    env.globals["taskt_compare"] = taskt_compare
    env.globals["is_numeric"] = is_numeric
    env.globals["file_exists"] = lambda name: False  # substituído por instância (ficheiros desta execução)
    env.globals["now"] = lambda: datetime.now()
    env.globals["today"] = lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    env.globals["first_day_of_month"] = lambda offset=0: _month_start(offset)
    return env


def _month_start(offset: int) -> datetime:
    d = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    m = d.month - 1 + int(offset)
    return d.replace(year=d.year + m // 12, month=m % 12 + 1)


def find_key(data: Any, key: str) -> Any:
    """Procura recursiva do primeiro valor de `key` (equivalente a $..key)."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        values = data.values()
    elif isinstance(data, list):
        values = data
    else:
        return None
    for v in values:
        found = find_key(v, key)
        if found is not None:
            return found
    return None


def extract_path(data: Any, path: str) -> Any:
    """Caminho simples: a.b[0].c, items[*].id, $.a (o '$.' inicial é opcional)."""
    path = path[2:] if path.startswith("$.") else path.lstrip("$")
    tokens = re.findall(r"[^.\[\]]+|\[\*\]|\[\d+\]", path)

    def walk(cur: Any, toks: list[str]) -> Any:
        for i, t in enumerate(toks):
            if t == "[*]":
                if not isinstance(cur, list):
                    return None
                return [walk(x, toks[i + 1:]) for x in cur]
            if t.startswith("["):
                idx = int(t[1:-1])
                cur = cur[idx] if isinstance(cur, list) and idx < len(cur) else None
            else:
                cur = cur.get(t) if isinstance(cur, dict) else None
            if cur is None:
                return None
        return cur

    return walk(data, tokens)


class Engine:
    def __init__(
        self,
        job: dict[str, Any],
        out_dir: Path,
        emit: Callable[[str], None] = print,
        http_client: httpx.Client | None = None,
        smtp_factory: Callable[..., Any] | None = None,
        sql_connect: Callable[..., Any] | None = None,
    ):
        self.job = job
        self.flow = job["flow"]["definition"]
        self.credentials: dict[str, dict[str, Any]] = job.get("credentials") or {}
        self.allowed_hosts = set(job.get("allowed_hosts") or [])
        self.out_dir = out_dir
        self._emit = emit
        self.env = make_env()
        self.env.globals["file_exists"] = lambda name: (self.out_dir / str(name)).is_file()
        self.http = http_client or httpx.Client(follow_redirects=False, timeout=30,
                                                limits=httpx.Limits(max_connections=40))
        self.smtp_factory = smtp_factory
        self.sql_connect = sql_connect
        self.lock = threading.Lock()
        self.files: list[str] = []
        self.counters = {"steps": 0, "http_requests": 0, "emails": 0, "sql_queries": 0}
        self.secrets = [str(v) for c in self.credentials.values() for k, v in c.items()
                        if k in ("password", "token", "value") and v]
        self.dry_run = bool(job.get("dry_run"))
        self._expr_cache: dict[str, Any] = {}
        self._tpl_cache: dict[str, Any] = {}

    # ------------------------------------------------------------ utilitários

    def log(self, msg: str, level: str = "INFO") -> None:
        line = redact_text(f"{level} {msg}" if level != "INFO" else msg, self.secrets)
        with self.lock:
            self._emit(line)

    def render(self, tpl: str, ctx: dict[str, Any]) -> str:
        t = self._tpl_cache.get(tpl)
        if t is None:
            t = self._tpl_cache[tpl] = self.env.from_string(tpl)
        return t.render(**ctx)

    def evaluate(self, expr: str, ctx: dict[str, Any]) -> Any:
        e = self._expr_cache.get(expr)
        if e is None:
            e = self._expr_cache[expr] = self.env.compile_expression(expr, undefined_to_none=False)
        return e(**ctx)

    def _cred(self, name: str, kinds: set[str]) -> dict[str, Any]:
        c = self.credentials.get(name)
        if c is None or c.get("kind") not in kinds:
            raise ValueError(f"credencial '{name}' indisponível para este passo")
        return c

    # ------------------------------------------------------------ execução

    def run(self) -> dict[str, Any]:
        import copy

        # cópia: as listas iniciais não podem ser alteradas na definição (que pode ser reutilizada)
        ctx: dict[str, Any] = copy.deepcopy(self.flow.get("variables", {}))
        ctx["params"] = self.job.get("parameters") or {}
        ctx["run_id"] = self.job.get("run_id")
        ctx["files"] = self.files
        started = time.monotonic()
        result: dict[str, Any] = {"status": "SUCCEEDED"}
        try:
            if self.flow.get("language") == "groovy":
                self.run_groovy(ctx)
            else:
                self.run_steps(self.flow["steps"], ctx)
        except StopFlow as exc:
            result["stopped"] = str(exc)
        except FlowError as exc:
            self.log(f"[{exc.step_id}] falhou: {exc}", "ERROR")
            result = {"status": "FAILED", "failed_step": exc.step_id, "error": redact_text(str(exc), self.secrets)[:2000]}
        finally:
            self.http.close()
        result.update({"files": list(self.files), "counters": self.counters,
                       "duration_seconds": round(time.monotonic() - started, 3)})
        return result

    # ------------------------------------------------------------ robôs Groovy

    def run_groovy(self, ctx: dict[str, Any]) -> None:
        """Executa o código Groovy numa JVM isolada (BmHost.groovy). As operações com efeitos (http, email, sql,
        ficheiros) chegam pela ponte e são executadas aqui, com as mesmas regras e credenciais dos passos."""
        import subprocess

        rt = self.job.get("groovy") or {}
        if not rt.get("argv"):
            raise FlowError("groovy", "o worker não tem o Groovy instalado")
        variables = {k: v for k, v in ctx.items() if k not in ("files", "params", "run_id")}
        init = {"code": self.flow.get("code", ""), "variables": variables, "params": ctx["params"],
                "run_id": ctx["run_id"], "out_dir": str(self.out_dir)}
        proc = subprocess.Popen(rt["argv"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(self.out_dir), env=rt.get("env"), bufsize=0)
        assert proc.stdin and proc.stdout and proc.stderr
        write_lock = threading.Lock()

        def send(obj: dict[str, Any]) -> None:
            data = (json.dumps(obj, default=_json_default, ensure_ascii=False) + "\n").encode("utf-8")
            with write_lock:
                try:
                    proc.stdin.write(data)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass

        stderr_lines: list[str] = []

        def pump_stderr() -> None:
            from .groovy import is_jvm_noise

            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not is_jvm_noise(line) and len(stderr_lines) < 200:
                    stderr_lines.append(line)

        err_thread = threading.Thread(target=pump_stderr, daemon=True)
        err_thread.start()
        send(init)
        pool = ThreadPoolExecutor(max_workers=20, thread_name_prefix="groovy-op")
        end: dict[str, Any] | None = None
        n_calls = 0

        def handle(req: dict[str, Any]) -> None:
            try:
                value = self._groovy_op(f"g{req['id']}", req["op"], req.get("args") or {})
                send({"id": req["id"], "ok": True, "value": value})
            except Exception as exc:  # noqa: BLE001 - o erro volta para o código Groovy (pode ser tratado com try)
                send({"id": req["id"], "ok": False, "error": redact_text(f"{type(exc).__name__}: {exc}", self.secrets)})

        try:
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("@@CALL "):
                    n_calls += 1
                    with self.lock:
                        self.counters["steps"] += 1
                    pool.submit(handle, json.loads(line[7:]))
                elif line.startswith("@@LOG "):
                    m = json.loads(line[6:])
                    self.log(str(m.get("msg", "")), m.get("level", "INFO"))
                elif line.startswith("@@END "):
                    end = json.loads(line[6:])
                    break
                elif line.strip():
                    self.log(line)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
            err_thread.join(timeout=5)
        if end is None:
            detail = "\n".join(stderr_lines[-20:]) or f"código {proc.returncode}"
            raise FlowError("groovy", f"o processo Java terminou sem resultado: {detail}")
        status = end.get("status")
        if status == "ok":
            return
        if status == "stop":
            self.log(f"[groovy] fim antecipado: {end.get('message', '')}")
            raise StopFlow(end.get("message", ""))
        if status == "error":  # compilação ou código recusado
            msgs = "; ".join(f"linha {e.get('line')}: {e.get('message')}" for e in end.get("errors", []))
            raise FlowError("compilação", msgs or "erro de compilação")
        where = f"linha {end['line']}" if end.get("line") else "groovy"
        raise FlowError(where, str(end.get("message", "erro")))

    def _groovy_op(self, sid: str, op: str, a: dict[str, Any]) -> Any:
        if op == "http":
            body = a.get("body") or {}
            headers = {str(k): to_text(v) for k, v in (a.get("headers") or {}).items()}
            content = None
            if "json" in body:
                content = json.dumps(body["json"], default=_json_default, ensure_ascii=False)
                headers.setdefault("Content-Type", "application/json")
            elif "text" in body:
                content = body["text"]
            expect = a.get("esperar") or [200, 201, 202, 204]
            if not isinstance(expect, list):
                expect = [expect]
            status, value = self.http_call(
                sid, a.get("method", "GET"), str(a["url"]), headers,
                {str(k): to_text(v) for k, v in (a.get("query") or {}).items()}, content, a.get("credencial"),
                float(a.get("timeout") or 60), int(a.get("tentativas") or 2),
                [int(x) for x in expect], {"texto": "text", "json": "json"}.get(a.get("resposta"), "auto"))
            return value
        if op == "email":
            def lst(v):
                return [to_text(x) for x in v] if isinstance(v, list) else ([to_text(v)] if v else [])

            if not a.get("credencial"):
                raise ValueError("email.enviar: indique a credencial (credencial: \"smtp-...\")")
            self.send_email(sid, a["credencial"], lst(a.get("para")), lst(a.get("cc")), to_text(a.get("assunto")),
                            to_text(a.get("corpo")), lst(a.get("anexos")))
            return None
        if op == "sql":
            query, params = named_to_pyformat(str(a["query"]), a.get("params") or {})
            return self.sql_run(sid, str(a["credencial"]), query, params, not a.get("escrita"))
        if op == "file_read":
            path = self._out_path(str(a["nome"]))
            return path.read_text(encoding="utf-8-sig") if path.is_file() else None
        if op == "file_exists":
            return self._out_path(str(a["nome"])).is_file()
        if op == "file_write":
            self.write_text(sid, str(a["nome"]), to_text(a.get("texto")), bool(a.get("acrescentar")))
            return None
        if op == "file_csv":
            linhas = a.get("linhas") or []
            colunas = a.get("colunas")
            if not colunas:
                colunas = list(linhas[0].keys()) if linhas and isinstance(linhas[0], dict) else []
            rows = []
            for r in linhas:
                if isinstance(r, dict):
                    rows.append([to_text(r.get(c)) for c in colunas])
                else:
                    rows.append([to_text(x) for x in (r if isinstance(r, list) else [r])])
            self.write_csv(sid, str(a["nome"]), [to_text(c) for c in colunas], rows, str(a.get("separador") or ";"))
            return None
        raise ValueError(f"operação desconhecida: {op}")

    def run_steps(self, steps: list[dict[str, Any]], ctx: dict[str, Any]) -> None:
        for step in steps:
            self.run_step(step, ctx)

    def run_step(self, step: dict[str, Any], ctx: dict[str, Any]) -> None:
        sid = step["id"]
        with self.lock:
            self.counters["steps"] += 1
        handler = getattr(self, f"step_{step['type']}", None)
        if handler is None:
            raise FlowError(sid, f"tipo de passo desconhecido: {step['type']}")
        try:
            handler(step, ctx)
        except (StopFlow, FlowError, BreakLoop, ContinueLoop):
            raise
        except Exception as exc:  # noqa: BLE001 - convertido em falha do passo
            msg = f"{type(exc).__name__}: {exc}"
            if step.get("continue_on_error"):
                self.log(f"[{sid}] erro ignorado (continue_on_error): {msg}", "WARNING")
                ctx["last_error"] = msg
                return
            raise FlowError(sid, msg) from exc

    # ------------------------------------------------------------ passos

    def step_set(self, s, ctx):
        ctx[s["variable"]] = self.render(s["value"], ctx) if s.get("value") is not None else self.evaluate(s["expr"], ctx)

    def step_extract(self, s, ctx):
        ctx[s["save_as"]] = extract_path(self.evaluate(s["source_expr"], ctx), s["path"])

    def step_append(self, s, ctx):
        value = self.evaluate(s["expr"], ctx)
        with self.lock:
            lst = ctx.setdefault(s["variable"], [])
            if not isinstance(lst, list):
                raise ValueError(f"'{s['variable']}' não é uma lista")
            lst.append(value)

    def step_log(self, s, ctx):
        self.log(f"[{s['id']}] {self.render(s['message'], ctx)}", s.get("level", "INFO"))

    def step_fail(self, s, ctx):
        raise FlowError(s["id"], self.render(s["message"], ctx))

    def step_stop(self, s, ctx):
        msg = self.render(s.get("message", ""), ctx)
        self.log(f"[{s['id']}] fim antecipado: {msg}")
        raise StopFlow(msg)

    def step_break(self, s, ctx):
        raise BreakLoop()

    def step_continue(self, s, ctx):
        raise ContinueLoop()

    def step_try(self, s, ctx):
        try:
            self.run_steps(s.get("steps", []), ctx)
        except FlowError as exc:
            ctx["last_error"] = str(exc)
            self.log(f"[{s['id']}] erro tratado: {exc}", "WARNING")
            self.run_steps(s.get("on_error", []), ctx)

    def step_text_read(self, s, ctx):
        name = self.render(s["file"], ctx)
        path = self._out_path(name)
        if not path.is_file():
            if s.get("missing_ok"):
                ctx[s["save_as"]] = ""
                return
            raise ValueError(f"ficheiro {name} não existe nesta execução")
        ctx[s["save_as"]] = path.read_text(encoding="utf-8-sig")

    def step_if(self, s, ctx):
        branch = s.get("then", []) if self.evaluate(s["condition"], ctx) else s.get("otherwise", [])
        self.run_steps(branch, ctx)

    def step_foreach(self, s, ctx):
        items = self.evaluate(s["items_expr"], ctx)
        if items is None:
            items = []
        if isinstance(items, range):
            items = list(items)
        if not isinstance(items, (list, tuple)):
            raise ValueError("items_expr não devolveu uma lista")
        var, par = s.get("item_variable", "item"), int(s.get("parallel", 1))
        self.log(f"[{s['id']}] ciclo sobre {len(items)} elemento(s){f' em paralelo ({par})' if par > 1 else ''}")

        def one(i: int, item: Any) -> None:
            local = dict(ctx)  # variáveis definidas dentro da iteração são locais
            local[var], local["loop_index"] = item, i
            try:
                self.run_steps(s["steps"], local)
            except ContinueLoop:
                pass
            finally:
                # variáveis que passam para as iterações seguintes e para depois do ciclo (semântica do taskt)
                for name in s.get("carry") or []:
                    if name in local:
                        ctx[name] = local[name]

        if par <= 1:
            for i, item in enumerate(items):
                try:
                    one(i, item)
                except BreakLoop:
                    break
            return
        with ThreadPoolExecutor(max_workers=par) as pool:
            futures = [pool.submit(one, i, it) for i, it in enumerate(items)]
            done, pending = wait(futures, return_when=FIRST_EXCEPTION)
            for f in pending:
                f.cancel()
            for f in done:
                exc = f.exception()
                if exc:
                    raise exc

    def step_http_request(self, s, ctx):
        url = self.render(s["url"], ctx)
        headers = {k: self.render(v, ctx) for k, v in (s.get("headers") or {}).items()}
        params = {k: self.render(v, ctx) for k, v in (s.get("query") or {}).items()}
        content: str | None = None
        if s.get("body_json_expr"):
            content = json.dumps(self.evaluate(s["body_json_expr"], ctx), default=_json_default)
            headers.setdefault("Content-Type", "application/json")
        elif s.get("body_text") is not None:
            content = self.render(s["body_text"], ctx)
        status, body = self.http_call(s["id"], s.get("method", "GET"), url, headers, params, content,
                                      s.get("credential"), s.get("timeout_seconds", 30), int(s.get("retries", 0)),
                                      s.get("expect_status") or [200], s.get("response", "json"))
        if s.get("save_as"):
            ctx[s["save_as"]] = body
            ctx[f"{s['save_as']}_status"] = status

    def http_call(self, sid: str, method: str, url: str, headers: dict[str, str], params: dict[str, str],
                  content: str | bytes | None, credential: str | None, timeout: float, retries: int,
                  expect: list[int], response: str) -> tuple[int, Any]:
        """Pedido HTTP com as regras dos fluxos: só https, hosts autorizados, credencial do cofre, repetição só em
        GET/HEAD. Usado pelos passos e pelos robôs Groovy."""
        method = method.upper()
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise ValueError("só são permitidos pedidos https")
        if self.allowed_hosts and parts.hostname not in self.allowed_hosts:
            raise ValueError(f"host não autorizado: {parts.hostname}")
        headers = dict(headers)
        auth = None
        if credential:
            c = self._cred(credential, {"http_basic", "http_bearer", "http_header"})
            if c["kind"] == "http_basic":
                auth = (c["username"], c["password"])
            elif c["kind"] == "http_bearer":
                headers["Authorization"] = f"Bearer {c['token']}"
            else:
                headers[c["header_name"]] = c["value"]
        if params:  # junta aos parâmetros que já estejam no URL (ex.: fields=a&fields=b), sem os substituir
            url = str(httpx.URL(url).copy_merge_params(params))
        if self.dry_run and method not in ("GET", "HEAD"):
            size = len(content or "")
            self.log(f"[{sid}] [SIMULAÇÃO] {method} {parts.scheme}://{parts.netloc}{parts.path} não enviado "
                     f"(corpo com {size} caracteres)", "WARNING")
            return 0, ({} if response == "json" else "")
        kwargs: dict[str, Any] = {"headers": headers, "auth": auth, "timeout": timeout}
        if content is not None:
            kwargs["content"] = content
        attempts = 1 + (retries if method in ("GET", "HEAD") else 0)
        for attempt in range(1, attempts + 1):
            t0 = time.monotonic()
            try:
                resp = self.http.request(method, url, **kwargs)
                if resp.status_code >= 500 and attempt < attempts:
                    raise httpx.HTTPStatusError("5xx", request=resp.request, response=resp)
                break
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt >= attempts:
                    raise
                self.log(f"[{sid}] {type(exc).__name__}; nova tentativa {attempt + 1}/{attempts}", "WARNING")
                time.sleep(min(2 ** attempt, 15))
        with self.lock:
            self.counters["http_requests"] += 1
        ms = int((time.monotonic() - t0) * 1000)
        self.log(f"[{sid}] {method} {parts.scheme}://{parts.netloc}{parts.path} → {resp.status_code} ({ms} ms)")
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise ValueError("resposta demasiado grande")
        if resp.status_code not in expect:
            raise ValueError(f"estado HTTP {resp.status_code} inesperado: {resp.text[:300]}")
        if response == "json" and resp.content:
            return resp.status_code, resp.json()
        if response == "auto" and resp.content:
            try:
                return resp.status_code, resp.json()
            except ValueError:
                return resp.status_code, resp.text
        return resp.status_code, resp.text

    def _out_path(self, name: str) -> Path:
        name = name.strip()
        if not name or "/" in name or "\\" in name or name.startswith(".") or ":" in name:
            raise ValueError(f"nome de ficheiro inválido: {name!r}")
        return self.out_dir / name

    def _register_file(self, name: str) -> None:
        with self.lock:
            if name not in self.files:
                self.files.append(name)

    def step_csv_write(self, s, ctx):
        name = self.render(s["file"], ctx)
        rows = self.evaluate(s["rows_expr"], ctx) or []
        cells = [[self.render(c["value"], {**ctx, "row": row}) for c in s["columns"]] for row in rows]
        self.write_csv(s["id"], name, [c["header"] for c in s["columns"]], cells, s.get("delimiter", ";"))

    def write_csv(self, sid: str, name: str, header: list[str], rows: list[list[str]], delimiter: str = ";") -> None:
        """CSV em UTF-8 com BOM (abre bem no Excel), com proteção contra injeção de fórmulas."""
        path = self._out_path(name)
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=delimiter)
            w.writerow(header)
            for row in rows:
                w.writerow(["'" + v if v.startswith(CSV_FORMULA_PREFIX) else v for v in row])
        self._register_file(name)
        self.log(f"[{sid}] ficheiro {name} criado ({len(rows)} linha(s))")

    def step_text_write(self, s, ctx):
        self.write_text(s["id"], self.render(s["file"], ctx), self.render(s["content"], ctx), bool(s.get("append")))

    def write_text(self, sid: str, name: str, content: str, append: bool = False) -> None:
        path = self._out_path(name)
        with self.lock:
            with path.open("a" if append else "w", encoding="utf-8") as fh:
                fh.write(content)
        self._register_file(name)
        if not append:
            self.log(f"[{sid}] ficheiro {name} criado")

    def step_email(self, s, ctx):
        def addresses(items):  # cada entrada pode ter vários endereços separados por , ou ;
            return [self.render(x, ctx) for x in items]

        self.send_email(s["id"], s["credential"], addresses(s["to"]), addresses(s.get("cc", [])),
                        self.render(s["subject"], ctx), self.render(s["body"], ctx),
                        [self.render(a, ctx) for a in s.get("attachments", [])])

    def send_email(self, sid: str, credential: str, to_items: list[str], cc_items: list[str], subject: str, body: str,
                   attachments: list[str]) -> None:
        c = self._cred(credential, {"smtp"})

        def split(items):
            return [a.strip() for x in items for a in re.split(r"[,;]", x) if a.strip()]

        to, cc = split(to_items), split(cc_items)
        if not to:
            raise ValueError("email sem destinatários")
        for addr in to + cc:
            if not EMAIL_RE.match(addr):
                raise ValueError(f"endereço de email inválido: {addr!r}")
        msg = EmailMessage()
        msg["From"] = c.get("from_address") or c["username"]
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg.set_content(body)
        for name in attachments:
            if name not in self.files:
                raise ValueError(f"anexo não foi produzido por este fluxo: {name}")
            msg.add_attachment(self._out_path(name).read_bytes(), maintype="application",
                               subtype="octet-stream", filename=name)
        if self.dry_run:
            self.log(f"[{sid}] [SIMULAÇÃO] email não enviado: para {', '.join(to + cc)} — {subject}", "WARNING")
            return
        host, port = c["host"], int(c.get("port") or 587)
        security = c.get("security", "starttls")
        factory = self.smtp_factory or (smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP)
        tls = ssl.create_default_context()
        kwargs = {"context": tls} if security == "ssl" and self.smtp_factory is None else {}
        with factory(host, port, timeout=60, **kwargs) as smtp:
            if security == "starttls":
                smtp.starttls(context=tls)
            if c.get("username"):
                smtp.login(c["username"], c["password"])
            smtp.send_message(msg)
        with self.lock:
            self.counters["emails"] += 1
        self.log(f"[{sid}] email enviado para {len(to) + len(cc)} destinatário(s), {len(attachments)} anexo(s)")

    def step_sql_query(self, s, ctx):
        params = {k: self.render(v, ctx) for k, v in (s.get("params") or {}).items()}
        rows = self.sql_run(s["id"], s["credential"], s["query"], params, s.get("read_only", True))
        if s.get("save_as"):
            ctx[s["save_as"]] = rows

    def sql_run(self, sid: str, credential: str, query: str, params: dict[str, Any], read_only: bool) -> list[dict]:
        c = self._cred(credential, {"mssql"})
        if self.sql_connect is None:
            import pymssql  # dependência opcional: só necessária para fluxos com SQL Server

            connect = pymssql.connect
        else:
            connect = self.sql_connect
        conn = connect(server=c["server"], port=str(c.get("port") or 1433), user=c["username"],
                       password=c["password"], database=c["database"], login_timeout=30, timeout=600)
        try:
            cur = conn.cursor(as_dict=True)
            cur.execute(query, params or None)
            rows = cur.fetchall() if cur.description else []
            if read_only or self.dry_run:
                conn.rollback()  # garante que nada é gravado
                if self.dry_run and not read_only:
                    self.log(f"[{sid}] [SIMULAÇÃO] escrita SQL desfeita (rollback)", "WARNING")
            else:
                conn.commit()
        finally:
            conn.close()
        with self.lock:
            self.counters["sql_queries"] += 1
        self.log(f"[{sid}] consulta SQL devolveu {len(rows)} linha(s)")
        return rows


def main() -> int:
    job = json.loads(sys.stdin.read())
    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = Engine(job, out_dir, emit=lambda line: print(line, flush=True))
    try:
        result = engine.run()
    except TemplateError as exc:  # erro fora de um passo (não deveria acontecer)
        result = {"status": "FAILED", "error": f"modelo: {exc}"}
    print(RESULT_PREFIX + json.dumps(result, default=_json_default), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
