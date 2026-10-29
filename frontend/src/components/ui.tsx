import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { AVAILABILITY_LABEL, FAILURE_LABEL, RISK_LABEL, STATUS_LABEL, TRIGGER_LABEL, fmtDate, fmtDuration } from "../format";
import type { RunBrief, RunStatus } from "../types";

export function StatusBadge({ status }: { status: RunStatus }) {
  return <span className={`badge status-${status.toLowerCase()}`}>{STATUS_LABEL[status] ?? status}</span>;
}

export function AvailabilityBadge({ value, enabled }: { value: string; enabled: boolean }) {
  const v = !enabled && value === "available" ? "disabled" : value;
  return <span className={`badge avail-${v}`}>{AVAILABILITY_LABEL[v] ?? v}</span>;
}

export function RiskBadge({ level }: { level: string }) {
  return <span className={`badge risk-${level}`}>Risco {RISK_LABEL[level] ?? level}</span>;
}

export function ErrorBox({ error }: { error: string | null | undefined }) {
  if (!error) return null;
  return (
    <div className="alert alert-error" role="alert">
      {error}
    </div>
  );
}

export function Card({ title, children, actions }: { title?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-header">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted empty">{children}</p>;
}

export function RunsTable({ runs, showBot = true }: { runs: RunBrief[]; showBot?: boolean }) {
  if (!runs.length) return <Empty>Sem execuções.</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Estado</th>
            {showBot && <th>Bot</th>}
            <th>Origem</th>
            <th>Criada</th>
            <th>Duração</th>
            <th>Detalhe</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td>
                <StatusBadge status={r.status} />{r.dry_run && <span className="badge">simulação</span>}
                {r.needs_review && <span className="badge review" title="Pode ter produzido efeitos externos">Rever</span>}
              </td>
              {showBot && <td>{r.bot_name}</td>}
              <td>{TRIGGER_LABEL[r.trigger_source] ?? r.trigger_source}</td>
              <td>{fmtDate(r.created_at)}</td>
              <td>{fmtDuration(r.started_at, r.finished_at)}</td>
              <td>
                <Link to={`/runs/${r.id}`}>{r.failure_reason ? FAILURE_LABEL[r.failure_reason] ?? r.failure_reason : "Abrir"}</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
