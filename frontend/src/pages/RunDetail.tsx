import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { Card, ErrorBox, KeyValue, StatusBadge } from "../components/ui";
import { FAILURE_LABEL, TRIGGER_LABEL, fmtDate, fmtDuration } from "../format";
import { useResource } from "../hooks";
import type { Run } from "../types";

interface LogLine { seq: number; ts: string; level: string; source: string; message: string }

const ACTIVE = ["PENDING", "WAITING_APPROVAL", "QUEUED", "RUNNING"];

function Logs({ runId, active }: { runId: string; active: boolean }) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const last = useRef(0);
  const box = useRef<HTMLPreElement>(null);
  useEffect(() => {
    let stop = false;
    async function poll() {
      try {
        const r = await api.get<{ lines: LogLine[] }>(`/api/runs/${runId}/logs?after_seq=${last.current}`);
        if (!stop && r.lines.length) {
          last.current = r.lines[r.lines.length - 1].seq;
          setLines((prev) => [...prev, ...r.lines]);
          requestAnimationFrame(() => box.current?.scrollTo(0, box.current.scrollHeight));
        }
      } catch { /* mostra o que já existe */ }
    }
    poll();
    const t = active ? setInterval(poll, 2000) : undefined;
    return () => { stop = true; if (t) clearInterval(t); };
  }, [runId, active]);
  return (
    <pre className="logs" ref={box}>
      {lines.length === 0 && <span className="muted">Sem linhas de log.</span>}
      {lines.map((l) => (
        <div key={l.seq} className={`log-${l.level.toLowerCase()}`}>
          <span className="muted">{new Date(l.ts).toLocaleTimeString("pt-PT")}</span>{" "}
          <span className="log-src">[{l.source}]</span> {l.message}
        </div>
      ))}
    </pre>
  );
}

interface Artifact { id: number; name: string; size_bytes: number; created_at: string }

function Artifacts({ runId, active }: { runId: string; active: boolean }) {
  const { data } = useResource<Artifact[]>(`/api/runs/${runId}/artifacts`, active ? 5000 : undefined);
  if (!data?.length) return null;
  return (
    <Card title="Ficheiros produzidos">
      <ul className="plain">
        {data.map((a) => (
          <li key={a.id}>
            <a href={`/api/runs/${runId}/artifacts/${a.id}`} download>{a.name}</a>{" "}
            <span className="muted small">{(a.size_bytes / 1024).toFixed(1)} KB · {fmtDate(a.created_at)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function RunDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: run, error, reload } = useResource<Run>(`/api/runs/${id}`, 3000);
  const [actionError, setActionError] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [confirmRetry, setConfirmRetry] = useState(false);

  async function act(fn: () => Promise<unknown>) {
    setActionError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setActionError((e as ApiError).message);
    }
  }

  if (error) return <ErrorBox error={error} />;
  if (!run) return <p className="muted">A carregar…</p>;
  const active = ACTIVE.includes(run.status);
  const summary = { ...run.result_summary };

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/runs" className="muted">← Execuções</Link>
          <h1>
            <Link to={`/bots/${run.bot_key}`}>{run.bot_name}</Link> <StatusBadge status={run.status} />
          </h1>
          <code className="muted">{run.id}</code>
        </div>
        <div className="actions">
          {run.permissions?.cancel && active && !run.cancel_requested && (
            <button className="btn btn-danger" onClick={() => act(() => api.post(`/api/runs/${run.id}/cancel`))}>Cancelar</button>
          )}
          {run.cancel_requested && run.status === "RUNNING" && <span className="badge">Cancelamento pedido…</span>}
          {run.permissions?.retry && (run.status === "FAILED" || run.status === "CANCELLED") && (
            <button className="btn" onClick={() =>
              run.needs_review && !confirmRetry
                ? setConfirmRetry(true)
                : act(async () => {
                    const r = await api.post<{ run_id: string }>(`/api/runs/${run.id}/retry`, { confirm_side_effects_checked: confirmRetry });
                    navigate(`/runs/${r.run_id}`);
                  })}>
              Repetir
            </button>
          )}
        </div>
      </div>
      {run.needs_review && (
        <div className="alert alert-warn">
          <strong>Requer revisão.</strong> O resultado desta execução não foi confirmado e o bot pode ter produzido efeitos
          externos (ex.: alterações no Cyclos, emails, callbacks). Verifique antes de repetir.
          {confirmRetry && (
            <div className="confirm">
              <p>Confirma que verificou os efeitos da execução anterior e que repetir é seguro?</p>
              <button className="btn btn-danger" onClick={() => act(async () => {
                const r = await api.post<{ run_id: string }>(`/api/runs/${run.id}/retry`, { confirm_side_effects_checked: true });
                navigate(`/runs/${r.run_id}`);
              })}>Sim, verifiquei — repetir</button>{" "}
              <button className="btn" onClick={() => setConfirmRetry(false)}>Não</button>
            </div>
          )}
        </div>
      )}
      {run.status === "WAITING_APPROVAL" && run.permissions?.approve && (
        <Card title="Aprovação">
          <p>Esta execução foi pedida por <strong>{run.requested_by_name ?? "regra automática"}</strong> e aguarda aprovação.</p>
          <textarea placeholder="Comentário (opcional)" value={comment} maxLength={500} onChange={(e) => setComment(e.target.value)} />
          <div className="actions">
            <button className="btn btn-primary" onClick={() => act(() => api.post(`/api/runs/${run.id}/approval`, { approve: true, comment }))}>Aprovar</button>
            <button className="btn btn-danger" onClick={() => act(() => api.post(`/api/runs/${run.id}/approval`, { approve: false, comment }))}>Rejeitar</button>
          </div>
        </Card>
      )}
      <ErrorBox error={actionError} />
      <div className="grid-2">
        <Card title="Execução">
          <KeyValue items={[
            ["Origem", TRIGGER_LABEL[run.trigger_source] ?? run.trigger_source],
            ["Pedida por", run.requested_by_name ?? "Sistema"],
            ["Aprovada por", run.approved_by_name ? `${run.approved_by_name} (${fmtDate(run.approved_at)})` : "—"],
            ["Criada", fmtDate(run.created_at)],
            ["Iniciada", fmtDate(run.started_at)],
            ["Terminada", fmtDate(run.finished_at)],
            ["Duração", fmtDuration(run.started_at, run.finished_at)],
            ["Timeout", `${Math.round(run.timeout_seconds / 60)} min`],
            ["Versão do fluxo", run.flow_version ?? "—"],
            ["Último heartbeat", fmtDate(run.last_heartbeat_at)],
          ]} />
        </Card>
        <Card title="Resultado">
          <KeyValue items={[
            ["Estado", <StatusBadge status={run.status} />],
            ["Motivo da falha", run.failure_reason ? FAILURE_LABEL[run.failure_reason] ?? run.failure_reason : "—"],
            ["Código de saída", run.exit_code ?? "—"],
            ["Parâmetros", Object.keys(run.parameters).length ? <code>{JSON.stringify(run.parameters)}</code> : "—"],
          ]} />
          {Object.keys(summary).length > 0 && <pre className="json">{JSON.stringify(summary, null, 2)}</pre>}
        </Card>
      </div>
      {(run.trigger_rule || run.trigger_event || run.parent_run_id || run.retry_of_run_id) && (
        <Card title="Origem do evento">
          <KeyValue items={[
            ["Regra", run.trigger_rule ? `${run.trigger_rule.name} (${TRIGGER_LABEL[run.trigger_rule.type] ?? run.trigger_rule.type})` : "—"],
            ["Evento", run.trigger_event ? <code>{run.trigger_event.dedup_key}</code> : "—"],
            ["Recebido", fmtDate(run.trigger_event?.received_at)],
            ["Execução anterior (cadeia)", run.parent_run_id ? <Link to={`/runs/${run.parent_run_id}`}>{run.parent_run_id}</Link> : "—"],
            ["Repetição de", run.retry_of_run_id ? <Link to={`/runs/${run.retry_of_run_id}`}>{run.retry_of_run_id}</Link> : "—"],
          ]} />
        </Card>
      )}
      <Artifacts runId={run.id} active={active} />
      <Card title="Logs">
        <Logs runId={run.id} active={active} />
      </Card>
    </>
  );
}
