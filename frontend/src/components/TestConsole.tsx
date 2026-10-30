import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Run } from "../types";
import { StatusBadge } from "./ui";

interface LogLine { seq: number; ts: string; level: string; source: string; message: string }
const TERMINAL = ["SUCCEEDED", "FAILED", "CANCELLED"];

/** Consola da execução de teste: estado, duração e logs em direto. "linha N" nos erros leva ao código. */
export function TestConsole({ runId, onGotoLine, onClose }: {
  runId: string; onGotoLine?: (line: number) => void; onClose: () => void;
}) {
  const [run, setRun] = useState<Run | null>(null);
  const [lines, setLines] = useState<LogLine[]>([]);
  const last = useRef(0);
  const box = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [r, l] = await Promise.all([
          api.get<Run>(`/api/runs/${runId}`),
          api.get<{ lines: LogLine[] }>(`/api/runs/${runId}/logs?after_seq=${last.current}`),
        ]);
        if (stop) return;
        setRun(r);
        if (l.lines.length) {
          last.current = l.lines[l.lines.length - 1].seq;
          setLines((prev) => [...prev, ...l.lines]);
          requestAnimationFrame(() => box.current?.scrollTo(0, box.current.scrollHeight));
        }
        if (!TERMINAL.includes(r.status)) timer = setTimeout(poll, 1500);
      } catch {
        if (!stop) timer = setTimeout(poll, 3000);
      }
    }
    poll();
    return () => { stop = true; clearTimeout(timer); };
  }, [runId]);

  const seconds = run?.started_at
    ? Math.round(((run.finished_at ? Date.parse(run.finished_at) : Date.now()) - Date.parse(run.started_at)) / 1000)
    : null;
  return (
    <section className="card test-console">
      <header className="card-header">
        <h2>{run?.dry_run ? "Teste (simulação)" : "Execução"}</h2>
        <div className="actions">
          {run && <StatusBadge status={run.status} />}
          {seconds !== null && <span className="muted small">{seconds}s</span>}
          <Link className="btn btn-small" to={`/runs/${runId}`}>Abrir execução</Link>
          <button className="btn btn-small" onClick={onClose}>Fechar</button>
        </div>
      </header>
      <div className="card-body">
        {run?.dry_run && (
          <p className="muted small">Simulação: os pedidos GET e as consultas SQL são feitos; POST/PUT/DELETE, emails e
            escritas SQL não são, e os ficheiros persistentes não mudam.</p>
        )}
        {run && ["QUEUED", "PENDING"].includes(run.status) && (
          <p className="alert alert-info">À espera de um worker… (confirme que o worker está a correr)</p>
        )}
        <pre className="logs" ref={box}>
          {lines.length === 0 && <span className="muted">Sem linhas de log.</span>}
          {lines.map((l) => <LogText key={l.seq} line={l} onGotoLine={onGotoLine} />)}
        </pre>
      </div>
    </section>
  );
}

function LogText({ line, onGotoLine }: { line: LogLine; onGotoLine?: (n: number) => void }) {
  const parts = line.message.split(/(linha \d+)/g);
  return (
    <div className={`log-${line.level.toLowerCase()}`}>
      <span className="muted">{new Date(line.ts).toLocaleTimeString("pt-PT")}</span>{" "}
      {parts.map((p, i) => {
        const m = /^linha (\d+)$/.exec(p);
        return m && onGotoLine
          ? <button key={i} className="link-button" onClick={() => onGotoLine(Number(m[1]))}>{p}</button>
          : <span key={i}>{p}</span>;
      })}
    </div>
  );
}
