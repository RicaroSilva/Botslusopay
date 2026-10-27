import { useSearchParams } from "react-router-dom";
import { qs } from "../api";
import { Card, ErrorBox, RunsTable } from "../components/ui";
import { STATUS_LABEL } from "../format";
import { useResource } from "../hooks";
import type { Bot, Run } from "../types";

export function Runs({ fixedStatus, title = "Execuções" }: { fixedStatus?: string; title?: string }) {
  const [params, setParams] = useSearchParams();
  const filters = {
    bot: params.get("bot") ?? "",
    status: fixedStatus ?? params.get("status") ?? "",
    requested_by: params.get("requested_by") ?? "",
    date_from: params.get("date_from") ?? "",
    date_to: params.get("date_to") ?? "",
    needs_review: params.get("needs_review") ?? "",
  };
  const { data, error } = useResource<Run[]>(`/api/runs${qs({ ...filters, limit: 100 })}`, 5000);
  const { data: bots } = useResource<Bot[]>("/api/bots");
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next);
  };
  return (
    <>
      <h1>{title}</h1>
      <div className="toolbar">
        <select value={filters.bot} onChange={(e) => set("bot", e.target.value)} aria-label="Bot">
          <option value="">Todos os bots</option>
          {(bots ?? []).map((b) => <option key={b.key} value={b.key}>{b.name}</option>)}
        </select>
        {!fixedStatus && (
          <select value={filters.status} onChange={(e) => set("status", e.target.value)} aria-label="Estado">
            <option value="">Todos os estados</option>
            {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        )}
        <input placeholder="Utilizador" value={filters.requested_by} onChange={(e) => set("requested_by", e.target.value)} />
        <label className="inline">De <input type="date" value={filters.date_from} onChange={(e) => set("date_from", e.target.value)} /></label>
        <label className="inline">Até <input type="date" value={filters.date_to} onChange={(e) => set("date_to", e.target.value)} /></label>
        <label className="inline check">
          <input type="checkbox" checked={filters.needs_review === "true"} onChange={(e) => set("needs_review", e.target.checked ? "true" : "")} />
          Só por rever
        </label>
      </div>
      <ErrorBox error={error} />
      <Card>
        <RunsTable runs={data ?? []} />
      </Card>
    </>
  );
}
