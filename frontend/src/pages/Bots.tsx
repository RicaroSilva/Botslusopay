import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { hasRole, useAuth } from "../auth";
import { AvailabilityBadge, ErrorBox, RiskBadge, StatusBadge } from "../components/ui";
import { fmtDate } from "../format";
import { useResource } from "../hooks";
import type { Bot } from "../types";
import { RunButton } from "./RunDialog";

export function Bots() {
  const { user } = useAuth();
  const { data, error, reload } = useResource<Bot[]>("/api/bots", 15000);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const categories = useMemo(() => [...new Set((data ?? []).map((b) => b.category).filter(Boolean))].sort(), [data]);
  const bots = (data ?? []).filter(
    (b) =>
      (!category || b.category === category) &&
      (!q || `${b.name} ${b.description} ${b.key}`.toLowerCase().includes(q.toLowerCase())),
  );
  return (
    <>
      <div className="page-head">
        <h1>Catálogo de bots</h1>
        {hasRole(user, "admin") && <Link className="btn btn-primary" to="/flows/new">+ Novo fluxo</Link>}
      </div>
      <div className="toolbar">
        <input placeholder="Pesquisar…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Todas as categorias</option>
          {categories.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </div>
      <ErrorBox error={error} />
      <div className="bot-grid">
        {bots.map((b) => (
          <article key={b.key} className="bot-card">
            <header>
              <h3>{b.name}</h3>
              <div className="badges">
                <AvailabilityBadge value={b.availability} enabled={b.enabled} />
                <RiskBadge level={b.risk_level} />
                {b.requires_approval && <span className="badge">Exige aprovação</span>}
              </div>
            </header>
            <p className="desc">{b.description}</p>
            <dl className="kv compact">
              <div><dt>Categoria</dt><dd>{b.category || "—"}</dd></div>
              <div><dt>Execução</dt><dd>{b.adapter === "flow" ? <span className="badge avail-available">Fluxo nativo v{b.current_flow_version}</span> : <code>{b.adapter}</code>}</dd></div>
              <div>
                <dt>Última execução</dt>
                <dd>{b.last_run ? <><StatusBadge status={b.last_run.status} /> {fmtDate(b.last_run.created_at)}</> : "—"}</dd>
              </div>
            </dl>
            <footer>
              <Link className="btn" to={`/bots/${b.key}`}>Detalhes</Link>
              {b.permissions.includes("execute") && <RunButton bot={b} onDone={reload} />}
            </footer>
          </article>
        ))}
      </div>
    </>
  );
}
