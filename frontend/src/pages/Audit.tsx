import { useState } from "react";
import { qs } from "../api";
import { Card, ErrorBox } from "../components/ui";
import { fmtDate } from "../format";
import { useResource } from "../hooks";

interface AuditRow {
  id: number; created_at: string; actor_type: string; actor_id: string | null; action: string;
  resource_type: string; resource_id: string | null; outcome: string; details: Record<string, unknown>; ip: string | null;
}

export function Audit() {
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const { data, error } = useResource<AuditRow[]>(`/api/admin/audit${qs({ actor, action, limit: 200 })}`);
  return (
    <>
      <h1>Auditoria</h1>
      <div className="toolbar">
        <input placeholder="Ator" value={actor} onChange={(e) => setActor(e.target.value)} />
        <input placeholder="Ação (prefixo, ex.: run.)" value={action} onChange={(e) => setAction(e.target.value)} />
      </div>
      <ErrorBox error={error} />
      <Card>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Data</th><th>Ator</th><th>Ação</th><th>Recurso</th><th>Resultado</th><th>Contexto</th></tr></thead>
            <tbody>
              {(data ?? []).map((a) => (
                <tr key={a.id} className={a.outcome !== "success" ? "row-bad" : ""}>
                  <td>{fmtDate(a.created_at)}</td>
                  <td>{a.actor_type}:{a.actor_id ?? "—"}</td>
                  <td><code>{a.action}</code></td>
                  <td>{a.resource_type}:{a.resource_id ?? "—"}</td>
                  <td>{a.outcome}</td>
                  <td><code className="small">{JSON.stringify(a.details)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
