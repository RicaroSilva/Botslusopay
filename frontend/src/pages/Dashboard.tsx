import { Link } from "react-router-dom";
import { Card, Empty, ErrorBox, RunsTable } from "../components/ui";
import { fmtDate } from "../format";
import { useResource } from "../hooks";
import type { Dashboard as D } from "../types";

function Stat({ label, value, tone, to }: { label: string; value: number; tone?: string; to?: string }) {
  const body = (
    <div className={`stat ${tone ?? ""}`}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
  return to ? <Link to={to} className="stat-link">{body}</Link> : body;
}

export function Dashboard() {
  const { data, error } = useResource<D>("/api/dashboard", 10000);
  return (
    <>
      <h1>Dashboard</h1>
      <ErrorBox error={error} />
      {data && (
        <>
          <div className="stats">
            <Stat label="Bots disponíveis" value={data.bots_available} to="/bots" />
            <Stat label="Bots registados" value={data.bots_total} to="/bots" />
            <Stat label="Em execução" value={data.running} tone="info" to="/runs?status=RUNNING" />
            <Stat label="Em fila" value={data.queued} to="/runs?status=QUEUED" />
            <Stat label="A aguardar aprovação" value={data.waiting_approval} tone="warn" to="/approvals" />
            <Stat label="Concluídas (7 dias)" value={data.succeeded_7d} tone="ok" to="/runs?status=SUCCEEDED" />
            <Stat label="Falhadas (7 dias)" value={data.failed_7d} tone="bad" to="/runs?status=FAILED" />
            <Stat label="Por rever" value={data.needs_review} tone="warn" to="/runs?needs_review=true" />
          </div>
          <div className="grid-2">
            <Card title="Falhas recentes">
              <RunsTable runs={data.recent_failures} />
            </Card>
            <Card title="Últimas execuções">
              <RunsTable runs={data.recent_runs} />
            </Card>
          </div>
          <div className="grid-2">
            <Card title="Workers">
              {data.workers.length ? (
                <ul className="plain">
                  {data.workers.map((w) => (
                    <li key={w.name}>
                      <span className={`dot ${w.online ? "on" : "off"}`} /> {w.name}{" "}
                      <span className="muted">— visto {fmtDate(w.last_seen_at)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>Nenhum worker registado.</Empty>
              )}
            </Card>
            {data.activity.length > 0 && (
              <Card title="Últimas atividades">
                <ul className="plain activity">
                  {data.activity.map((a, i) => (
                    <li key={i} className={a.outcome !== "success" ? "bad" : ""}>
                      <span className="muted">{fmtDate(a.ts)}</span> <strong>{a.actor ?? "sistema"}</strong> {a.action}{" "}
                      <span className="muted">{a.resource}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        </>
      )}
    </>
  );
}
