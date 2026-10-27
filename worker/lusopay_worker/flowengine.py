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


def make_env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)
    env.filters["date"] = lambda v, fmt="%Y-%m-%d": _to_date(v).strftime(fmt)
    env.filters["add_days"] = lambda v, n: _to_date(v) + timedelta(days=int(n))
    env.filters["tojson"] = lambda v: json.dumps(v, ensure_ascii=False, default=_json_default)
    env.filters["fromjson"] = lambda v: json.loads(v)
    env.filters["money"] = lambda v: f"{float(v):.2f}".replace(".", ",")
    env.globals["now"] = lambda: datetime.now()
    env.globals["today"] = lambda: datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    env.globals["first_day_of_month"] = lambda offset=0: _month_start(offset)
    return env


def _month_start(offset: int) -> datetime:
    d = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    m = d.month - 1 + int(offset)
    return d.replace(year=d.year + m // 12, month=m % 12 + 1)


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
        self.http = http_client or httpx.Client(follow_redirects=False, timeout=30,
                                                limits=httpx.Limits(max_connections=40))
        self.smtp_factory = smtp_factory
        self.sql_connect = sql_connect
        self.lock = threading.Lock()
        self.files: list[str] = []
        self.counters = {"steps": 0, "http_requests": 0, "emails": 0, "sql_queries": 0}
        self.secrets = [str(v) for c in self.credentials.values() for k, v in c.items()
                        if k in ("password", "token", "value") and v]
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
        ctx: dict[str, Any] = {**self.flow.get("variables", {})}
        ctx["params"] = self.job.get("parameters") or {}
        ctx["run_id"] = self.job.get("run_id")
        ctx["files"] = self.files
        started = time.monotonic()
        result: dict[str, Any] = {"status": "SUCCEEDED"}
        try:
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
        except (StopFlow, FlowError):
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

    def step_if(self, s, ctx):
        branch = s.get("then", []) if self.evaluate(s["condition"], ctx) else s.get("otherwise", [])
        self.run_steps(branch, ctx)

    def step_foreach(self, s, ctx):
        items = self.evaluate(s["items_expr"], ctx)
        if items is None:
            items = []
        if not isinstance(items, (list, tuple)):
            raise ValueError("items_expr não devolveu uma lista")
        var, par = s.get("item_variable", "item"), int(s.get("parallel", 1))
        self.log(f"[{s['id']}] ciclo sobre {len(items)} elemento(s){f' em paralelo ({par})' if par > 1 else ''}")

        def one(i: int, item: Any) -> None:
            local = dict(ctx)  # variáveis definidas dentro da iteração são locais
            local[var], local["loop_index"] = item, i
            self.run_steps(s["steps"], local)

        if par <= 1:
            for i, item in enumerate(items):
                one(i, item)
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
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise ValueError("só são permitidos pedidos https")
        if self.allowed_hosts and parts.hostname not in self.allowed_hosts:
            raise ValueError(f"host não autorizado: {parts.hostname}")
        headers = {k: self.render(v, ctx) for k, v in (s.get("headers") or {}).items()}
        params = {k: self.render(v, ctx) for k, v in (s.get("query") or {}).items()}
        auth = None
        if s.get("credential"):
            c = self._cred(s["credential"], {"http_basic", "http_bearer", "http_header"})
            if c["kind"] == "http_basic":
                auth = (c["username"], c["password"])
            elif c["kind"] == "http_bearer":
                headers["Authorization"] = f"Bearer {c['token']}"
            else:
                headers[c["header_name"]] = c["value"]
        kwargs: dict[str, Any] = {"headers": headers, "params": params or None, "auth": auth,
                                  "timeout": s.get("timeout_seconds", 30)}
        if s.get("body_json_expr"):
            kwargs["content"] = json.dumps(self.evaluate(s["body_json_expr"], ctx), default=_json_default)
            headers.setdefault("Content-Type", "application/json")
        elif s.get("body_text") is not None:
            kwargs["content"] = self.render(s["body_text"], ctx)
        method = s.get("method", "GET")
        attempts = 1 + (int(s.get("retries", 0)) if method in ("GET", "HEAD") else 0)
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
                self.log(f"[{s['id']}] {type(exc).__name__}; nova tentativa {attempt + 1}/{attempts}", "WARNING")
                time.sleep(min(2 ** attempt, 15))
        with self.lock:
            self.counters["http_requests"] += 1
        ms = int((time.monotonic() - t0) * 1000)
        self.log(f"[{s['id']}] {method} {parts.scheme}://{parts.netloc}{parts.path} → {resp.status_code} ({ms} ms)")
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise ValueError("resposta demasiado grande")
        if resp.status_code not in (s.get("expect_status") or [200]):
            raise ValueError(f"estado HTTP {resp.status_code} inesperado: {resp.text[:300]}")
        if s.get("save_as"):
            body = resp.json() if s.get("response", "json") == "json" and resp.content else resp.text
            ctx[s["save_as"]] = body
            ctx[f"{s['save_as']}_status"] = resp.status_code

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
        path = self._out_path(name)
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=s.get("delimiter", ";"))
            w.writerow([c["header"] for c in s["columns"]])
            for row in rows:
                local = {**ctx, "row": row}
                cells = []
                for c in s["columns"]:
                    v = self.render(c["value"], local)
                    # proteção contra injeção de fórmulas no Excel
                    cells.append("'" + v if v.startswith(CSV_FORMULA_PREFIX) else v)
                w.writerow(cells)
        self._register_file(name)
        self.log(f"[{s['id']}] ficheiro {name} criado ({len(rows)} linha(s))")

    def step_text_write(self, s, ctx):
        name = self.render(s["file"], ctx)
        self._out_path(name).write_text(self.render(s["content"], ctx), encoding="utf-8")
        self._register_file(name)
        self.log(f"[{s['id']}] ficheiro {name} criado")

    def step_email(self, s, ctx):
        c = self._cred(s["credential"], {"smtp"})
        to = [self.render(x, ctx).strip() for x in s["to"]]
        cc = [self.render(x, ctx).strip() for x in s.get("cc", [])]
        for addr in to + cc:
            if not EMAIL_RE.match(addr):
                raise ValueError(f"endereço de email inválido: {addr!r}")
        msg = EmailMessage()
        msg["From"] = c.get("from_address") or c["username"]
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = self.render(s["subject"], ctx)
        msg.set_content(self.render(s["body"], ctx))
        for a in s.get("attachments", []):
            name = self.render(a, ctx)
            if name not in self.files:
                raise ValueError(f"anexo não foi produzido por este fluxo: {name}")
            msg.add_attachment(self._out_path(name).read_bytes(), maintype="application",
                               subtype="octet-stream", filename=name)
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
        n_att = len(s.get("attachments", []))
        self.log(f"[{s['id']}] email enviado para {len(to) + len(cc)} destinatário(s), {n_att} anexo(s)")

    def step_sql_query(self, s, ctx):
        c = self._cred(s["credential"], {"mssql"})
        params = {k: self.render(v, ctx) for k, v in (s.get("params") or {}).items()}
        if self.sql_connect is None:
            import pymssql  # dependência opcional: só necessária para fluxos com SQL Server

            connect = pymssql.connect
        else:
            connect = self.sql_connect
        conn = connect(server=c["server"], port=str(c.get("port") or 1433), user=c["username"],
                       password=c["password"], database=c["database"], login_timeout=30, timeout=600)
        try:
            cur = conn.cursor(as_dict=True)
            cur.execute(s["query"], params or None)
            rows = cur.fetchall() if cur.description else []
            if s.get("read_only", True):
                conn.rollback()  # garante que nada é gravado
            else:
                conn.commit()
        finally:
            conn.close()
        with self.lock:
            self.counters["sql_queries"] += 1
        self.log(f"[{s['id']}] consulta SQL devolveu {len(rows)} linha(s)")
        if s.get("save_as"):
            ctx[s["save_as"]] = rows


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
